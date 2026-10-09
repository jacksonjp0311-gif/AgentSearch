"""Release checks must detect damage instead of reporting a clean test badge."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from agentsearch import __version__
from agentsearch.adapter import AgentSearchAdapter
from agentsearch.verify import verify_manifest, atomic_json

class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'agentsearch').mkdir()
        self.file = self.root/'agentsearch'/'sample.py'
        self.file.write_text('value = 1\n')
        raw = self.file.read_bytes()
        self.manifest = {'version': __version__, 'files': {'agentsearch/sample.py': {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}}
        self.save()
    def save(self):
        (self.root/'MANIFEST.json').write_text(json.dumps(self.manifest))
    def test_valid_manifest(self):
        self.assertTrue(verify_manifest(self.root)['ok'])
    def test_changed_file_is_detected(self):
        self.file.write_text('value = 2\n')
        self.assertFalse(verify_manifest(self.root)['ok'])
    def test_missing_file_is_detected(self):
        self.file.unlink()
        self.assertFalse(verify_manifest(self.root)['ok'])
    def test_extra_python_source_is_detected(self):
        (self.root/'agentsearch'/'unexpected.py').write_text('pass\n')
        self.assertFalse(verify_manifest(self.root)['ok'])
    def test_invalid_manifest_is_an_explicit_failure(self):
        self.manifest['files'] = []; self.save()
        self.assertFalse(verify_manifest(self.root)['ok'])
    def test_atomic_receipt_replacement(self):
        path = self.root/'state'/'receipt.json'
        atomic_json(path, {'ok': False}); atomic_json(path, {'ok': True})
        self.assertEqual(json.loads(path.read_text()), {'ok': True})
        self.assertEqual(list(path.parent.glob('*.tmp')), [])
    def test_mcp_annotation_admits_optional_index_refresh(self):
        definitions = {t['name']: t for t in AgentSearchAdapter.tools()}
        self.assertFalse(definitions['content_search']['annotations']['readOnlyHint'])
        self.assertTrue(definitions['file_search']['annotations']['readOnlyHint'])
