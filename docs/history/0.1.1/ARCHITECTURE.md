# Architecture

**AgentSearch 0.1.0 — persistent local retrieval baseline**

[README](../README.md) · [Agent integration](AGENT_INTEGRATION.md) · [Windows validation](WINDOWS_VALIDATION.md)

## Intended job

AgentSearch turns a set of explicitly selected directories into a reusable search index. Its consumers are terminal agents, local harnesses, and Python applications. It returns file locations and bounded text evidence; task reasoning belongs to its caller.

The engine depends on Python's standard library and a SQLite build with FTS5 trigram support. This deliberately keeps source execution simple across Windows and Linux. The PowerShell script supplies a fixed Windows entry point; it does not install a service or alter an existing agent system.

## Data flow

| Stage | Input | Output and constraint |
| --- | --- | --- |
| Configure | Explicit root paths and exclusions | Local JSON configuration |
| Enumerate | Configured directories | File metadata, excluding links and reparse points; directories are traversed, not returned as search hits |
| Reconcile | Metadata and prior database state | New/changed records refreshed; observed removals reconciled |
| Index text | Eligible text within the size ceiling | Persistent SQLite FTS5 trigram candidate index |
| Query | Name query or literal content pattern | Bounded candidates, filters, and completion information |
| Verify content | Current candidate files | Current matching lines rather than stored index snippets |
| Read | Allowed path and line/character bounds | Bounded text for the caller to inspect |

## Persistent state

The SQLite database is the persistent search index. It is not a learned memory store, an agent policy, or the authority for current file contents. The source files remain authoritative for reads and final content-match verification.

Metadata reconciliation avoids rereading unchanged content by comparing file size, `mtime_ns`, and `ctime_ns`. Directory enumeration remains necessary for the polling implementation. This reduces repeated content work but does not make incremental reconciliation independent of the number of filesystem entries.

State is separated from source code:

- `config/search.json` identifies allowed roots and content eligibility settings.
- `state/index.sqlite3` stores metadata and text index state.
- `state/rootmirror.json` records the package root used by the PowerShell launcher.

These generated files are local to a machine and must not be included in a clean source release. The database can contain representations of indexed text, so treat it as part of the indexed workspace's data.

## Search semantics

### Filename and path search

Name search works with indexed metadata and ranks name/path candidates. Approximate matching is useful when an agent recalls only part of a name or makes a typing error. Its bounded fallback may inspect many entries. The current design does not guarantee constant-time fuzzy search or global ranking beyond a reported candidate budget.

### Content search

The content operation searches literal text. Regular expressions, language-aware symbol resolution, embeddings, and semantic search are outside version 0.1.0.

For eligible patterns, SQLite FTS5 trigram lookup narrows candidates. Each candidate is then read from disk and checked before matching text is returned. Verification is needed because the files may have changed since indexing and because index candidate retrieval is not itself a complete statement of exact current matches.

Very short patterns cannot be selected by a three-character index, so they can require a bounded content scan. A small query budget can therefore produce partial results even for an apparently simple request.

### Bounded reads

The read operation accepts a file path and limits for its starting line, line count, and character count. It checks the configured root scope before reading. This keeps retrieval output manageable for a model context; it is not a substitute for the operating system's process permissions.

## Freshness model

There are three distinct moments:

1. The last index reconciliation determines what records and content candidates are known.
2. A content query rereads the current contents of its selected candidate files.
3. A subsequent read sees the file as it exists at that later read.

These operations do not freeze the filesystem. A file can change between any two moments. A stale candidate index can omit a newly matching file even when all returned matches have been verified against current content.

`index` reconciles explicitly. `grep --fresh` performs reconciliation before candidate retrieval. Its reconciliation time is additional work: the query budget applies to the search phase after reconciliation. `watch` repeats reconciliations and waits between them. No process remains after a foreground watch is stopped.

Metadata checks can miss content changes that preserve all checked metadata: file size, `mtime_ns`, and `ctime_ns`. Timestamp behavior, concurrent writes, unavailable roots, and permissions also constrain coverage. A stronger future freshness contract would need content fingerprinting and explicit rescan policies, with their additional I/O cost measured.

## Completion and budgeting

A search may be limited by result count, candidate count, elapsed query budget, per-file matching lines, or maximum snippet size. Content-match snippet text is also capped at 32,000 characters across the response. Snippet/per-file truncation, a stopped search, and an incomplete index are reflected in completion information. Consumers must inspect that information instead of equating an empty result with global absence.

A completed index search means the applicable work finished within that index's declared coverage. It does not imply that excluded files were searched or that the index observed every concurrent filesystem change. Search timing budgets are cooperative limits, not hard real-time deadlines; a blocking filesystem read or database operation can exceed a target interval.

## Boundary enforcement

Allowed roots are explicit and excluded directories are configurable. Symlinks and Windows reparse points are skipped to avoid ordinary traversal through an unexpected destination. Scope requests and file reads are constrained to configured roots.

This is a local tool running with its owner's OS permissions. Path checks and skips are practical retrieval boundaries, not a claim of isolation against an adversary concurrently replacing filesystem objects. The process should be configured to index the repositories and notes actually needed by its caller.

## Interface separation

| Interface | Transport | Purpose |
| --- | --- | --- |
| CLI | One process invocation | Scripts, terminal agents, manual use |
| JSONL | One JSON request and response per line | Persistent local adapter with an explicit small protocol |
| MCP | JSON-RPC over standard input/output | Tool discovery and calls for compatible MCP clients |
| Python | Direct imports | Embed retrieval without shell parsing |

The JSONL protocol is custom. The MCP adapter is a separate minimal implementation supporting the documented initialization and tool operations. It has not been presented as complete MCP conformance or as tested with every harness. All runtime protocol messages belong on stdout; diagnostics belong on stderr.

## Future Windows acceleration

The version 0.1.0 backend is enumeration plus polling. Windows supports two useful primitives for later work:

| Proposed backend | Intended benefit | Required recovery behavior |
| --- | --- | --- |
| `ReadDirectoryChangesW` | Receive directory/subtree notifications while running | Rescan after notification loss, buffer overflow, or unsupported operation |
| NTFS USN change journal | Replay volume changes across process downtime when available | Track journal identity and cursor; reconcile when continuity cannot be established |

Microsoft documents subtree notifications and explicitly requires enumeration to recover after certain lost-change conditions in [ReadDirectoryChangesW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-readdirectorychangesw). Its [change-journal overview](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals) describes NTFS volume-level change records and recovery use cases.

A later backend should preserve the same root policy and search response semantics. Native events should identify what may need reconciliation; they should not make an unverified claim that a file is unchanged. Journal handling also needs clear behavior for unavailable journals, volume changes, and gaps in retained history.

No native backend, journal access, Windows handle management, or replay checkpoint is implemented in this release. Those claims require Windows tests and corpus measurements after implementation.

## Measurement plan

Measure first-index duration, incremental duration after edits, warm-query p50/p95, end-to-end CLI latency, index disk size, and known-result recall. Record file count, text bytes, root exclusions, Python and SQLite versions, operating system, and storage hardware with every run.

Use separate workloads for exact names, misspelled names, common literals, rare literals, Unicode, short patterns, and no-match queries. Include changes between index and query, file deletions, locked files, and result caps. A selective warm query is not a proxy for complete whole-disk performance.
