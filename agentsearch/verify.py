"""Repeat the offline source-distribution tests and write a machine-readable receipt.

python -m agentsearch.verify --repeat 5 --output state/verification.json
No source folders are indexed here: tests create and destroy isolated fixtures.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import time
import unittest
from ._version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def source_hashes() -> dict:
    paths = [*sorted((ROOT/'agentsearch').glob('*.py')), *sorted((ROOT/'tests').glob('*.py')), *sorted((ROOT/'examples').glob('*.py')),
             ROOT/'AgentSearch.ps1', ROOT/'pyproject.toml']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def verify_manifest(root: Path = ROOT) -> dict:
    path = root/'MANIFEST.json'
    if not path.exists():
        return {'ok': False, 'error': 'Release manifest is missing.'}
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        entries = manifest['files']
        if not isinstance(entries, dict) or any(not isinstance(k, str) or not isinstance(v, dict) for k, v in entries.items()):
            raise ValueError('Manifest files must map relative paths to hash/size objects.')
        failures = []
        if manifest.get('version') != VERSION:
            failures.append('Manifest version differs from runtime version.')
        for relative, expected in entries.items():
            candidate = (root/relative).resolve()
            if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
                failures.append('Missing or invalid path: '+relative)
                continue
            raw = candidate.read_bytes()
            if len(raw) != expected['size'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                failures.append('Hash/size mismatch: '+relative)
        # Refuse unexpected executable code, while permitting generated state.
        for folder in ('agentsearch', 'tests', 'examples', 'scripts', 'skills'):
            for candidate in (root/folder).rglob('*'):
                if candidate.suffix not in ('.py','.ps1'):continue
                if candidate.relative_to(root).as_posix() not in entries:
                    failures.append('Unlisted Python source: '+candidate.relative_to(root).as_posix())
        return {'ok': not failures, 'checked_files': len(entries), 'failures': failures,
                'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'authentication': 'Local integrity check; not a cryptographic publisher signature.'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'error': str(exc)}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.verification-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT/'state'/'verification.json')
    parser.add_argument('--allow-unsealed', action='store_true', help='Developer-only: test edited sources without accepting release-manifest integrity.')
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 100:
        parser.error('--repeat must be between 1 and 100')
    if not (ROOT/'tests').is_dir():
        parser.error('Tests are absent. Use the complete source ZIP, not a minimal wheel installation.')
    start = time.perf_counter()
    integrity = verify_manifest()
    if not integrity['ok'] and not args.allow_unsealed:
        receipt = {'ok': False, 'version': VERSION, 'manifest': integrity, 'runs': [], 'message': 'Manifest check failed; no tests were run.'}
        atomic_json(args.output, receipt)
        print(json.dumps(receipt, ensure_ascii=True))
        return 1
    runs = []
    initial_hashes = source_hashes()
    for number in range(1, args.repeat+1):
        print(f'AgentSearch verification run {number}/{args.repeat}', file=sys.stderr, flush=True)
        before = time.perf_counter()
        suite = unittest.TestLoader().discover(str(ROOT/'tests'))
        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
        runs.append({'run': number, 'collected': result.testsRun,
                     'passed': result.testsRun-len(result.skipped)-len(result.errors)-len(result.failures)-len(result.expectedFailures)-len(result.unexpectedSuccesses),
                     'skipped': [{'test': test.id(), 'reason': reason} for test,reason in result.skipped],
                     'failures': [{'test': test.id(), 'traceback': trace} for test,trace in result.failures],
                     'errors': [{'test': test.id(), 'traceback': trace} for test,trace in result.errors],
                     'expected_failures': len(result.expectedFailures), 'unexpected_successes': len(result.unexpectedSuccesses),
                     'ok': result.wasSuccessful(), 'elapsed_seconds': round(time.perf_counter()-before, 3)})
        if not result.wasSuccessful():
            break
    final_hashes = source_hashes()
    unchanged = initial_hashes == final_hashes
    receipt = {'ok': len(runs)==args.repeat and all(r['ok'] for r in runs) and unchanged,
               'version': VERSION, 'measured_at_utc': datetime.now(timezone.utc).isoformat(),
               'environment': {'os': platform.system(), 'platform': platform.platform(), 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version},
               'manifest': integrity, 'unsealed_developer_run': args.allow_unsealed,
               'native_windows_run': os.name == 'nt', 'source_unchanged_during_tests': unchanged,
               'source_sha256': final_hashes, 'requested_repeats': args.repeat, 'runs': runs,
               'totals': {'collected': sum(r['collected'] for r in runs), 'passed': sum(r['passed'] for r in runs), 'skipped': sum(len(r['skipped']) for r in runs)},
               'elapsed_seconds': round(time.perf_counter()-start, 3),
               'limitations': ['Repeated tests are not a proof of zero defects.', 'Only the recorded operating system/runtime was executed.', 'No power-loss, NTFS or cloud-synced-folder reliability is implied by Linux tests.']}
    atomic_json(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=True))
    return 0 if receipt['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
