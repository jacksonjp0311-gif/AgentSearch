import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from agentsearch import SearchEngine, SearchConfig
from agentsearch.pegasus import register, PRIVATE_DIRECTORIES


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'project';self.root.mkdir()
        self.file=self.root/'source.py';self.file.write_bytes(b'answer = 42\n')
        self.db=self.base/'index.sqlite3';self.tools={}
        with SearchEngine(self.db,SearchConfig((str(self.root),),exclude_dirs=tuple(PRIVATE_DIRECTORIES))) as e:e.index()
        register(SimpleNamespace(register_tool=lambda **kw:self.tools.update({kw['name']:kw})),
                 project_root=self.root,index_path=self.db)
    def call(self,name,args):return json.loads(self.tools['agentsearch_'+name]['handler'](args))
    def test_skill_discovery_and_all_five_invocations(self):
        skill=Path(__file__).resolve().parents[1]/'skills/agentsearch/SKILL.md'
        self.assertIn('name: agentsearch',skill.read_text())
        self.assertEqual(len(self.tools),5)
        self.assertTrue(self.call('index_status',{})['ok'])
        self.assertEqual(len(self.call('file_search',{'query':'source'})['hits']),1)
        self.assertEqual(len(self.call('content_search',{'pattern':'answer'})['files']),1)
        evidence=self.call('read_file',{'path':str(self.file)})
        self.assertTrue(self.call('verify_evidence',{'path':str(self.file),'sha256':evidence['content_sha256']})['verified'])
    def test_scope_refresh_and_memory_boundaries(self):
        private=self.root/'data';private.mkdir();p=private/'memory.txt';p.write_text('private')
        self.assertFalse(self.call('read_file',{'path':str(p)})['ok'])
        self.assertFalse(self.call('read_file',{'path':str(self.base/'outside.txt')})['ok'])
        self.assertFalse(self.call('content_search',{'pattern':'answer','fresh':True})['ok'])
        other=self.base/'other';other.mkdir()
        with SearchEngine(self.db,SearchConfig((str(other),))) as e:e.index()
        self.assertFalse(self.call('index_status',{})['ok'])
    def test_independent_client_connections(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertTrue(all(pool.map(lambda _:self.call('content_search',{'pattern':'answer'})['ok'],range(32))))


if __name__=='__main__':unittest.main()
