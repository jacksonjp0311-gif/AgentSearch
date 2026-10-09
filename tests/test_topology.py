import json,unittest,hashlib,ast
from pathlib import Path
from agentsearch.adapter import TOOL_DEFINITIONS
class TopologyTests(unittest.TestCase):
    def test_graph_references_and_contract(self):
        root=Path(__file__).resolve().parents[1]
        obj=json.loads((root/'topology/agent-topology.json').read_text())
        ids={n['id'] for n in obj['nodes']}
        self.assertEqual(len(ids),len(obj['nodes']))
        for edge in obj['edges']:
            self.assertIn(edge['from'],ids)
            self.assertIn(edge['to'],ids)
        self.assertEqual(set(obj['integration']['tools']),{t['name'] for t in TOOL_DEFINITIONS})
    def test_modules_exist(self):
        root=Path(__file__).resolve().parents[1]
        obj=json.loads((root/'topology/agent-topology.json').read_text())
        for n in obj['nodes']:
            if n['kind']=='module':
                self.assertTrue((root/n['path']).is_file())
                self.assertEqual(n['sha256'],hashlib.sha256((root/n['path']).read_bytes()).hexdigest())
        actual={p.relative_to(root).as_posix() for p in (root/'agentsearch').glob('*.py')}
        self.assertEqual({n['path'] for n in obj['nodes'] if n['kind']=='module'},actual)
    def test_import_edges_match_source(self):
        root=Path(__file__).resolve().parents[1]
        modules={p.stem:p for p in (root/'agentsearch').glob('*.py')};expected=set()
        for name,p in modules.items():
            for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
                deps=[]
                if isinstance(n,ast.ImportFrom):
                    if n.level:deps=[n.module.split('.')[0]] if n.module else [a.name for a in n.names]
                    elif n.module and n.module.startswith('agentsearch.'):deps=[n.module.split('.')[1]]
                elif isinstance(n,ast.Import):deps=[a.name.split('.')[1] for a in n.names if a.name.startswith('agentsearch.')]
                expected.update(('agentsearch.'+name,'agentsearch.'+d) for d in deps if d in modules and d!=name)
        obj=json.loads((root/'topology/agent-topology.json').read_text())
        self.assertEqual(expected,{(e['from'],e['to']) for e in obj['edges'] if e['kind']=='imports'})
