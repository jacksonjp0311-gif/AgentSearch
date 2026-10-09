import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentsearch import SearchConfig, SearchEngine
from agentsearch.evidence import receipt


class NativeRegressions(unittest.TestCase):
    def test_rewritten_stable_file_is_read_indexed_and_verified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'root';root.mkdir();p=root/'edited.txt'
            p.write_bytes(b'original');p.write_bytes(b'edited bytes')
            with SearchEngine(Path(d)/'index.sqlite3',SearchConfig((str(root),))) as e:
                self.assertTrue(e.index()['complete'])
                self.assertEqual(e.read(str(p))['text'],'edited bytes')
                self.assertEqual(len(e.grep('edited')['files']),1)
                self.assertEqual(receipt(p)['sha256'],hashlib.sha256(b'edited bytes').hexdigest())
                self.assertEqual(e.index()['updated'],0)

    def test_growing_evidence_never_reads_without_bound(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'grow';p.write_bytes(b'a')
            original=Path.open
            def grow(target,*args,**kwargs):
                with original(target,'ab') as f:f.write(b'b'*100)
                return original(target,*args,**kwargs)
            with patch.object(Path,'open',grow),self.assertRaisesRegex(ValueError,'size limit'):
                receipt(p,max_bytes=8)

    @unittest.skipUnless(os.name=='nt','Windows junction test')
    def test_junction_cannot_escape_roots(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=base/'root';root.mkdir();outside=base/'outside';outside.mkdir()
            (outside/'private.txt').write_text('private marker');link=root/'junction'
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            try:
                with SearchEngine(base/'index.sqlite3',SearchConfig((str(root),))) as e:
                    self.assertTrue(e.index()['complete'])
                    self.assertEqual(e.grep('private')['files'],[])
                    with self.assertRaises(ValueError):e.read(str(link/'private.txt'))
            finally:link.rmdir()

    @unittest.skipUnless(os.name=='nt','Windows long path test')
    def test_long_path_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d).resolve();root=Path('\\\\?\\'+str(base/'root'));root.mkdir()
            try:
                sub=root/('a'*90)/('b'*90)/('c'*90);sub.mkdir(parents=True)
                p=sub/'long.txt';p.write_bytes(b'long path marker')
                with SearchEngine(base/'index.sqlite3',SearchConfig((str(root),))) as e:
                    self.assertTrue(e.index()['complete'])
                    self.assertEqual(e.read(str(p))['text'],'long path marker')
            finally:
                # Remove only the exact extended-path fixture we just created;
                # ordinary cleanup cannot traverse it when long-path policy is off.
                import shutil
                self.assertEqual(str(root), '\\\\?\\'+str(base/'root'))
                shutil.rmtree(root)


if __name__=='__main__':unittest.main()
