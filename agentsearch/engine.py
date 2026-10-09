"""SQLite-backed search. Source files are never modified by this module.

The index describes the last enumeration, not an atomic filesystem snapshot.
Literal results are verified against current file bytes. Fuzzy name fallback
and short patterns are bounded scans; no whole-disk latency claim is made.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache, wraps
import hashlib
import heapq
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
from typing import Any

from .config import SearchConfig, is_reparse, expand_windows_alias
from ._version import VERSION
from .file_identity import identity

SCHEMA_VERSION = "1"
MAX_MATCH_TEXT_CHARS = 32000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fold_path(path: str | Path) -> str:
    value = os.path.normpath(str(path))
    return os.path.normcase(value)


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}.")
    return value


def _text(value: Any, name: str, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError(f"{name} must be nonempty text of at most {maximum} characters without NUL or unpaired surrogates.")
    return value


def _phrase(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _decode(raw: bytes) -> tuple[str | None, str]:
    try:
        if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            text = raw.decode("utf-32")
        elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            if b"\x00" in raw:
                return None, "binary"
            text = raw.decode("utf-8-sig")
        if "\x00" in text:
            return None, "binary"
        return text, "indexed"
    except UnicodeDecodeError:
        return None, "unsupported_encoding"


def _snapshot(method):
    """Pin candidates, configuration and receipts to ONE SQLite read snapshot.

    File bytes are still live reads, not part of the database snapshot.
    One engine belongs to one thread; independent workers open independent engines.
    """
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        if self.conn.in_transaction:
            raise ValueError("Finish the current transaction before running a query.")
        self.conn.execute("BEGIN")
        try:
            return method(self, *args, **kwargs)
        finally:
            self.conn.set_progress_handler(None, 0)
            self.conn.rollback()  # End read snapshot, including on interruption.
    return wrapped


class _RankedHit:
    """Heap head is the WORST item: lowest score, then largest path.

    Final public order is highest score, then path ascending, including at a
    top-k tie boundary. Filesystem enumeration order cannot choose the winners.
    """
    __slots__ = ("score", "path", "hit")

    def __init__(self, score: float, path: str, hit: dict):
        self.score, self.path, self.hit = score, path, hit

    def __lt__(self, other):
        if self.score != other.score:
            return self.score < other.score
        return self.path > other.path


def _fuzzy_scorer():
    """Per-query bounded cache; preserve SequenceMatcher argument orientation.

    Both pruning bounds are >= the exact ratio. Rejecting a bound < 0.65
    cannot remove an accepted (>= 0.65) piece. No approximate shortlist is used.
    """
    @lru_cache(maxsize=8192)
    def ratio(term: str, piece: str) -> float:
        total = len(term) + len(piece)
        if not total or 2 * min(len(term), len(piece)) / total < 0.65:
            return 0.0
        matcher = SequenceMatcher(None, term, piece, autojunk=False)
        if matcher.quick_ratio() < 0.65:
            return 0.0
        return matcher.ratio()

    @lru_cache(maxsize=4096)
    def pieces(name: str) -> tuple[str, ...]:
        stem = Path(name).stem
        return tuple(dict.fromkeys((name, stem, *stem.replace("-", "_").split("_"))))

    return ratio, pieces


def _source_offset(line: str, folded_offset: int, case_sensitive: bool) -> int:
    """Translate casefolded positions back to original Unicode coordinates."""
    if case_sensitive or len(line.casefold()) == len(line):
        return folded_offset
    position = 0
    for index, character in enumerate(line):
        width = len(character.casefold())
        if position + width > folded_offset:
            return index
        position += width
    return len(line)


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Retry only the idempotent first-open journal-mode transition.

    SQLite can fail a journal-mode lock upgrade without invoking its usual
    busy handler. Concurrent first open therefore needs a narrow bounded retry,
    not a blanket retry of arbitrary queries or partially executed writes.
    """
    deadline = time.perf_counter() + 5.0
    delay = 0.01
    while True:
        try:
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise ValueError("SQLite did not enable WAL mode for the index.")
            return
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
            if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.perf_counter() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


class SearchEngine:
    def __init__(self, db_path: str | Path, config: SearchConfig | None = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA synchronous=FULL")
            tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and "meta" not in tables:
                raise ValueError("Not an AgentSearch index; use a new, dedicated database path.")
            if not tables:
                # Transactional initialization: two first-open processes serialize.
                _enable_wal(self.conn)
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                self.conn.execute("""CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, path_key TEXT NOT NULL,
                    root TEXT NOT NULL, name TEXT NOT NULL, name_fold TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL,
                    content_status TEXT NOT NULL, content_hash TEXT)""")
                self.conn.execute("CREATE INDEX IF NOT EXISTS files_path_key ON files(path_key)")
                self.conn.execute("CREATE INDEX IF NOT EXISTS files_root ON files(root)")
                self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS names_fts USING fts5(name, path, tokenize='trigram case_sensitive 1')")
                self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS contents_fts USING fts5(body, tokenize='trigram case_sensitive 1')")
                self._set_meta("schema_version", SCHEMA_VERSION)
            else:
                version = self._meta("schema_version")
                if version != SCHEMA_VERSION or not {"files", "names_fts", "contents_fts"}.issubset(tables):
                    raise ValueError("Unsupported or damaged AgentSearch index; use a new database path.")
                if self.conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                    raise ValueError("Index must use WAL mode; rebuild into a new database path.")
            stored = self._meta("config")
            if config is None:
                if stored is None:
                    raise ValueError("No configured index. Create configuration and run index first.")
                config = SearchConfig(**json.loads(stored))
            if not isinstance(config, SearchConfig):
                raise ValueError("config must be a SearchConfig instance.")
            self.config = config
            self._config_json = json.dumps(config.to_dict(), sort_keys=True)
            self._config_changed = stored is not None and stored != self._config_json
            if stored is None:
                self._set_meta("config", self._config_json)
            self.conn.commit()
        except Exception:
            self.conn.close()
            raise

    def __enter__(self) -> "SearchEngine":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else row[0]

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _ready(self) -> None:
        if self._config_changed or self._meta("config") != self._config_json:
            raise ValueError("Configuration differs from the saved index; run index first.")

    def _is_internal(self, path: Path) -> bool:
        if str(path) in {str(self.db_path), str(self.db_path) + "-wal", str(self.db_path) + "-shm", str(self.db_path) + "-journal"}:
            return True
        state_inside_root = any(self.db_path.parent.is_relative_to(Path(root)) for root in self.config.roots)
        if state_inside_root and str(self.db_path.parent) not in self.config.roots and path.is_relative_to(self.db_path.parent):
            return True
        return False

    def _checked_path(self, value: str | Path, directory: bool = False) -> Path:
        candidate = Path(_text(str(value), "path", 32768)).expanduser()
        if not candidate.is_absolute():
            raise ValueError("Use an absolute path inside a configured root.")
        candidate = expand_windows_alias(Path(os.path.abspath(candidate)))
        root = next((Path(r) for r in self.config.roots if candidate.is_relative_to(Path(r))), None)
        if root is None:
            raise ValueError("Path is outside configured roots.")
        current = root
        if is_reparse(root):
            raise ValueError("Configured root became a link or junction; reconfigure it.")
        relative = candidate.relative_to(root)
        excluded = {name.casefold() for name in self.config.exclude_dirs}
        for position, part in enumerate(relative.parts):
            current = current / part
            if is_reparse(current):
                raise ValueError("Links and Windows reparse points are not followed.")
            if (directory or position < len(relative.parts) - 1) and part.casefold() in excluded:
                raise ValueError("Path is under an excluded directory.")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or self._is_internal(resolved):
            raise ValueError("Path is outside the allowed source scope.")
        if directory and not resolved.is_dir():
            raise ValueError("scope must be a directory.")
        if not directory and not resolved.is_file():
            raise ValueError("Path must be a regular file.")
        return resolved

    def _load_text(self, path: Path) -> tuple[str | None, str, str | None, bool]:
        """Bound the read, verify scope again and note concurrent changes."""
        path = self._checked_path(path)
        expected = path.stat()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino) != (expected.st_dev, expected.st_ino):
                return None, "changed_during_read", None, True
            if not stat.S_ISREG(before.st_mode):
                return None, "not_regular", None, False
            if before.st_size > self.config.max_file_bytes:
                return None, "too_large", None, False
            raw = stream.read(self.config.max_file_bytes + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > self.config.max_file_bytes:
            return None, "too_large", None, False
        text, status = _decode(raw)
        changed = (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        try:
            final = self._checked_path(path).stat()
            changed = changed or identity(after) != identity(final)
        except (OSError, ValueError):
            changed = True
        return text, status, hashlib.sha256(raw).hexdigest(), changed

    def index(self, force: bool = False) -> dict:
        if type(force) is not bool:
            raise ValueError("force must be a boolean.")
        start = time.perf_counter()
        seen_count = updated = unchanged = removed = 0
        skipped: Counter = Counter()
        errors: list[dict] = []
        error_count = 0
        def error(path: Path, exc: Exception) -> None:
            nonlocal error_count
            error_count += 1
            if len(errors) < 20:
                errors.append({"path": str(path), "error": str(exc)})
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            reset = self._meta("config") != self._config_json
            if reset:
                self.conn.execute("DELETE FROM names_fts")
                self.conn.execute("DELETE FROM contents_fts")
                self.conn.execute("DELETE FROM files")
            self.conn.execute("CREATE TEMP TABLE IF NOT EXISTS scan_seen (path TEXT PRIMARY KEY)")
            self.conn.execute("DELETE FROM scan_seen")
            excluded = {name.casefold() for name in self.config.exclude_dirs}
            for root_value in self.config.roots:
                root = Path(root_value)
                queue = [root]
                while queue:
                    directory = queue.pop()
                    try:
                        if is_reparse(directory):
                            raise ValueError("Directory became a link or reparse point.")
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                path = Path(entry.path)
                                try:
                                    info = entry.stat(follow_symlinks=False)
                                    if entry.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400):
                                        skipped["links_or_reparse"] += 1
                                        continue
                                    if self._is_internal(path):
                                        skipped["index_state"] += 1
                                        continue
                                    if entry.is_dir(follow_symlinks=False):
                                        if entry.name.casefold() in excluded:
                                            skipped["excluded_directories"] += 1
                                            continue
                                        queue.append(path)
                                        continue
                                    if not stat.S_ISREG(info.st_mode):
                                        skipped["not_regular"] += 1
                                        continue
                                    value = _text(str(path), "filesystem path", 32768)
                                    self.conn.execute("INSERT OR IGNORE INTO scan_seen(path) VALUES (?)", (value,))
                                    seen_count += 1
                                    old = self.conn.execute("SELECT * FROM files WHERE path=?", (value,)).fetchone()
                                    signature = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                                    if not force and old is not None and signature == (old["size"], old["mtime_ns"], old["ctime_ns"]) and old["content_status"] not in ("unreadable", "changed_during_read"):
                                        unchanged += 1
                                        continue
                                    body = None
                                    content_hash = None
                                    content_status = "too_large"
                                    if info.st_size <= self.config.max_file_bytes:
                                        try:
                                            body, content_status, content_hash, changing = self._load_text(path)
                                            if changing:
                                                body = None
                                                content_status = "changed_during_read"
                                                error(path, OSError("File changed while reading; reindex required."))
                                        except (OSError, ValueError) as exc:
                                            content_status = "unreadable"
                                            error(path, exc)
                                    if old is None:
                                        cursor = self.conn.execute("INSERT INTO files(path,path_key,root,name,name_fold,size,mtime_ns,ctime_ns,content_status,content_hash) VALUES (?,?,?,?,?,?,?,?,?,?)", (value, _fold_path(value), root_value, path.name, path.name.casefold(), *signature, content_status, content_hash))
                                        rowid = cursor.lastrowid
                                        self.conn.execute("INSERT INTO names_fts(rowid,name,path) VALUES (?,?,?)", (rowid, path.name.casefold(), value.casefold()))
                                    else:
                                        rowid = old["id"]
                                        self.conn.execute("UPDATE files SET size=?,mtime_ns=?,ctime_ns=?,content_status=?,content_hash=? WHERE id=?", (*signature, content_status, content_hash, rowid))
                                        self.conn.execute("DELETE FROM contents_fts WHERE rowid=?", (rowid,))
                                    if body is not None:
                                        self.conn.execute("INSERT INTO contents_fts(rowid,body) VALUES (?,?)", (rowid, body.casefold()))
                                    updated += 1
                                except (OSError, ValueError) as exc:
                                    error(path, exc)
                    except (OSError, ValueError) as exc:
                        error(directory, exc)
            # A failed walk is never interpreted as mass deletion. Retained rows
            # are still checked against the source when returned by a search.
            if not error_count:
                self.conn.execute("DELETE FROM names_fts WHERE rowid IN (SELECT id FROM files WHERE path NOT IN (SELECT path FROM scan_seen))")
                self.conn.execute("DELETE FROM contents_fts WHERE rowid IN (SELECT id FROM files WHERE path NOT IN (SELECT path FROM scan_seen))")
                removed = self.conn.execute("DELETE FROM files WHERE path NOT IN (SELECT path FROM scan_seen)").rowcount
            self._set_meta("config", self._config_json)
            self._config_changed = False
            counts = dict(self.conn.execute("SELECT content_status,COUNT(*) FROM files GROUP BY content_status").fetchall())
            generation = int(self._meta("generation") or "0") + 1
            self._set_meta("generation", str(generation))
            receipt = {"ok": True, "generation": generation, "force": force, "complete": error_count == 0, "finished_at": _now(), "scanned_files": seen_count,
                       "updated": updated, "unchanged": unchanged, "removed": removed, "config_reset": reset,
                       "skipped": dict(skipped), "content_counts": counts, "errors": errors, "error_count": error_count,
                       "warnings": ["Some paths could not be read; deletion cleanup was deferred."] if error_count else [],
                       "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
            self._set_meta("last_index", json.dumps(receipt))
            self.conn.commit()
            return receipt
        except BaseException:
            self.conn.rollback()
            raise

    def _coverage(self) -> dict:
        value = self._meta("last_index")
        last = json.loads(value) if value else None
        return {"indexed_at": last["finished_at"] if last else None,
                "generation": int(self._meta("generation") or "0"),
                "candidate_source": "committed_index", "atomic_filesystem_snapshot": False,
                "enumeration_complete": last["complete"] if last else False,
                "freshness": "last_index_scan; source matches reread on query",
                "max_file_bytes": self.config.max_file_bytes,
                "content_counts": last.get("content_counts", {}) if last else {}}

    @_snapshot
    def status(self) -> dict:
        self._ready()
        return {"ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
                "database": str(self.db_path), "config": self.config.to_dict(),
                "files": self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
                "text_files": self.conn.execute("SELECT COUNT(*) FROM files WHERE content_status='indexed'").fetchone()[0],
                "index": self._coverage(), "last_index": json.loads(self._meta("last_index") or "null"),
                "backend": "sqlite_fts5_trigram", "watcher": "polling", "warnings": []}

    def _filters(self, scope: str | None, ext: str | None, only_text: bool = False) -> tuple[str, list]:
        terms: list[str] = []
        values: list = []
        if scope is not None:
            path = self._checked_path(scope, directory=True)
            prefix = _fold_path(path).rstrip(os.sep) + os.sep
            terms.append("substr(f.path_key,1,?)=?")
            values.extend((len(prefix), prefix))
        if ext is not None:
            ext = _text(ext, "ext", 100).lstrip(".").casefold()
            if not ext or any(c in ext for c in "/\\\x00"):
                raise ValueError("ext must be a file extension.")
            terms.append("substr(f.name_fold,-?)=?")
            values.extend((len(ext) + 1, "." + ext))
        if only_text:
            terms.append("f.content_status='indexed'")
        return (" AND " + " AND ".join(terms) if terms else ""), values

    def _begin_query(self, budget_ms: int) -> float:
        _integer(budget_ms, "budget_ms", 1, 30000)
        deadline = time.perf_counter() + budget_ms / 1000
        self.conn.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 1000)
        return deadline

    @_snapshot
    def search(self, query: str, limit: int = 20, scope: str | None = None, ext: str | None = None, budget_ms: int = 1000) -> dict:
        self._ready()
        if self._meta("last_index") is None:
            raise ValueError("No completed index scan. Run index before searching.")
        query = _text(query, "query").strip().casefold()
        _integer(limit, "limit", 1, 200)
        suffix, values = self._filters(scope, ext)
        terms = query.split()
        if len(terms) > 32:
            raise ValueError("query must contain at most 32 words.")
        long_terms = [term for term in terms if len(term) >= 3]
        start = time.perf_counter()
        deadline = self._begin_query(budget_ms)
        complete = True
        warnings: list[str] = []
        heap: list[_RankedHit] = []
        matches = examined = 0
        strategy = "fts_literal" if long_terms else "literal_scan"
        def collect(row: sqlite3.Row, score: float, kind: str) -> None:
            nonlocal matches, complete
            # Count matching INDEXED names. Once top-k is full, a worse
            # candidate cannot affect the answer: avoid filesystem checks.
            # A rejected/unavailable contender never displaces a valid hit.
            matches += 1
            contender = _RankedHit(score, row["path"], {})
            if len(heap) >= limit and not heap[0] < contender:
                return
            try:
                path = self._checked_path(row["path"])
                info = path.stat()
            except (OSError, ValueError):
                complete = False
                if len(warnings) < 20:
                    warnings.append(f"An indexed path is no longer accessible: {row['path']}")
                return
            hit = {"path": str(path), "name": path.name, "score": round(score, 4), "size": info.st_size,
                   "mtime_ns": info.st_mtime_ns, "match": kind, "metadata_changed": (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (row["size"], row["mtime_ns"], row["ctime_ns"])}
            item = _RankedHit(score, str(path), hit)
            if len(heap) < limit:
                heapq.heappush(heap, item)
            elif heap[0] < item:
                heapq.heapreplace(heap, item)
        try:
            if long_terms:
                sql = "SELECT f.* FROM files f JOIN names_fts ON names_fts.rowid=f.id WHERE names_fts MATCH ?" + suffix
                args = [" AND ".join(_phrase(term) for term in long_terms), *values]
            else:
                sql = "SELECT f.* FROM files f WHERE 1=1" + suffix
                args = values
            for row in self.conn.execute(sql, args):
                examined += 1
                if time.perf_counter() >= deadline:
                    complete = False
                    break
                full = row["path"].casefold()
                name = row["name_fold"]
                if all(term in full for term in terms):
                    score = 1000 if name == query else 900 if name.startswith(query) else 800 if query in name else 700
                    collect(row, score - len(name) / 10000, "literal")
            if not heap and complete:
                strategy = "fuzzy_bounded_scan"
                ratio, name_pieces = _fuzzy_scorer()
                for row in self.conn.execute("SELECT f.* FROM files f WHERE 1=1" + suffix, values):
                    examined += 1
                    if time.perf_counter() >= deadline:
                        complete = False
                        break
                    scores = []
                    for term in terms:
                        if term in row["path"].casefold():
                            best = 1.0
                        else:
                            best = max(ratio(term, piece) for piece in name_pieces(row["name_fold"]))
                        if best < 0.65:
                            break
                        scores.append(best)
                    if len(scores) == len(terms):
                        collect(row, 500 * sum(scores) / len(scores), "fuzzy")
        except sqlite3.OperationalError as exc:
            if "interrupt" not in str(exc).lower():
                raise
            complete = False
        finally:
            self.conn.set_progress_handler(None, 0)
        if time.perf_counter() >= deadline:
            complete = False
            warnings.append("Search budget exhausted; ranking and coverage are partial.")
        if matches > limit:
            complete = False
            warnings.append("Result limit reached; additional matches were omitted.")
        coverage = self._coverage()
        if not coverage["enumeration_complete"]:
            complete = False
            warnings.append("Last index enumeration was incomplete.")
        return {"ok": True, "hits": [item.hit for item in sorted(heap, key=lambda item: (-item.score, item.path))],
                "complete": complete, "strategy": strategy, "examined": examined, "matched": matches,
                "matched_scope": "indexed_candidates",
                "index": coverage, "warnings": warnings, "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}

    def grep(self, pattern: str, limit: int = 20, per_file: int = 3, scope: str | None = None,
             ext: str | None = None, budget_ms: int = 1000, case_sensitive: bool = False, fresh: bool = False) -> dict:
        pattern = _text(pattern, "pattern")
        if "\n" in pattern or "\r" in pattern:
            raise ValueError("Content search is line-based; patterns cannot contain newlines.")
        _integer(limit, "limit", 1, 200)
        _integer(per_file, "per_file", 1, 20)
        _integer(budget_ms, "budget_ms", 1, 30000)
        if type(fresh) is not bool or type(case_sensitive) is not bool:
            raise ValueError("fresh and case_sensitive must be booleans.")
        self._filters(scope, ext, only_text=True)  # Validate before optional writes.
        start = time.perf_counter()
        refresh = self.index() if fresh else None
        result = self._grep(pattern, limit, per_file, scope, ext, budget_ms, case_sensitive)
        if refresh is not None:
            result["refresh"] = refresh
        result["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
        return result

    @_snapshot
    def _grep(self, pattern: str, limit: int = 20, per_file: int = 3, scope: str | None = None,
              ext: str | None = None, budget_ms: int = 1000, case_sensitive: bool = False) -> dict:
        start = time.perf_counter()
        self._ready()
        if self._meta("last_index") is None:
            raise ValueError("No completed index scan. Run index or use fresh=true before searching.")
        suffix, values = self._filters(scope, ext, only_text=True)
        folded = pattern.casefold()
        needle = pattern if case_sensitive else folded
        indexed = len(folded) >= 3
        if indexed:
            sql = "SELECT f.* FROM files f JOIN contents_fts ON contents_fts.rowid=f.id WHERE contents_fts MATCH ?" + suffix + " ORDER BY f.path"
            args = [_phrase(folded), *values]
        else:
            # Scan cached text in SQLite/C; reread only matching candidates.
            # Same last-index freshness contract as >=3-character FTS searches.
            sql = "SELECT f.* FROM files f JOIN contents_fts ON contents_fts.rowid=f.id WHERE instr(contents_fts.body,?)>0" + suffix + " ORDER BY f.path"
            args = [folded, *values]
        deadline = self._begin_query(budget_ms)
        files: list[dict] = []
        complete = True
        examined = 0
        text_characters = 0
        stale_candidates = 0
        warnings: list[str] = []
        try:
            for row in self.conn.execute(sql, args):
                if time.perf_counter() >= deadline:
                    complete = False
                    warnings.append("Search budget exhausted.")
                    break
                examined += 1
                try:
                    body, content_status, digest, changing = self._load_text(Path(row["path"]))
                except (OSError, ValueError) as exc:
                    complete = False
                    if len(warnings) < 20:
                        warnings.append(f"Could not verify {row['path']}: {exc}")
                    continue
                if body is None:
                    complete = False
                    if len(warnings) < 20:
                        warnings.append(f"File now has content status {content_status}: {row['path']}")
                    continue
                if changing:
                    complete = False
                    if len(warnings) < 20:
                        warnings.append(f"Source changed during read; unstable evidence omitted: {row['path']}")
                    continue
                if digest != row["content_hash"]:
                    stale_candidates += 1
                    complete = False
                found: list[dict] = []
                truncated = False
                for number, line in enumerate(body.splitlines(), 1):
                    if time.perf_counter() >= deadline:
                        complete = False
                        warnings.append("Search budget exhausted while matching file lines.")
                        break
                    haystack = line if case_sensitive else line.casefold()
                    if needle in haystack:
                        if len(found) >= per_file:
                            truncated = True
                            break
                        # Snippets remain bounded even for a one-line JSON ledger.
                        remaining = MAX_MATCH_TEXT_CHARS - text_characters
                        if remaining <= 0:
                            complete = False
                            truncated = True
                            break
                        position = _source_offset(line, haystack.find(needle), case_sensitive)
                        offset = max(0, position - 200)
                        snippet = line[offset:offset + min(2000, remaining)]
                        text_characters += len(snippet)
                        snippet_cut = offset > 0 or offset + len(snippet) < len(line)
                        if snippet_cut:
                            complete = False
                        found.append({"line": number, "column": position + 1, "text": snippet,
                                      "text_start_column": offset + 1, "text_truncated": snippet_cut})
                if found:
                    if len(files) >= limit:
                        complete = False
                        warnings.append("File result limit reached.")
                        break
                    files.append({"path": row["path"], "matches": found, "matches_truncated": truncated,
                                  "content_sha256": digest, "changed_since_index": digest != row["content_hash"], "changed_during_read": changing})
                    if truncated or changing:
                        complete = False
                if text_characters >= MAX_MATCH_TEXT_CHARS:
                    complete = False
                    warnings.append("Aggregate match text limit reached (32000 characters).")
                    break
                if time.perf_counter() >= deadline:
                    complete = False
                    break
        except sqlite3.OperationalError as exc:
            if "interrupt" not in str(exc).lower():
                raise
            complete = False
            warnings.append("Search budget exhausted in SQLite.")
        finally:
            self.conn.set_progress_handler(None, 0)
        if stale_candidates:
            warnings.append("Candidate content differs from index; refresh before claiming exhaustive coverage.")
        if any(file["matches_truncated"] for file in files):
            warnings.append("Per-file match limit reached.")
        if any(file["changed_during_read"] for file in files):
            warnings.append("A source file changed during the read; repeat for verification.")
        if any(match["text_truncated"] for file in files for match in file["matches"]):
            warnings.append("Some matching lines are returned as bounded excerpts.")
        coverage = self._coverage()
        if not coverage["enumeration_complete"]:
            complete = False
            warnings.append("Last index enumeration was incomplete.")
        result = {"ok": True, "files": files, "complete": complete, "strategy": "fts_literal" if indexed else "short_cached_scan",
                  "stale_candidates": stale_candidates,
                  "examined": examined, "index": coverage, "warnings": warnings,
                  "elapsed_ms": round((time.perf_counter() - start) * 1000, 3), "budget_scope": "query_after_optional_refresh"}
        return result

    @_snapshot
    def read(self, path: str, start_line: int = 1, max_lines: int = 100, max_chars: int = 16000) -> dict:
        self._ready()
        _integer(start_line, "start_line", 1, 10000000)
        _integer(max_lines, "max_lines", 1, 500)
        _integer(max_chars, "max_chars", 1, 64000)
        target = self._checked_path(path)
        body, content_status, digest, changing = self._load_text(target)
        if changing:
            raise ValueError("Source changed during reading; repeat to obtain stable evidence.")
        if body is None:
            raise ValueError(f"File cannot be read as bounded text: {content_status}.")
        lines = body.splitlines()
        selected = lines[start_line - 1:start_line - 1 + max_lines]
        joined = "\n".join(selected)
        output = joined[:max_chars]
        truncated = len(joined) > max_chars or start_line - 1 + max_lines < len(lines)
        end_line = start_line - 1 if not selected else start_line + output.count("\n")
        return {"ok": True, "path": str(target), "text": output, "start_line": start_line, "end_line": end_line,
                "total_lines": len(lines), "truncated": truncated, "complete": not truncated and not changing,
                "content_sha256": digest, "changed_during_read": changing,
                "warnings": ["Source changed during reading."] if changing else []}


    def check(self) -> dict:
        """Check SQLite, FTS internals and source-to-index row relationships.

        Uses a short exclusive-writer transaction, then rolls back the FTS
        diagnostic commands. This is not filesystem backup or authentication.
        """
        self._ready()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            sqlite_results = [row[0] for row in self.conn.execute("PRAGMA integrity_check")]
            self.conn.execute("INSERT INTO names_fts(names_fts) VALUES ('integrity-check')")
            self.conn.execute("INSERT INTO contents_fts(contents_fts) VALUES ('integrity-check')")
            missing_names = self.conn.execute("SELECT COUNT(*) FROM files f WHERE NOT EXISTS (SELECT 1 FROM names_fts n WHERE n.rowid=f.id)").fetchone()[0]
            orphan_names = self.conn.execute("SELECT COUNT(*) FROM names_fts n WHERE NOT EXISTS (SELECT 1 FROM files f WHERE f.id=n.rowid)").fetchone()[0]
            missing_text = self.conn.execute("SELECT COUNT(*) FROM files f WHERE f.content_status='indexed' AND NOT EXISTS (SELECT 1 FROM contents_fts c WHERE c.rowid=f.id)").fetchone()[0]
            orphan_text = self.conn.execute("SELECT COUNT(*) FROM contents_fts c WHERE NOT EXISTS (SELECT 1 FROM files f WHERE f.id=c.rowid AND f.content_status='indexed')").fetchone()[0]
            clean = sqlite_results == ["ok"] and not any((missing_names, orphan_names, missing_text, orphan_text))
            return {"ok": clean, "complete": clean, "version": VERSION, "sqlite": sqlite_results,
                    "fts_integrity": "ok", "missing_names": missing_names, "orphan_names": orphan_names,
                    "missing_text": missing_text, "orphan_text": orphan_text, "index": self._coverage()}
        finally:
            self.conn.rollback()
