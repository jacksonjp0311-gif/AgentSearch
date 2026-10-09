"""Measure an isolated synthetic corpus; make no cross-tool speed claims.

Example:
    python examples/benchmark.py --files 2000 --repetitions 20 --output benchmark.json

The temporary corpus and index are removed on exit. Only --output, if supplied,
persists a JSON receipt. The corpus seed is reproducible; timings are not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentsearch import SearchConfig, SearchEngine  # noqa: E402


def latency_summary(samples_ms: list[float]) -> dict:
    ordered = sorted(samples_ms)
    return {
        "samples": len(ordered),
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 4),
        "min_ms": round(ordered[0], 4),
        "max_ms": round(ordered[-1], 4),
        "raw_samples_ms": [round(value, 4) for value in samples_ms],
    }


def build_corpus(root: Path, count: int, seed: int) -> tuple[list[Path], list[str], dict]:
    rng = random.Random(seed)
    files: list[Path] = []
    needles: list[str] = []
    digest = hashlib.sha256()
    total_bytes = 0
    words = ["checkpoint", "receipt", "context", "memory", "observed", "verified", "route", "evidence"]
    for number in range(count):
        relative = Path(f"batch_{number // 100:03d}") / f"receipt_{number:05d}_checkpoint.txt"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        nonce = f"{rng.getrandbits(64):016x}"
        needle = f"receipt::{nonce}[{number}]=accepted"
        body = (
            f"# Synthetic benchmark record {number}\n"
            f"record_id = {number}\n"
            + " ".join(rng.choice(words) for _ in range(80))
            + f"\n{needle}\n"
        )
        if number == 3:
            body += "Short literal sentinel: ~^\n"
        if number == 7:
            body += "Unicode literal sentinel: café_雪_unique\n"
        raw = body.encode("utf-8")
        path.write_bytes(raw)
        digest.update(relative.as_posix().encode("utf-8") + b"\0" + raw + b"\0")
        total_bytes += len(raw)
        files.append(path)
        needles.append(needle)
    return files, needles, {
        "seed": seed,
        "files": count,
        "content_bytes": total_bytes,
        "manifest_sha256": digest.hexdigest(),
        "description": "UTF-8 text files; deterministic synthetic receipts, unique literal markers, one short and one Unicode sentinel",
        "directories": math.ceil(count / 100),
    }


def run_benchmark(file_count: int, repetitions: int, seed: int, budget_ms: int = 1000) -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="agentsearch-benchmark-") as temporary:
        base = Path(temporary).resolve()
        corpus_root = base / "corpus"
        corpus_root.mkdir()
        paths, needles, corpus = build_corpus(corpus_root, file_count, seed)
        config = SearchConfig(roots=(str(corpus_root),))
        engine_start = time.perf_counter()
        with SearchEngine(base / "index.sqlite3", config=config) as engine:
            engine_open_ms = (time.perf_counter() - engine_start) * 1000
            cold_start = time.perf_counter()
            index_result = engine.index()
            cold_index_ms = (time.perf_counter() - cold_start) * 1000
            target = file_count // 2
            cases = [
                ("filename_exact", paths[target].name, paths[target], False),
                ("filename_transposition", paths[target].name.replace("checkpoint", "checkpiont"), paths[target], False),
                ("content_literal_punctuation", needles[target], paths[target], True),
                ("content_short_literal", "~^", paths[3], True),
                ("content_unicode_literal", "café_雪_unique", paths[7], True),
            ]
            measurements = []
            for label, query, expected_path, is_content in cases:
                call: Callable[[], dict]
                if is_content:
                    call = lambda query=query: engine.grep(query, limit=20, budget_ms=budget_ms)
                else:
                    call = lambda query=query: engine.search(query, limit=20, budget_ms=budget_ms)
                call()  # Unmeasured warm-up for this query class.
                samples = []
                passed = 0
                complete_responses = 0
                for _ in range(repetitions):
                    before = time.perf_counter()
                    result = call()
                    samples.append((time.perf_counter() - before) * 1000)
                    entries = result["files"] if is_content else result["hits"]
                    returned = {Path(entry["path"]) for entry in entries}
                    correct = expected_path in returned
                    if is_content:
                        correct = correct and returned == {expected_path}
                        matching = [entry for entry in entries if Path(entry["path"]) == expected_path]
                        correct = correct and any(
                            query.casefold() in match["text"].casefold()
                            for entry in matching for match in entry["matches"]
                        )
                    passed += int(correct)
                    complete_responses += int(result.get("complete") is True)
                measurements.append({
                    "class": label,
                    "query": query,
                    "expected_relative_path": expected_path.relative_to(corpus_root).as_posix(),
                    "correctness": {"passed": passed, "checked": repetitions},
                    "complete_responses": complete_responses,
                    **latency_summary(samples),
                })
            # Check fresh mode separately; reconciliation cost is deliberately
            # included and is not mixed with warm-index query latency.
            fresh_path = paths[0]
            fresh_marker = "fresh_benchmark_patch_only"
            with fresh_path.open("a", encoding="utf-8") as stream:
                stream.write(f"\n{fresh_marker}\n")
            fresh_start = time.perf_counter()
            fresh_result = engine.grep(fresh_marker, fresh=True, limit=20)
            fresh_ms = (time.perf_counter() - fresh_start) * 1000
            fresh_passed = any(Path(entry["path"]) == fresh_path for entry in fresh_result["files"])
            status_result = engine.status()
            passed = sum(item["correctness"]["passed"] for item in measurements) + int(fresh_passed)
            checked = len(cases) * repetitions + 1
            receipt = {
                "schema_version": "1.0",
                "measured_at_utc": datetime.now(timezone.utc).isoformat(),
                "benchmark_kind": "synthetic_single_implementation",
                "engine_source_sha256": hashlib.sha256((PROJECT_ROOT / "agentsearch" / "engine.py").read_bytes()).hexdigest(),
                "config_source_sha256": hashlib.sha256((PROJECT_ROOT / "agentsearch" / "config.py").read_bytes()).hexdigest(),
                "benchmark_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "environment": {
                    "platform": platform.platform(),
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "sqlite": sqlite3.sqlite_version,
                    "logical_cpu_count": os.cpu_count(),
                    "storage_medium": "not measured",
                },
                "corpus": corpus,
                "setup": {
                    "engine_open_ms": round(engine_open_ms, 4),
                    "cold_index_ms": round(cold_index_ms, 4),
                    "cold_definition": "First index build with an empty database; OS filesystem caches were not flushed",
                    "index_result": index_result,
                },
                "query_policy": {
                    "repetitions_per_class": repetitions,
                    "unmeasured_warmups_per_class": 1,
                    "limit": 20,
                    "budget_ms": budget_ms,
                    "p95_method": "nearest rank",
                },
                "warm_queries": measurements,
                "fresh_after_write": {
                    "elapsed_ms_including_reconciliation": round(fresh_ms, 4),
                    "correct": fresh_passed,
                    "expected_relative_path": fresh_path.relative_to(corpus_root).as_posix(),
                },
                "correctness": {"passed": passed, "checked": checked, "all_passed": passed == checked},
                "final_status": status_result,
                "limitations": [
                    "Synthetic text-only corpus does not represent a whole disk or a large production repository.",
                    "Warm repeated queries benefit from process and operating-system caches.",
                    "A complete response does not by itself prove complete filesystem coverage.",
                    "No FSearch, ripgrep, Everything, or other implementation was benchmarked here.",
                    "Native platform validation is limited to the environment recorded in this receipt.",
                ],
            }
        receipt["total_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 4)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=2000, help="Synthetic files to create (16–100000; default: 2000)")
    parser.add_argument("--repetitions", type=int, default=20, help="Measured samples per query class (1–1000; default: 20)")
    parser.add_argument("--budget-ms", type=int, default=1000, help="Cooperative per-query budget, 1–30000 ms")
    parser.add_argument("--seed", type=int, default=20261008, help="Deterministic corpus seed")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON receipt; otherwise stdout only")
    args = parser.parse_args()
    if not 16 <= args.files <= 100_000:
        parser.error("--files must be between 16 and 100000")
    if not 1 <= args.repetitions <= 1000:
        parser.error("--repetitions must be between 1 and 1000")
    if not 1 <= args.budget_ms <= 30000:
        parser.error("--budget-ms must be between 1 and 30000")
    receipt = run_benchmark(args.files, args.repetitions, args.seed, args.budget_ms)
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        destination = args.output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if receipt["correctness"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
