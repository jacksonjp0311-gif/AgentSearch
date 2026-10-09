# Windows validation

**AgentSearch 0.1.0 — native execution pending**

[README](../README.md) · [Architecture](ARCHITECTURE.md) · [Agent integration](AGENT_INTEGRATION.md)

This package was authored in a Linux environment. Its executed unit run collected **33 tests: 31 passed and 2 Windows-specific tests were skipped**; see [the validation receipt](VALIDATION_RESULTS.json). A separate synthetic benchmark passed **101 known-result checks**; see [the benchmark receipt](BENCHMARK_RESULTS.json).

A Windows host and a PowerShell runtime were not available for direct native validation there. Portable unit tests and static source review provide useful evidence, but they do not establish Windows behavior. The included CI matrix requests Windows and Linux jobs when this source is placed in a repository and the workflow runs.

## Acceptance gate

| Check | Initial status | Evidence to record |
| --- | --- | --- |
| Python 3.11+ found by `py -3` or `python` | Pending on Windows | Interpreter version and resolved executable |
| SQLite FTS5 trigram available | Pending on Windows | Successful index creation; SQLite version |
| PowerShell 5.1 launcher parse and execution | Pending | Setup, Index, Search, Read, Status exit codes |
| PowerShell 7 launcher execution | Pending | Same actions if that shell is used |
| Native unit suite | Pending | Test command and complete output |
| Windows paths and Unicode | Pending | Paths containing spaces and non-ASCII text |
| Junction/reparse point skip | Pending | A root-local link to an outside directory remains unread |
| File creation, rename, deletion | Pending | Reconciled search results and status |
| Foreground polling stop | Pending | Ctrl+C exits watch without an installed background task |
| JSONL transport | Pending | Multiple valid requests, malformed request recovery |
| Actual harness MCP handshake | Pending | Client name/version, initialize, tool list, search, read |
| Windows performance | Pending | Corpus, timings, output caps, Python/SQLite versions |

Record native results when performed. Do not mark a row passed merely because a workflow file or a test exists.

## Small demonstration run

In PowerShell, from the extracted package folder:

```powershell
.\AgentSearch.ps1 -Action Setup
.\AgentSearch.ps1 -Action Index
.\AgentSearch.ps1 -Action Search -Query 'checkpoint'
.\AgentSearch.ps1 -Action Grep -Query 'checkpoint' -Fresh
.\AgentSearch.ps1 -Action Status
.\AgentSearch.ps1 -Action Test
```

The first Setup uses only the bundled examples if configuration does not already exist. Search words should be adjusted to a known phrase from the supplied examples if necessary. Preserve the JSON index/search output and the test report as evidence.

## One real repository

Choose an existing repository and record a known source file plus one literal phrase it contains:

```powershell
.\AgentSearch.ps1 -Action Setup -Root 'C:\Projects\MyRepo'
.\AgentSearch.ps1 -Action Index
.\AgentSearch.ps1 -Action Search -Query 'known-file-name'
.\AgentSearch.ps1 -Action Grep -Query 'known literal phrase' -Fresh
.\AgentSearch.ps1 -Action Read -Path 'C:\Projects\MyRepo\known-file.py' -MaxLines 80
```

All paths and search values are examples to replace. Measure the first index separately from subsequent reconciliations. A PowerShell timing example is:

```powershell
Measure-Command { .\AgentSearch.ps1 -Action Index }
```

That measurement includes launcher and interpreter startup. In-process search timings describe a different latency and should be reported separately.

## Native path cases

Use a temporary test directory, explicitly configured as a root, to check:

- Folder and file names with spaces, accented letters, and non-Latin characters.
- A sibling path with a similar prefix that is outside the root.
- Different letter casing for a path on the filesystem used by the project.
- A junction or other reparse point that leads outside the root.
- A locked, unreadable, or concurrently removed file.
- Nested excluded directories and files above the content-size ceiling.

Validate the result and the reported coverage in each case. Windows filesystem behavior and reparse point creation permissions can differ by machine. Long paths, network shares, cloud placeholders, and unusual encodings require additional workload-specific validation before they are relied upon.

## Freshness and output bounds

1. Index a small file with a unique literal string.
2. Change the string, preserving a normal modification timestamp update.
3. Compare ordinary Grep with Grep using `-Fresh`.
4. Create and remove a file, then run Index and check both outcomes.
5. Run a frequent literal with `-Limit 1` and `-PerFile 1` and inspect truncation/completion information.
6. Run a short literal under a small budget and verify that partial results are not interpreted as an exhaustive search.

An additional metadata test can attempt to edit content while preserving the checked size, `mtime_ns`, and `ctime_ns`. Record which metadata the filesystem actually changed; only a change that preserves every checked field demonstrates this limit. Passing ordinary refresh tests does not establish detection of such a change.

## MCP in the intended harness

Use the concrete launcher in [Agent integration](AGENT_INTEGRATION.md). Confirm the client receives a valid initialization response, sees all four tools, completes a known filename search, searches a known literal, and reads a returned path. Capture protocol errors without mixing diagnostic text into stdout.

No Pegasus/Hermes configuration has been changed by this source package. Integration should be recorded only after these steps complete in that actual harness.

## How to report results

Record date, OS build, PowerShell version, Python version, SQLite version, hardware, chosen roots, file count, content ceiling, exclusions, first-index time, incremental time, and query p50/p95. State whether timing includes process startup. Preserve the exact queries and any incomplete or truncated result flags.

The goal of this gate is a measured Windows baseline that justifies the next implementation choice: use the portable tool as-is, add native change notifications, or replace a measured hot path with a compiled backend.
