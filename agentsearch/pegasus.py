"""Opt-in host adapter; importing this module does not install or register it."""
import json
from pathlib import Path
import sqlite3
from .engine import SearchEngine
from .adapter import AgentSearchAdapter, ToolArgumentError, error_result

# Broad source retrieval must not become a route around private agent memory.
PRIVATE_DIRECTORIES=frozenset({'data','runtime','recalltree','.git','.codex','.hermes'})


def register(ctx, *, project_root, index_path):
    """The trusted host supplies the accepted project and prebuilt private index.

    One connection per invocation supports independent worker threads/processes.
    This integration intentionally does not expose indexing or fresh=true; the
    operator refreshes derived state separately under the host's permissions.
    """
    project=Path(project_root).resolve(strict=True)
    database=Path(index_path).resolve(strict=True)
    if not project.is_dir() or not database.is_file():raise ValueError('Existing project and index required')
    def invoke(name,args):
        try:
            if not isinstance(args,dict):raise ToolArgumentError('Arguments must be an object')
            if args.get('fresh',False):raise ToolArgumentError('Operator must refresh the index separately')
            with SearchEngine(database) as engine:
                if tuple(map(Path,engine.config.roots))!=(project,):
                    raise ValueError('Index does not match the host-selected project')
                if not PRIVATE_DIRECTORIES.issubset({x.casefold() for x in engine.config.exclude_dirs}):
                    raise ValueError('Index must exclude Pegasus private directories before registration')
                return AgentSearchAdapter(engine).dispatch(name,args)
        except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:
            return error_result(type(exc).__name__,str(exc))
    for tool in AgentSearchAdapter.function_tools():
        schema=tool['function'];name=schema['name'];schema['name']='agentsearch_'+name
        if name=='content_search':schema['parameters']['properties'].pop('fresh',None)
        def handler(args,_name=name,**kwargs):
            return json.dumps(invoke(_name,args),ensure_ascii=True)
        ctx.register_tool(name=schema['name'],toolset='pegasus_local',schema=schema,
                          handler=handler,description=schema['description'])
