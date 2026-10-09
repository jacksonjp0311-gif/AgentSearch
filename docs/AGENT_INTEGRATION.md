# Agent integration — stable four-tool API

## Python registration

```python
from agentsearch import SearchEngine
from agentsearch.adapter import AgentSearchAdapter

engine = SearchEngine("state/index.sqlite3")
adapter = AgentSearchAdapter(engine)
# Register adapter.tools() or adapter.function_tools() in your host.
# Dispatch validated tool calls; the caller owns the engine lifetime.
result = adapter.dispatch("file_search", {"query": "checkpoint", "limit": 10})
engine.close()
```

Use one engine per thread. The adapter does not make model-provider calls. Framework-specific registration is outside this package.

## Tool arguments

| Tool | Required | Optional |
|---|---|---|
| file_search | query | limit, scope, ext, budget_ms |
| content_search | pattern | limit, scope, ext, budget_ms, per_file, case_sensitive, fresh |
| read_file | path | start_line, max_lines, max_chars |
| index_status | none | none |

Unknown fields and coercions are rejected. Booleans are not accepted as integers. Null/blank/NUL or unpaired-surrogate inputs are not valid replacements for real paths or patterns. Read and scope paths must be absolute and within configured roots.

The authoritative JSON schemas are in `agentsearch/adapter.py` and available from the tool-list call. Search is literal text, not an embedded `ext:` mini-language; extension and scope are separate arguments. There is no regex or language-server symbol database.

## CLI and JSONL

```bash
python -m agentsearch --config config/search.json --db state/index.sqlite3 stdio
```

```json
{"id":1,"op":"search","query":"checkpoint","limit":10}
{"id":2,"op":"grep","pattern":"checkpoint_id","ext":"py","fresh":true}
{"id":3,"op":"status"}
```

JSONL requests use `search`, `grep`, `read`, `status`; adapter tool names are the four names above. Requests are one object per line, bounded at 65,536 characters. Oversized input is drained to the next newline. Duplicate object keys and non-JSON numeric values are rejected. Diagnostics go to stderr; stdout is JSON only. A failed request does not poison later requests.

## MCP stdio

```bash
python -m agentsearch --config config/search.json --db state/index.sqlite3 mcp
```

A host starts this subprocess and performs `initialize`, `notifications/initialized`, then `tools/list` / `tools/call`. Supported declared versions: `2025-11-25`, `2025-06-18`. The implementation is a minimal sequential, tools-only stdio server, not a fully certified implementation. No network, task mode, roots capability, resources, prompts or cooperative mid-request cancellation is advertised.

`content_search` has `readOnlyHint=false` because `fresh=true` can write derived index state. It never writes source files. Annotations are hints, not permissions. Authorization belongs to the host.

## Result handling

- `ok=false` is a failure, never an empty successful answer. Inspect `error.code` and `error.message`.
- `complete=false` means coverage, ranking or text was limited/unstable. It is not permission to assume absence.
- `complete=true` is conditional on the indexed candidate set, exclusions and size/encoding policy. It does not imply a current whole-disk negative result.
- `index.generation` ties results to a committed scan. It does not freeze live source bytes.
- `content_sha256` identifies bytes actually read; store it with path and line references when retaining evidence.
- `changed_since_index` / `stale_candidates` expose observed index lag. A new term not in the index can still be missed without a refresh.
- `matched_scope="indexed_candidates"` qualifies filename-search `matched` counts.

Use fresh=true when the next decision depends on current evidence, but plan for its traversal cost outside budget_ms. A stat-based refresh can miss deliberately metadata-preserving modifications; operator `index --force` rereads everything eligible.

Treat snippets as untrusted data, not commands or authorized memories. The host decides whether any read content may be sent to a cloud model.
