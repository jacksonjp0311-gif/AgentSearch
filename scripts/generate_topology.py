"""Regenerate module hashes and import edges in the existing topology map."""
from pathlib import Path
import ast, hashlib, json
root=Path(__file__).resolve().parents[1]
path=root/'topology'/'agent-topology.json'
obj=json.loads(path.read_text())
modules={f.stem:f for f in (root/'agentsearch').glob('*.py') if f.stem!='__init__'}
for node in obj['nodes']:
    if node['kind']=='module':
        f=root/node['path']
        node['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()
obj['edges']=[e for e in obj['edges'] if e['kind']!='imports']
for name,f in sorted(modules.items()):
    deps=set()
    for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
        if isinstance(n,ast.ImportFrom):
            if n.level and n.module: deps.add(n.module.split('.')[0])
            elif n.module and n.module.startswith('agentsearch.'): deps.add(n.module.split('.')[1])
        elif isinstance(n,ast.Import):
            for alias in n.names:
                if alias.name.startswith('agentsearch.'): deps.add(alias.name.split('.')[1])
    for dep in sorted(deps):
        if dep in modules and dep!=name:
            obj['edges'].append({'from':'agentsearch.'+name,'to':'agentsearch.'+dep,'kind':'imports'})
path.write_text(json.dumps(obj,indent=2)+'\n')
print(f"Topology: {len(obj['nodes'])} nodes, {len(obj['edges'])} edges")
