"""Deterministic regression and fault-injection tests. No model/network required."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import hashlib
import io
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

from agentsearch import SearchConfig, SearchEngine, __version__
from agentsearch.adapter import AgentSearchAdapter, ToolArgumentError
from agentsearch.engine import _fuzzy_scorer
from agentsearch.protocol import serve_json_lines, SERVER_VERSION

PACKAGE = Path(__file__).resolve().parents[1]


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='agentsearch-reliability-')
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'source'
        self.root.mkdir()
        self.db = self.base / 'state' / 'index.sqlite3'
        self.engine = SearchEngine(self.db, SearchConfig((str(self.root),)))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.engine.close)

    def write(self, name, body='anchor_token\n'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        return path

    def rows(self):
        return [tuple(r) for r in self.engine.conn.execute('SELECT * FROM files ORDER BY path')]

    def test_version_consistency(self):
        metadata = tomllib.loads((PACKAGE / 'pyproject.toml').read_text())
        self.assertEqual(metadata['project']['version'], __version__)
        self.assertEqual(SERVER_VERSION, __version__)
        self.assertEqual(self.engine.status()['version'], __version__)

    def test_noop_refresh_is_idempotent_except_receipt(self):
        for n in range(30):
            self.write(f'{n:03}.txt', f'token{n}\n')
        self.engine.index()
        before = self.rows()
        for _ in range(8):
            r = self.engine.index()
            self.assertEqual((r['updated'], r['removed'], r['unchanged']), (0, 0, 30))
            self.assertTrue(r['complete'])
            self.assertEqual(before, self.rows())
        self.assertTrue(self.engine.check()['ok'])

    def test_force_refresh_rereads_unchanged_metadata(self):
        self.write('sample.txt')
        self.engine.index()
        with patch.object(self.engine, '_load_text', wraps=self.engine._load_text) as read:
            r = self.engine.index(force=True)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(r['updated'], 1)
            self.assertTrue(r['force'])
        with self.assertRaises(ValueError):
            self.engine.index(force=1)

    def test_tie_boundary_uses_path_ascending_not_insertion_order(self):
        for folder in ['dd', 'cc', 'aa', 'bb']:
            self.write(f'{folder}/checkpoint.txt')
        self.engine.index()
        for _ in range(4):
            result = self.engine.search('checkpoint', limit=2)
            self.assertEqual([Path(x['path']).parent.name for x in result['hits']], ['aa', 'bb'])
            self.assertEqual(result['matched'], 4)
            self.assertFalse(result['complete'])
            self.engine.index(force=True)

    def test_fuzzy_membership_and_scores_match_bruteforce_reference(self):
        rng = random.Random(6502)
        stems = ['checkpoint', 'routing', 'receipt', 'memory', 'algorithm', 'café', 'calibration']
        paths = []
        for n in range(110):
            stem = rng.choice(stems)
            paths.append(self.write(f'{n:03}_{stem}_{rng.choice(stems)}.txt'))
        self.engine.index()
        queries = ['checkpiont', 'mmory', 'algoritm', 'routng', 'reciept', 'cafè', 'calibraton',
                   'routng algoritm', 'mmory reciept', 'checkpiont calibraton', 'notarealword999']
        for query in queries:
            with self.subTest(query=query):
                terms = query.casefold().split()
                literal = []
                fuzzy = []
                for path in paths:
                    name = path.name.casefold()
                    full = str(path).casefold()
                    if all(term in full for term in terms):
                        score = 1000 if name == query else 900 if name.startswith(query) else 800 if query in name else 700
                        literal.append((score - len(name)/10000, str(path)))
                    stem = Path(name).stem
                    pieces = [name, stem, *stem.replace('-', '_').split('_')]
                    scores = [1.0 if term in full else max(SequenceMatcher(None, term, x, autojunk=False).ratio() for x in pieces) for term in terms]
                    if min(scores) >= 0.65:
                        fuzzy.append((500*sum(scores)/len(scores), str(path)))
                expected = sorted(literal or fuzzy, key=lambda x: (-x[0], x[1]))[:20]
                result = self.engine.search(query, limit=20, budget_ms=10000)
                self.assertEqual([(x['score'], x['path']) for x in result['hits']], [(round(s, 4), p) for s,p in expected])

    def test_ratio_bounds_preserve_every_accepted_score(self):
        ratio, _ = _fuzzy_scorer()
        rng = random.Random(937)
        for _ in range(4000):
            a = ''.join(rng.choices('abcdé雪_', k=rng.randrange(1, 30)))
            b = ''.join(rng.choices('abcdé雪_', k=rng.randrange(1, 30)))
            ref = SequenceMatcher(None, a, b, autojunk=False).ratio()
            fast = ratio(a, b)
            self.assertEqual(ref >= 0.65, fast >= 0.65)
            if ref >= 0.65:
                self.assertEqual(ref, fast)

    def test_short_query_rereads_matching_candidates_only(self):
        for n in range(120):
            self.write(f'{n:03}.txt', 'ordinary text\n' + ('~^\n' if n == 9 else ''))
        self.engine.index()
        with patch.object(self.engine, '_load_text', wraps=self.engine._load_text) as read:
            result = self.engine.grep('~^')
            self.assertEqual(read.call_count, 1)
            self.assertEqual(len(result['files']), 1)
            self.assertEqual(result['strategy'], 'short_cached_scan')
            self.assertTrue(result['complete'])

    def test_short_query_freshness_is_explicit_and_refresh_finds_edit(self):
        p = self.write('sample.txt', 'old\n')
        self.engine.index()
        p.write_text('old ~^\n')
        before = self.engine.grep('~^')
        self.assertEqual(before['files'], [])
        self.assertFalse(before['index']['atomic_filesystem_snapshot'])
        after = self.engine.grep('~^', fresh=True)
        self.assertEqual(len(after['files']), 1)
        self.assertGreater(after['index']['generation'], before['index']['generation'])

    def test_stale_candidate_does_not_claim_complete_even_without_match(self):
        p = self.write('sample.txt', 'needle\n')
        self.engine.index()
        p.write_text('changed\n')
        r = self.engine.grep('needle')
        self.assertEqual(r['files'], [])
        self.assertEqual(r['stale_candidates'], 1)
        self.assertFalse(r['complete'])

    def test_utf32_bom_decoding_and_embedded_nul_policy(self):
        (self.root/'utf32.txt').write_bytes('snowman_雪\n'.encode('utf-32'))
        (self.root/'nul.txt').write_bytes('bad\x00needle\n'.encode('utf-16'))
        r = self.engine.index()
        self.assertEqual(r['content_counts'].get('binary'), 1)
        result = self.engine.grep('snowman_雪')
        self.assertEqual(len(result['files']), 1)
        self.assertEqual(self.engine.grep('needle')['files'], [])

    def test_unstable_reads_are_not_returned_as_evidence(self):
        p = self.write('sample.txt', 'needle\n')
        self.engine.index()
        with patch.object(self.engine, '_load_text', return_value=('needle\n', 'indexed', 'a'*64, True)):
            r = self.engine.grep('needle')
            self.assertEqual(r['files'], [])
            self.assertFalse(r['complete'])
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.engine.read(str(p))

    def test_atomic_replacement_is_detected_after_descriptor_read(self):
        p = self.write('sample.txt', 'needle\n')
        replacement = self.write('new.txt', 'replacement\n')
        expected_body = p.read_bytes().decode('utf-8')
        original = self.engine._checked_path
        calls = 0
        def swap(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                os.replace(replacement, p)
            return original(path)
        # Swap after the descriptor closes: Windows denies replacement while
        # the CRT handle is open, but the post-close race still needs detection.
        with patch.object(self.engine, '_checked_path', side_effect=swap):
            body, _, _, changed = self.engine._load_text(p)
        self.assertEqual(body, expected_body)
        self.assertTrue(changed)

    def test_bad_surrogate_and_duplicate_json_recover_next_request(self):
        self.engine.index()
        source = io.StringIO('{"id":1,"op":"status","op":"search"}\n' +
                             '{"id":2,"op":"search","query":"\\ud800"}\n' +
                             '{"id":3,"op":"status"}\n')
        out = io.StringIO()
        serve_json_lines(self.engine, source, out)
        values = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(len(values), 3)
        self.assertFalse(values[0]['ok'])
        self.assertFalse(values[1]['ok'])
        self.assertTrue(values[2]['ok'])

    @unittest.skipIf(os.name == 'nt', 'POSIX arbitrary-byte filenames only')
    def test_invalid_utf8_filename_is_visible_skip_not_total_crash(self):
        filename = os.fsencode(self.root) + b'/invalid_\xff.txt'
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd, b'content'); os.close(fd)
        self.write('normal.txt')
        r = self.engine.index()
        self.assertFalse(r['complete'])
        self.assertEqual(r['error_count'], 1)
        self.assertEqual(self.engine.status()['files'], 1)

    def test_interrupted_index_rolls_back_all_changes_and_receipt(self):
        for n in range(12):
            self.write(f'{n}.txt', 'initial\n')
        self.engine.index()
        original_rows = self.rows()
        generation = self.engine.status()['index']['generation']
        for n in range(12):
            self.write(f'{n}.txt', 'updated\n')
        original = self.engine._load_text
        calls = 0
        def interrupt(path):
            nonlocal calls
            calls += 1
            if calls == 6:
                raise KeyboardInterrupt('fault injection')
            return original(path)
        with patch.object(self.engine, '_load_text', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.index(force=True)
        self.assertEqual(self.rows(), original_rows)
        self.assertEqual(self.engine.status()['index']['generation'], generation)
        self.assertTrue(self.engine.check()['ok'])
        self.assertEqual(self.engine.index(force=True)['updated'], 12)

    def test_killed_index_writer_recovers_last_committed_state(self):
        for n in range(12):
            self.write(f'{n}.txt', 'initial\n')
        self.engine.index()
        original_rows = self.rows()
        generation = self.engine.status()['index']['generation']
        for n in range(12):
            self.write(f'{n}.txt', 'updated\n')
        code = '''import sys,time
from agentsearch import SearchEngine
e=SearchEngine(sys.argv[1]); original=e._load_text; calls=0
def pause(path):
 global calls
 calls+=1
 if calls==6:
  print('mid-transaction',flush=True);time.sleep(60)
 return original(path)
e._load_text=pause
e.index(force=True)
'''
        proc = subprocess.Popen([sys.executable, '-c', code, str(self.db)], cwd=PACKAGE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                ready = pool.submit(proc.stdout.readline)
                try:
                    self.assertEqual(ready.result(timeout=10).strip(), 'mid-transaction')
                finally:
                    proc.kill()
                    proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=10)
            proc.stdout.close(); proc.stderr.close()
        self.assertEqual(self.rows(), original_rows)
        self.assertEqual(self.engine.status()['index']['generation'], generation)
        self.assertTrue(self.engine.check()['ok'])
        self.assertEqual(self.engine.index(force=True)['updated'], 12)

    def test_new_reader_opens_while_writer_is_uncommitted(self):
        self.write('anchor.txt')
        self.engine.index()
        self.engine.conn.execute('BEGIN IMMEDIATE')
        self.engine._set_meta('generation', '9000')
        def open_reader():
            with SearchEngine(self.db) as reader:
                return reader.status()['index']['generation']
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(open_reader)
                try:
                    self.assertEqual(future.result(timeout=2), 1)
                finally:
                    self.engine.conn.rollback()
        finally:
            self.engine.conn.rollback()

    def test_query_receipt_uses_same_snapshot_as_candidates(self):
        self.write('anchor.txt')
        self.engine.index()
        old = self.engine.status()['index']['generation']
        with SearchEngine(self.db) as writer:
            original = self.engine._coverage
            def during_coverage():
                writer.index()
                return original()
            with patch.object(self.engine, '_coverage', side_effect=during_coverage):
                result = self.engine.search('anchor')
            self.assertEqual(result['index']['generation'], old)
            self.assertEqual(writer.status()['index']['generation'], old+1)

    def test_concurrent_readers_and_writer_finish_without_partial_commits(self):
        self.write('anchor.txt')
        self.engine.index()
        def reader(worker):
            with SearchEngine(self.db) as engine:
                seen = []
                for _ in range(30):
                    r = engine.grep('anchor_token')
                    self.assertEqual(len(r['files']), 1)
                    self.assertTrue(r['ok'])
                    seen.append(r['index']['generation'])
                self.assertEqual(seen, sorted(seen))
                return len(seen)
        def writer():
            with SearchEngine(self.db) as engine:
                for n in range(15):
                    (self.root/'changing.txt').write_text(f'mutation {n}\n')
                    self.assertTrue(engine.index()['ok'])
            return 15
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(reader, n) for n in range(4)] + [pool.submit(writer)]
            self.assertEqual(sum(f.result(timeout=30) for f in futures), 135)
        self.assertTrue(self.engine.check()['ok'])

    def test_budget_interruption_does_not_poison_next_request(self):
        for n in range(200):
            self.write(f'doc_{n}.txt', 'anchor_token\n')
        self.engine.index()
        real = self.engine._begin_query
        def expired(ms):
            real(ms)
            return time.perf_counter()-1
        with patch.object(self.engine, '_begin_query', side_effect=expired):
            r = self.engine.search('doc')
        self.assertFalse(r['complete'])
        self.assertFalse(self.engine.conn.in_transaction)
        self.assertTrue(self.engine.search('doc_19.txt')['ok'])

    def test_invalid_fresh_query_does_not_write_generation(self):
        self.write('anchor.txt'); self.engine.index()
        previous = self.engine.status()['index']['generation']
        with self.assertRaises(ValueError):
            self.engine.grep('needle', fresh=True, scope=str(self.base))
        self.assertEqual(self.engine.status()['index']['generation'], previous)

    def test_integrity_check_detects_orphan_fts_row(self):
        self.write('anchor.txt'); self.engine.index()
        self.engine.conn.execute('INSERT INTO names_fts(rowid,name,path) VALUES (?,?,?)', (999, 'orphan', 'orphan'))
        self.engine.conn.commit()
        r = self.engine.check()
        self.assertFalse(r['ok'])
        self.assertEqual(r['orphan_names'], 1)

    def test_integrity_check_detects_missing_content_row(self):
        self.write('anchor.txt'); self.engine.index()
        self.engine.conn.execute('DELETE FROM contents_fts'); self.engine.conn.commit()
        r = self.engine.check()
        self.assertFalse(r['ok'])
        self.assertEqual(r['missing_text'], 1)

    def test_unrelated_sqlite_database_is_not_modified(self):
        other = self.base/'unrelated.sqlite'
        with sqlite3.connect(other) as db:
            db.execute('CREATE TABLE business_data(value TEXT)')
            db.execute("INSERT INTO business_data VALUES ('keep')")
        db.close()  # A SQLite context commits; it does not close the connection.
        before = hashlib.sha256(other.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Not an AgentSearch'):
            SearchEngine(other, SearchConfig((str(self.root),)))
        self.assertEqual(hashlib.sha256(other.read_bytes()).hexdigest(), before)

    def test_search_and_index_leave_all_source_bytes_unchanged(self):
        paths = [self.write(f'{n}.txt', f'anchor_token {n}\n') for n in range(20)]
        before = {p: p.read_bytes() for p in paths}
        self.engine.index()
        for _ in range(5):
            self.engine.search('1'); self.engine.grep('anchor_token'); self.engine.read(str(paths[0])); self.engine.index()
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_scope_cannot_match_neighbor_prefix_directory(self):
        inside = self.write('src/anchor.txt')
        self.write('src2/anchor.txt')
        self.engine.index()
        r = self.engine.search('anchor', scope=str(self.root/'src'))
        self.assertEqual([x['path'] for x in r['hits']], [str(inside)])

    def test_semicolon_quote_and_unicode_filenames_are_data(self):
        p = self.write("semi; quote' café 雪.txt", 'literal [x] = "value"\n')
        self.engine.index()
        r = self.engine.grep('[x] = "value"')
        self.assertEqual(r['files'][0]['path'], str(p))
        self.assertTrue(self.engine.check()['ok'])

    def test_failed_write_lock_returns_error_and_next_call_works(self):
        self.write('anchor.txt'); self.engine.index()
        with SearchEngine(self.db) as writer:
            writer.conn.execute('BEGIN IMMEDIATE')
            self.engine.conn.execute('PRAGMA busy_timeout=10')
            with self.assertRaises(sqlite3.OperationalError):
                self.engine.index()
            writer.conn.rollback()
        self.assertTrue(self.engine.index()['ok'])
        self.assertTrue(self.engine.check()['ok'])

    def test_queries_do_not_dirty_index_or_open_write_transaction(self):
        self.write('anchor.txt'); self.engine.index()
        self.engine.conn.execute('PRAGMA query_only=ON')
        try:
            for _ in range(10):
                self.assertTrue(self.engine.search('anchor')['ok'])
                self.assertTrue(self.engine.grep('anchor_token')['ok'])
                self.assertTrue(self.engine.status()['ok'])
                self.assertFalse(self.engine.conn.in_transaction)
        finally:
            self.engine.conn.execute('PRAGMA query_only=OFF')


if __name__ == '__main__':
    unittest.main()

class LongSessionAndStartupTests(unittest.TestCase):
    def test_concurrent_first_open_is_safe(self):
        from threading import Barrier
        with tempfile.TemporaryDirectory(prefix='agentsearch-startup-') as t:
            root = Path(t)/'source'; root.mkdir()
            config = SearchConfig((str(root),))
            for iteration in range(8):
                db = Path(t)/f'new-{iteration}.sqlite'
                barrier = Barrier(4)
                def open_one():
                    barrier.wait(timeout=5)
                    with SearchEngine(db, config) as engine:
                        return engine.status()['files']
                with ThreadPoolExecutor(max_workers=4) as pool:
                    jobs = [pool.submit(open_one) for _ in range(4)]
                    self.assertEqual([job.result(timeout=15) for job in jobs], [0]*4)

    def test_long_lived_subprocess_jsonl_handles_250_requests(self):
        with tempfile.TemporaryDirectory(prefix='agentsearch-session-') as t:
            root = Path(t)/'source'; root.mkdir(); (root/'anchor.txt').write_text('anchor_token\n')
            db = Path(t)/'index.sqlite'
            with SearchEngine(db, SearchConfig((str(root),))) as engine:
                engine.index()
            messages = []
            for n in range(250):
                op = ({'op':'status'}, {'op':'search','query':'anchor'}, {'op':'grep','pattern':'anchor_token'}, {'op':'delete'}, {'op':'status'})[n%5]
                messages.append(json.dumps({'id':n, **op}))
            process = subprocess.run([sys.executable, '-m', 'agentsearch', '--db', str(db), 'stdio'], input='\n'.join(messages)+'\n', text=True, capture_output=True, cwd=PACKAGE, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            results = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual(len(results), 250)
            for n, result in enumerate(results):
                self.assertEqual(result['id'], n)
                self.assertEqual(result['ok'], n%5 != 3)

    def test_seeded_malformed_json_never_poisons_session(self):
        rng = random.Random(741)
        with tempfile.TemporaryDirectory(prefix='agentsearch-fuzz-') as t:
            root = Path(t)/'source'; root.mkdir()
            with SearchEngine(Path(t)/'index.sqlite', SearchConfig((str(root),))) as engine:
                engine.index()
                alphabet = '{}[]\\"123xyz: ,'
                inputs = [''.join(rng.choices(alphabet,k=rng.randrange(1,70))) for _ in range(1500)]
                source = io.StringIO('\n'.join(inputs) + '\n{"id":9999,"op":"status"}\n')
                out = io.StringIO()
                serve_json_lines(engine, source, out)
                values = [json.loads(x) for x in out.getvalue().splitlines()]
                self.assertEqual(len(values), 1501)
                self.assertTrue(values[-1]['ok'])
                self.assertTrue(all(v.get('error', {}).get('code') != 'internal_error' for v in values))
