"""10,000 checked requests from 32 concurrent logical clients on one local index."""
import argparse,hashlib,json,platform,sqlite3,sys,tempfile,time,tracemalloc
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentsearch import SearchConfig,SearchEngine,__version__
from agentsearch.adapter import AgentSearchAdapter
from agentsearch.verify import atomic_json,source_hashes


def run(requests=10000,clients=32):
    started=time.perf_counter();barrier=Barrier(clients);tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix='agentsearch-stress-') as d:
        base=Path(d);root=base/'source';root.mkdir();db=base/'state/index.sqlite3'
        for i in range(64):(root/f'marker_{i:03}.txt').write_bytes(f'unique_{i:03}\n'.encode())
        with SearchEngine(db,SearchConfig((str(root),))) as e:
            assert e.index()['complete']
        def client(number):
            latencies=[]
            with SearchEngine(db) as e:
                a=AgentSearchAdapter(e);barrier.wait(timeout=30)
                for step in range(requests//clients+(number<requests%clients)):
                    before=time.perf_counter();kind=step%5;p=root/'marker_003.txt'
                    if kind==0:
                        r=a('file_search',{'query':'marker_003','budget_ms':30000});valid=len(r.get('hits',[]))==1
                    elif kind==1:
                        r=a('content_search',{'pattern':'unique_003','budget_ms':30000});valid=len(r.get('files',[]))==1
                    elif kind==2:
                        r=a('read_file',{'path':str(p)});valid=r.get('text')=='unique_003'
                    elif kind==3:
                        r=a('verify_evidence',{'path':str(p),'sha256':hashlib.sha256(b'unique_003\n').hexdigest()});valid=r.get('verified') is True
                    else:
                        r=a('index_status',{});valid=r.get('files')==64
                    if not r.get('ok') or not valid or r.get('complete') is False:raise AssertionError('Incorrect request: '+json.dumps(r))
                    latencies.append((time.perf_counter()-before)*1000)
            return latencies
        with ThreadPoolExecutor(max_workers=clients) as pool:
            latencies=[v for values in pool.map(client,range(clients)) for v in values]
        with SearchEngine(db) as e:assert e.check()['ok']
        index_bytes=db.stat().st_size
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop();latencies.sort()
    return {'ok':True,'version':__version__,'requests':len(latencies),'clients':clients,
        'client_type':'threads, independent SQLite connections; not MCP process load',
        'elapsed_seconds':round(time.perf_counter()-started,3),
        'latency_ms':{key:round(latencies[min(len(latencies)-1,int(len(latencies)*q))],3) for key,q in [('p50',.5),('p95',.95),('p99',.99)]},
        'python_traced_peak_bytes':peak,'index_bytes':index_bytes,'source_sha256':source_hashes(),
        'environment':{'os':platform.system(),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version},
        'limitations':['Synthetic 64-file corpus, warm index, no concurrent source mutation.',
            'Python traced memory is not process RSS; tracing adds overhead. Separate suite tests concurrent writers and killed transactions.']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='state/stress.json');args=p.parse_args()
    try:result=run()
    except Exception as exc:result={'ok':False,'error':str(exc),'type':type(exc).__name__}
    atomic_json(Path(args.output),result);print(json.dumps(result));raise SystemExit(0 if result['ok'] else 1)
