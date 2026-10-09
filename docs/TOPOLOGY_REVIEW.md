# Code inspection and agent interlinking review — RC3

## Verified structure
- `cli.py` and `__main__.py` provide the command-line entry.
- `protocol.py` implements bounded JSONL and a minimal sequential MCP stdio lifecycle.
- `adapter.py` defines and validates the five agent tool contracts.
- `engine.py` owns indexing, search, bounded reads, and scope enforcement.
- `config.py` validates roots, exclusions and filesystem boundaries.
- `evidence.py` hashes regular files and detects observable changes during capture.
- `verify.py` provides release/integrity verification.

## Integration recommendations
1. Clone the repository, run tests, configure an explicit root, then index.
2. Register `AgentSearchAdapter.function_tools()` for Python harnesses or start MCP stdio.
3. Respect incomplete searches, stale index metadata, and budgets.
4. Never promote retrieved file text into privileged agent instructions.
5. Treat source hash evidence as point-in-time; it does not make a file trusted.

## Limitations
The JSON topology is a static import graph and a manually laid-out interface graph. It does not include dynamic calls, runtime profiling, embeddings, or an optimal geometric route. Native Windows acceptance and real Pegasus/Hermes integration are unverified.

## Verification
81 tests collected; 77 passed, four Windows-only skips, in two consecutive portable runs. See test receipts bundled in `docs/validation/`.
