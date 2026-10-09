"""Register and invoke all five tools using a real installed Hermes PluginContext.

Runs only against a disposable project/index/profile, never a production plugin.
"""
import argparse,hashlib,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentsearch import SearchConfig,SearchEngine
from agentsearch.pegasus import register,PRIVATE_DIRECTORIES

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--hermes-source',required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='agentsearch-hermes-') as d:
        base=Path(d);os.environ['HERMES_HOME']=str(base/'profile')
        sys.path.insert(0,str(Path(args.hermes_source).resolve()))
        from hermes_cli.plugins import PluginContext,PluginManager
        from hermes_cli.plugins_manifest import PluginManifest
        from tools.registry import registry
        root=base/'project';root.mkdir();source=root/'marker.txt';source.write_bytes(b'fixture marker')
        db=base/'index.sqlite3'
        with SearchEngine(db,SearchConfig((str(root),),exclude_dirs=tuple(PRIVATE_DIRECTORIES))) as e:e.index()
        manager=PluginManager(scope_key='agentsearch-isolated-smoke')
        ctx=PluginContext(PluginManifest(name='agentsearch-test',version='1',source='user'),manager)
        register(ctx,project_root=root,index_path=db)
        calls=[('index_status',{}),('file_search',{'query':'marker'}),('content_search',{'pattern':'fixture'}),
               ('read_file',{'path':str(source)}),('verify_evidence',{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})]
        outputs=[]
        for name,arguments in calls:
            entry=registry.get_entry('agentsearch_'+name,scope=manager.scope_key)
            if entry is None:raise RuntimeError('Tool was not registered: '+name)
            value=json.loads(entry.handler(arguments))
            if not value.get('ok'):raise RuntimeError('Tool failed: '+name)
            outputs.append({'tool':name,'ok':value['ok']})
        print(json.dumps({'ok':True,'tools':outputs,'scope':'Real PluginContext and registry; synthetic fixture, no model or production installation'}))
