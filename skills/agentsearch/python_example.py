"""Invoke the standalone skill without any model SDK."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from agentsearch import SearchEngine
from agentsearch.adapter import AgentSearchAdapter

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--query',default='checkpoint')
    args=p.parse_args()
    with SearchEngine(args.db) as engine:
        adapter=AgentSearchAdapter(engine)
        print(json.dumps(adapter.dispatch('index_status')))
        print(json.dumps(adapter.dispatch('file_search',{'query':args.query,'limit':5})))
