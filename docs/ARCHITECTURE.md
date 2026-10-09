# Architecture — AgentSearch 0.2.0

## Boundaries

Source files are read-only inputs. SQLite is derived, writable state. Agents consume JSON results. The host decides which agents may read which roots; this tool is not an authentication system.

The persisted schema remains version 1: `files`, `names_fts`, `contents_fts`, and `meta`. A new `meta.generation` value increments transactionally with successful scans. Old version-1 indexes without it begin at generation 0. A generation identifies a committed enumeration, not a frozen filesystem image.

## Index transactions

An initial opener creates the schema within a write transaction. An idempotent WAL-mode transition has a bounded, narrow retry for SQLite BUSY/LOCKED races. Other operational errors are not hidden in retry loops. Existing readers avoid unnecessary schema/metadata writes on startup.

`index(force=False)` takes `BEGIN IMMEDIATE`, enumerates explicit roots, updates changed rows and text, and writes a receipt in the same transaction. A failed traversal prevents deletion cleanup. An exception or interrupted process leaves the last committed state. `force=True` rereads files even when stat metadata matches. Metadata-only detection remains a heuristic for ordinary refreshes.

`PRAGMA synchronous=FULL` is explicit. Process termination recovery was tested; storage-controller behavior and physical power loss were not.

## Query snapshots

Search, content search, bounded reads and status run with a scoped SQLite read transaction. Configuration checks, candidate selection and generation metadata therefore refer to the same committed snapshot. Every exit path clears the progress handler and releases the transaction. Source bytes remain live and cannot be made atomic by a SQLite snapshot.

## Filename ranking

Literal candidates use the trigram name/path index for sufficiently long terms; shorter terms use a scan. Only when literal search produces no valid hits and is otherwise complete does fuzzy fallback run. It preserves the original SequenceMatcher orientation and 0.65 per-term acceptance threshold.

Fuzzy comparison uses two safe upper bounds before an expensive exact ratio. For lengths m,n, 2 min(m,n)/(m+n) bounds the possible similarity. SequenceMatcher.quick_ratio is a second upper bound. If either is below 0.65, the piece cannot meet the threshold. Accepted scores remain exact. Per-query LRU caches are bounded and retain no result cache across requests.

A top-k heap ranks score descending then path ascending. Low-ranked candidates that cannot improve the heap skip filesystem metadata work. An unavailable contender cannot evict a valid hit. The `matched` counter describes indexed candidates, not verified live files. These changes are covered by a brute-force reference comparison and top-k tie regressions.

Fuzzy search still scans the filename inventory. There is no claim of a sublinear fuzzy index, approximate-neighbor guarantee, novel similarity theorem, or FSearch-level latency.

## Content selection and verification

For folded patterns with at least three code points, FTS5 selects candidates. For one or two code points, SQLite `instr` scans the cached folded body and returns matching row IDs. This avoids opening every source file, but gives short queries the same refresh requirement as longer indexed queries.

Selected candidates are opened with available no-follow/nonblocking flags. Descriptor identity and stat metadata are checked, followed by a pathname check. Replaced/changing files are not returned as stable evidence. Results include SHA-256 of observed bytes and bounded line excerpts. The source is not locked against hostile concurrent mutation; operating-system isolation remains necessary.

Text decoding supports UTF-8 and BOM-marked UTF-16/UTF-32. Embedded NULs are treated as binary. Oversized files retain filename visibility without content indexing. Unsupported filesystem strings produce a visible incomplete scan rather than crashing the whole scan.

## Budgets and output

Budgets are cooperative SQLite progress checks plus checks between Python work units. They cannot preempt an arbitrary operating-system read or guarantee a wall-clock deadline. Fresh reconciliation precedes the query budget. Result and excerpt limits are surfaced in metadata.

A single engine belongs to one thread. Independent connections may read the same local WAL index while writers serialize. Long-lived JSONL/MCP sessions execute one request at a time.

## Administrative integrity

`check()` is a CLI/Python administrative method, not a fifth agent tool. It runs SQLite integrity checking, FTS integrity checks and missing/orphan row checks within a transaction that is rolled back. It does not repair corruption, verify live coverage or authenticate a publisher.

`agentsearch.verify` checks release hashes, runs isolated tests repeatedly, and writes an atomic JSON receipt. The manifest is unsigned local integrity data. It detects accidental damage, not a malicious publisher able to replace both package and manifest.

## Primary technical references

- SQLite FTS5/trigram behavior: https://sqlite.org/fts5.html
- SQLite snapshot isolation: https://sqlite.org/isolation.html
- Python SequenceMatcher upper bounds: https://docs.python.org/3.13/library/difflib.html
- MCP declared tools lifecycle: https://modelcontextprotocol.io/specification/2025-11-25/server/tools

These references support implementation choices. They do not certify this implementation or its benchmarks.
