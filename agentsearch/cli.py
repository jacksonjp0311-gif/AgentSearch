"""Command-line entrypoint; results on stdout are JSON, diagnostics use stderr."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from .adapter import AgentSearchAdapter, ToolArgumentError, error_result
from .protocol import serve_json_lines, serve_mcp, write_json

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "search.json"
DEFAULT_DB = PACKAGE_ROOT / "state" / "index.sqlite3"


class ArgumentError(ValueError):
    """A CLI syntax error that can be returned as JSON."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise ArgumentError(message)

    def print_help(self, file=None):
        super().print_help(file=sys.stderr if file is None else file)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS,
                        help="Configuration JSON path (default: package/config/search.json).")
    common.add_argument("--db", type=Path, default=argparse.SUPPRESS,
                        help="SQLite index path (default: package/state/index.sqlite3).")
    parser = Parser(prog="agentsearch",
                    description="Local, bounded file and literal-content search for humans and agents.")
    # Root and subparser actions must be separate objects: argparse parent
    # actions share defaults, which would overwrite flags supplied before a
    # subcommand when its suppressed defaults are changed on the root parser.
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Configuration JSON path (default: package/config/search.json).")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="SQLite index path (default: package/state/index.sqlite3).")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    config = sub.add_parser("config", parents=[common], help="Write a root-scoped configuration.")
    config.add_argument("--root", action="append", required=True,
                        help="Directory to index; repeat for additional roots.")
    config.add_argument("--max-file-bytes", type=int, default=2 * 1024 * 1024)
    config.add_argument("--exclude", action="append", default=[],
                        help="Directory basename to exclude in addition to defaults; repeatable.")
    indexing = sub.add_parser("index", parents=[common], help="Refresh the persistent index.")
    indexing.add_argument("--force", action="store_true", help="Re-read all files, even when metadata is unchanged.")
    sub.add_parser("check", parents=[common], help="Administrator: verify SQLite and index integrity.")
    for command, argument in (("search", "query"), ("grep", "pattern")):
        search = sub.add_parser(command, parents=[common])
        search.add_argument(argument, help="Plain search text; no embedded filter syntax.")
        search.add_argument("--limit", type=int, default=20)
        search.add_argument("--scope")
        search.add_argument("--ext")
        search.add_argument("--budget-ms", type=int, default=1000)
        if command == "grep":
            search.add_argument("--per-file", type=int, default=3)
            search.add_argument("--case-sensitive", action="store_true")
            search.add_argument("--fresh", action="store_true",
                                help="Refresh index before searching (refresh is outside search budget).")
    read = sub.add_parser("read", parents=[common], help="Read a bounded excerpt inside roots.")
    read.add_argument("path")
    read.add_argument("--start-line", type=int, default=1)
    read.add_argument("--max-lines", type=int, default=100)
    read.add_argument("--max-chars", type=int, default=16000)
    sub.add_parser("status", parents=[common], help="Inspect index coverage and freshness.")
    sub.add_parser("stdio", parents=[common], help="Serve custom read-only JSON-lines requests.")
    sub.add_parser("mcp", parents=[common], help="Serve the minimal MCP stdio tools interface.")
    watch = sub.add_parser("watch", parents=[common], help="Refresh periodically in the foreground.")
    watch.add_argument("--interval", type=float, default=5.0,
                       help="Seconds to wait between completed refreshes (default: 5).")
    return parser


def _configure(args: argparse.Namespace) -> dict:
    from .config import SearchConfig

    # Let SearchConfig own canonical path normalization and the root policy.
    initial = SearchConfig(roots=tuple(args.root), max_file_bytes=args.max_file_bytes)
    exclusions = tuple(dict.fromkeys((*initial.exclude_dirs, *args.exclude)))
    config = SearchConfig(
        roots=initial.roots, max_file_bytes=initial.max_file_bytes, exclude_dirs=exclusions,
    )
    destination = args.config.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=".search-", suffix=".tmp",
            dir=destination.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(config.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {"ok": True, "config_path": str(destination), "config": config.to_dict()}


def _run(args: argparse.Namespace) -> int:
    from .config import SearchConfig
    from .engine import SearchEngine

    if args.command == "config":
        write_json(sys.stdout, _configure(args))
        return 0
    config_path = args.config.expanduser().resolve()
    config = SearchConfig.from_file(config_path) if config_path.exists() else None
    if args.command in {"index", "watch"} and config is None:
        raise ValueError("No configuration file. Run config --root DIRECTORY first.")
    if args.command == "watch" and not 0.1 <= args.interval <= 86400:
        raise ValueError("--interval must be between 0.1 and 86400 seconds.")
    with SearchEngine(args.db.expanduser().resolve(), config=config) as engine:
        if args.command == "stdio":
            return serve_json_lines(engine)
        if args.command == "mcp":
            return serve_mcp(engine)
        if args.command == "watch":
            print("Refreshing index in foreground. Press Ctrl+C to stop.", file=sys.stderr, flush=True)
            try:
                while True:
                    write_json(sys.stdout, engine.index())
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print("Index watch stopped.", file=sys.stderr, flush=True)
                return 0
        if args.command == "index":
            result = engine.index(force=args.force)
        if args.command == "check":
            result = engine.check()
        if args.command in {"search", "grep", "read", "status"}:
            tool_name = {
                "search": "file_search", "grep": "content_search",
                "read": "read_file", "status": "index_status",
            }[args.command]
            arguments = {
                key: value for key, value in vars(args).items()
                if key not in {"command", "config", "db"} and value is not None
            }
            result = AgentSearchAdapter(engine).dispatch(tool_name, arguments)
        write_json(sys.stdout, result)
        return 0 if result.get("ok", False) else 1


def main(argv: list[str] | None = None) -> int:
    args = None
    try:
        args = build_parser().parse_args(argv)
        # MCP/JSONL are UTF-8 even when Windows uses a legacy console encoding.
        if args.command in {"mcp", "stdio"}:
            for stream in (sys.stdin, sys.stdout, sys.stderr):
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(encoding="utf-8", errors="strict")
        return _run(args)
    except BrokenPipeError:
        return 0
    except (ArgumentError, ToolArgumentError, ValueError, OSError, sqlite3.Error) as exc:
        if args is not None and args.command == "mcp":
            # Startup failures cannot masquerade as JSON-RPC response messages.
            print(f"AgentSearch startup failed: {exc}", file=sys.stderr, flush=True)
            return 2
        write_json(sys.stdout, error_result(type(exc).__name__, str(exc)))
        return 2
    except KeyboardInterrupt:
        print("AgentSearch interrupted.", file=sys.stderr, flush=True)
        return 130
    except Exception as exc:
        print(f"AgentSearch internal failure: {type(exc).__name__}", file=sys.stderr, flush=True)
        if args is None or args.command != "mcp":
            write_json(sys.stdout, error_result("internal_error", "Internal search failure."))
        return 3
