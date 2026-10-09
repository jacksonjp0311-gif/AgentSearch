# Installation and use

Requires Python 3.11+ with SQLite FTS5 trigram. No runtime pip dependencies.
Run from the source checkout, or install with `python -m pip install .` into the
chosen host environment. An editable installation is also supported. Do not
change an existing host environment without its operator's authorization.

```powershell
python -m agentsearch --config state/demo.json --db state/demo.sqlite3 config --root ./examples/demo
python -m agentsearch --config state/demo.json --db state/demo.sqlite3 index
python skills/agentsearch/python_example.py --db state/demo.sqlite3 --query checkpoint
python skills/agentsearch/mcp_example.py --db state/demo.sqlite3
```

For MCP-compatible agents (including local tool-calling models), configure an
explicit Python executable with arguments `-m agentsearch --config ABS_CONFIG
--db ABS_DB mcp`, and the checkout as cwd if it is not installed. The example
performs initialization, lists five tools, reads index status and closes the child.
Do not share one stdio stream between clients; each child may open the same local
SQLite WAL index with its own connection. No network listener is installed.

For Hermes/Pegasus, see [the reviewed integration plan](../../docs/PEGASUS_INTEGRATION.md).
Pegasus names are prefixed `agentsearch_`; standalone tool names remain unchanged.
For Codex, install this skill folder in a selected skills location and configure
the MCP process in the host's supported MCP configuration; copying a skill alone
does not register tools. This package does not edit any host settings automatically.

## Troubleshooting and boundaries

- No index: configure roots and run the operator index command before searching.
- Scope mismatch: use an index built for the current accepted project, not another
  project's database. Caller-supplied paths never widen authorization.
- `complete=false`: inspect warnings, narrow the query or request a refresh.
- Changed hash: read current evidence; do not silently reuse the old receipt.
- SQLite BUSY: stop duplicate writers; preserve the error and retry a later bounded
  request. Existing readers and serialized writers have separate connections.
- Python not found in PowerShell: use `-PythonExecutable C:/path/python.exe` or
  `AGENTSEARCH_PYTHON`. No machine-specific interpreter is hardcoded.
- Database corruption: retain it for diagnosis, rebuild at a new path and run Check.
- Private indexes contain cached text. Use local filesystem permissions; do not
  commit databases or expose MCP as an unauthenticated network service.
- Reads are bounded and detect observable races, but are not a hostile-filesystem
  sandbox or a snapshot of the entire project. Hashes do not approve lessons.
