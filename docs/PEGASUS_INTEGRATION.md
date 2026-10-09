# Prepared Pegasus integration — not installed

Pegasus's `integrations/chat_agent.py` constructs Hermes AIAgent. Its operator and
specialist toolsets include `pegasus_local`. `integrations/pegasus_tools.py:register(ctx)`
uses Hermes PluginContext's `register_tool(name, toolset, schema, handler, description)`.
Skills are discovered separately from package `skills/`, the active Hermes home's
`skills/`, and specialist skills. Copying a skill alone does not register tools.

The prepared `agentsearch.pegasus.register` matches this interface. It registers
five `agentsearch_`-prefixed names without replacing existing tools. The trusted
host supplies the accepted project and index path; they are not model arguments.
Each call checks the persisted root and opens/closes its own SQLite connection.
An index with different roots is rejected. Refresh belongs to the operator:
`fresh=true` is denied even if a caller bypasses the advertised schema.

The broad source profile requires exclusions for data, runtime, RecallTree, .git,
.codex and .hermes. It cannot bypass identity-scoped agent memory. Authorized
experiment artifacts should later use a separate narrow export root and explicit
host scope, not generic access to the private data tree. AgentSearch hashes do not
automatically satisfy Pegasus's native source-read receipt and review contracts.

## Minimal connection procedure (future installation)

1. Install this exact reviewed source into the chosen host Python environment
   with `python -m pip install C:/path/to/AgentSearch`, or explicitly add the
   checkout to that process's import path. Preserve the existing environment.
2. Build a separate source-only index with that interpreter:

```powershell
python -m agentsearch --config C:/AgentSearchState/pegasus.json --db C:/AgentSearchState/pegasus.sqlite3 config --root C:/Users/jacks/PEGASUS --exclude data --exclude runtime --exclude RecallTree --exclude .codex --exclude .hermes
python -m agentsearch --config C:/AgentSearchState/pegasus.json --db C:/AgentSearchState/pegasus.sqlite3 index
python -m agentsearch --db C:/AgentSearchState/pegasus.sqlite3 check
```

3. Add this call to the host registration path after project acceptance, supplying
   stored host values, never caller-supplied tool arguments:

```python
from agentsearch.pegasus import register as register_agentsearch
register_agentsearch(ctx, project_root=accepted_project_root,
                    index_path=project_scoped_index_path)
```

4. Make `skills/agentsearch/` discoverable in the selected host skill directory.
   Validate the five tools in isolation, including outside-project/private-memory
   rejection. Run Pegasus regression gates and implement native source-receipt
   adaptation before these reads are used to satisfy its acceptance contracts.
5. Roll back by removing this registration and skill. Do not delete memories.

No Pegasus production file, configuration, process, index or memory was changed.
There is no automatic installer. Test the prepared connection now from AgentSearch:

```powershell
python -m unittest discover -s tests -p test_pegasus_skill.py -v
```

The skill folder contains Python/MCP examples and generated schemas. Model task
improvement remains a separate gate; this package supplies retrieval, not learning.
