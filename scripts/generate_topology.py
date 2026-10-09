"""Regenerate module hashes and import edges in the existing topology map."""
from pathlib import Path
import ast, hashlib, json
root=Path(__file__).resolve().parents[1]
path=root/'topology'/'agent-topology.json'
obj=json.loads(path.read_text(encoding='utf-8'))
modules={f.stem:f for f in (root/'agentsearch').glob('*.py')}
obj['nodes']=[n for n in obj['nodes'] if n['kind']!='module' or (root/n['path']).is_file()]
known={n['id'] for n in obj['nodes']}
for index,(name,f) in enumerate(sorted(modules.items())):
    if 'agentsearch.'+name not in known:
        obj['nodes'].append({'id':'agentsearch.'+name,'kind':'module','path':f.relative_to(root).as_posix(),'x':index*2,'y':4})
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
            elif n.level and not n.module: deps.update(alias.name for alias in n.names)
            elif n.module and n.module.startswith('agentsearch.'): deps.add(n.module.split('.')[1])
        elif isinstance(n,ast.Import):
            for alias in n.names:
                if alias.name.startswith('agentsearch.'): deps.add(alias.name.split('.')[1])
    for dep in sorted(deps):
        if dep in modules and dep!=name:
            obj['edges'].append({'from':'agentsearch.'+name,'to':'agentsearch.'+dep,'kind':'imports'})
import sys
sys.path.insert(0,str(root))
from agentsearch.adapter import TOOL_DEFINITIONS
obj['integration']['tools']=[t['name'] for t in TOOL_DEFINITIONS]
obj['integration']['pegasus_adapter']='agentsearch/pegasus.py; explicit host registration only'
obj['nodes']=sorted(obj['nodes'],key=lambda n:n['id'])
obj['edges']=sorted(obj['edges'],key=lambda e:(e['from'],e['to'],e['kind']))
path.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8',newline='\n')
(root/'skills/agentsearch/tool-schemas.json').write_text(json.dumps(list(TOOL_DEFINITIONS),indent=2)+'\n',encoding='utf-8',newline='\n')
print(f"Topology: {len(obj['nodes'])} nodes, {len(obj['edges'])} edges")
