import tempfile
import unittest
from pathlib import Path
from agentsearch.adapter import AgentSearchAdapter
from agentsearch.config import SearchConfig
from agentsearch.engine import SearchEngine
from agentsearch.evidence import receipt

class EvidenceToolTests(unittest.TestCase):
    def test_valid_changed_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            allowed=base/"allowed"
            allowed.mkdir()
            file=allowed/"hello.txt"
            file.write_text("alpha")
            outside=base/"outside.txt"
            outside.write_text("secret")
            with SearchEngine(base/"index.sqlite3",config=SearchConfig(roots=(str(allowed),))) as engine:
                engine.index()
                adapter=AgentSearchAdapter(engine)
                proof=receipt(file)
                self.assertTrue(adapter.dispatch("verify_evidence",{"path":str(file),"sha256":proof["sha256"]})["verified"])
                from agentsearch.protocol import handle_json_request
                result=handle_json_request(adapter,{'id':7,'op':'verify','path':str(file),'sha256':proof['sha256']})
                self.assertTrue(result['verified']);self.assertEqual(result['id'],7)
                file.write_text("bravo")
                self.assertFalse(adapter.dispatch("verify_evidence",{"path":str(file),"sha256":proof["sha256"]})["verified"])
                denied=adapter.dispatch("verify_evidence",{"path":str(outside),"sha256":proof["sha256"]})
                self.assertFalse(denied["ok"])
                self.assertFalse(adapter.dispatch("verify_evidence",{"path":str(file),"sha256":"x"*64})["ok"])
