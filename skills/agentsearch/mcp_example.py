"""A finite MCP stdio client example; closes its own subprocess after the run."""
import argparse,json,subprocess,sys
from pathlib import Path

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);args=p.parse_args()
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'agentsearch-example','version':'1'}}},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list'},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'index_status','arguments':{}}}]
    result=subprocess.run([sys.executable,'-m','agentsearch','--db',str(Path(args.db).resolve()),'mcp'],
        cwd=Path(__file__).resolve().parents[2],input='\n'.join(map(json.dumps,requests))+'\n',
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    if result.returncode:raise SystemExit(result.stderr)
    responses=[json.loads(line) for line in result.stdout.splitlines()]
    if len(responses)!=3 or any('error' in row for row in responses):raise SystemExit('MCP lifecycle failed')
    if len(responses[1]['result']['tools'])!=5 or responses[2]['result'].get('isError'):raise SystemExit('MCP tool failed')
    print(json.dumps({'ok':True,'tool_count':5,'status':responses[2]['result']['structuredContent']}))
