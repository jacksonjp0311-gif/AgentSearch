import json,unittest
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
