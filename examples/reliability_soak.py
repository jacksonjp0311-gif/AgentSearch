"""Seeded add/edit/rename/delete/reopen soak checked against direct file reads.

Creates only an isolated temporary corpus. No third-party packages or network.
python examples/reliability_soak.py --cycles 500 --output state/soak.json
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agentsearch import SearchConfig, SearchEngine, __version__
from agentsearch.verify import atomic_json, source_hashes


def run(cycles: int, seed: int) -> dict:
    rng = random.Random(seed)
    start = time.perf_counter()
    operations = Counter()
    checks = 0
    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)
    words = ['amber', 'Café', 'Straße', '雪人', 'alpha_beta', 'checkpoint', 'Ωmega', '~^', 'x', 'AB']
    patterns = ['amber', 'CAFÉ', 'strasse', '雪', '~^', 'x', 'AB', 'checkpoint', 'Ω', 'absent_marker_39401']
    with tempfile.TemporaryDirectory(prefix='agentsearch-soak-') as t:
        base = Path(t).resolve(); root = base/'corpus'; root.mkdir()
        db = base/'state'/'index.sqlite3'
        known = {}; serial = 0
        def write_new():
            nonlocal serial
            path = root/f'item_{serial:06d}.txt'; serial += 1
            write(path)
        def write(path):
            body = '\n'.join(' '.join(rng.sample(words, 4)) for _ in range(4))+'\n'
            encoding = rng.choice(['utf-8', 'utf-16', 'utf-32'])
            path.write_bytes(body.encode(encoding)); known[path] = body
        for _ in range(80):
            write_new()
        engine = SearchEngine(db, SearchConfig((str(root),)))
        try:
            engine.index()
            previous_generation = 1
            for cycle in range(cycles):
                action = rng.choice(['add', 'edit', 'rename', 'delete', 'noop'])
                if not known:
                    action = 'add'
                if len(known) >= 180 and action == 'add':
                    action = 'edit'
                if action == 'add':
                    write_new()
                if action == 'edit':
                    write(rng.choice(list(known)))
                if action == 'rename':
                    old = rng.choice(list(known)); new = root/f'renamed_{serial:06d}.txt'; serial += 1
                    old.rename(new); known[new] = known.pop(old)
                if action == 'delete':
                    old = rng.choice(list(known)); old.unlink(); del known[old]
                operations[action] += 1
                scan = engine.index(force=cycle%50 == 0)
                require(scan['complete'], f'Incomplete scan in cycle {cycle}')
                require(scan['generation'] == previous_generation+1, 'Nonmonotonic generation')
                previous_generation = scan['generation']
                require(engine.status()['files'] == len(known), 'Incorrect file count')
                for pattern in rng.sample(patterns, 3):
                    case_sensitive = bool(rng.getrandbits(1))
                    needle = pattern if case_sensitive else pattern.casefold()
                    expected = {str(p) for p,body in known.items() if any(needle in (line if case_sensitive else line.casefold()) for line in body.splitlines())}
                    result = engine.grep(pattern, limit=200, per_file=20, budget_ms=10000, case_sensitive=case_sensitive)
                    require(result['complete'], 'Unexpected truncated query')
                    require({f['path'] for f in result['files']} == expected, f'Content oracle mismatch: {cycle}/{pattern}')
                    for file in result['files']:
                        raw = Path(file['path']).read_bytes()
                        require(file['content_sha256'] == hashlib.sha256(raw).hexdigest(), 'Evidence hash mismatch')
                        lines = known[Path(file['path'])].splitlines()
                        expected_lines = [i for i,line in enumerate(lines,1) if needle in (line if case_sensitive else line.casefold())]
                        require([m['line'] for m in file['matches']] == expected_lines, 'Line evidence mismatch')
                    operations['content_query'] += 1
                if known:
                    target = rng.choice(list(known))
                    result = engine.search(target.name, budget_ms=10000)
                    require(result['hits'][0]['path'] == str(target), 'Exact file search mismatch')
                    repeated = engine.search(target.name, budget_ms=10000)
                    require(result['hits'] == repeated['hits'], 'Unstable repeated ranking')
                    read = engine.read(str(target))
                    require(read['text'] == known[target].rstrip('\n'), 'Bounded read mismatch')
                    operations['file_query'] += 2; operations['read'] += 1
                if cycle%20 == 0:
                    require(engine.check()['ok'], 'Integrity check failed')
                    engine.close(); engine = SearchEngine(db)
                    require(engine.status()['index']['generation'] == previous_generation, 'Generation lost on reopen')
                    operations['reopen'] += 1
            require(engine.check()['ok'], 'Final integrity check failed')
            final = engine.status()
        finally:
            engine.close()
    return {'ok': True, 'version': __version__, 'cycles': cycles, 'seed': seed, 'assertions': checks,
            'operations': dict(operations), 'source_sha256': source_hashes(),
            'measured_at_utc': datetime.now(timezone.utc).isoformat(),
            'environment': {'os': platform.system(), 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version},
            'elapsed_seconds': round(time.perf_counter()-start, 3), 'final_files': final['files'],
            'limitations': ['Seeded synthetic fixtures, not a production disk.', 'No simultaneous mutation during the direct-read oracle step. Concurrency and interrupted writes are separate tests.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=500)
    parser.add_argument('--seed', type=int, default=20261008)
    parser.add_argument('--output', type=Path, default=ROOT/'state'/'soak.json')
    args = parser.parse_args()
    if not 1 <= args.cycles <= 10000:
        parser.error('--cycles must be between 1 and 10000')
    try:
        receipt = run(args.cycles, args.seed)
    except Exception as exc:
        receipt = {'ok': False, 'version': __version__, 'seed': args.seed, 'error': str(exc), 'type': type(exc).__name__}
    atomic_json(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=True))
    return 0 if receipt['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
