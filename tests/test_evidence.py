import tempfile
import unittest
from pathlib import Path
from agentsearch.evidence import receipt, verify_receipt

class EvidenceTests(unittest.TestCase):
    def test_repeat_and_modify(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'source.txt'
            f.write_text('alpha')
            proof = receipt(f)
            self.assertEqual(proof, receipt(f))
            self.assertTrue(verify_receipt(proof))
            f.write_text('bravo')
            self.assertFalse(verify_receipt(proof))

    def test_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'source.txt'
            f.write_text('alpha')
            proof = receipt(f)
            f.unlink()
            self.assertFalse(verify_receipt(proof))

    def test_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'source.txt'
            f.write_text('alpha')
            with self.assertRaises(ValueError):
                receipt(f, max_bytes=2)

    def test_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'source.txt'
            f.write_text('alpha')
            link = Path(d) / 'link.txt'
            try:
                link.symlink_to(f)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError):
                receipt(link)
