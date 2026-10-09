# Engineering review — AgentSearch 0.2.0

## Scope

Reviewed and modified the actual supplied v0.1.1 ZIP. Its engine/package metadata still identified as v0.1.0. The original functional suite was rerun: 31 passed, 2 native-Windows skips. No claims from the previous assistant response were accepted as fresh validation.

## Fixed findings

- Corrected top-k tie boundaries to use path ascending consistently, including when only a prefix of tied results is returned.
- Removed per-open metadata/schema writes for an existing index, avoiding needless reader/writer contention.
- Pinned query candidates and their coverage receipt to one SQLite read snapshot.
- Found an intermittent concurrent-first-open WAL transition lock failure during repeated tests. Added a bounded retry specific to this idempotent operation, then reran full suites and a 512-open stress test. The failed pre-fix receipt is retained under validation/development-failures.
- Added safe ratio bounds and per-query caches without approximate candidate admission. Added top-k pruning before needless source checks.
- Replaced short-pattern source-file scanning with cached SQLite substring candidate selection, explicitly documenting the changed short-query freshness semantics.
- Detected atomic file replacement as well as writes to an open descriptor; unstable source reads are not returned as reliable evidence.
- Recognized UTF-32 BOMs before UTF-16, rejected decoded embedded NUL text, and made unsupported filesystem strings a visible incomplete scan rather than a total crash.
- Rejected duplicate JSON object keys and unpaired surrogates; tested service recovery after malformed input.
- Added administrative index integrity checks, forced rereads, manifest validation, atomic receipts, release-version tests and isolated native launcher gates.
- Corrected content_search's MCP read-only annotation because an optional refresh writes derived index state.
- Repaired the demonstration filename corrupted by the prior ZIP's text encoding. Archived the old generated infographic, whose examples and claims do not represent this release.

## Performance evidence and tradeoff

Original and refined runtimes were measured on the same seeded 2,000-file corpus, same host and query settings. Both passed 101 known-target checks. Median typo search improved from about 345 ms to 165 ms; the short sentinel improved from about 223 ms to 2.32 ms. Literal reads and initial indexing became somewhat slower because of added checks. This is not a claim of uniform acceleration, semantic-search quality, or whole-disk performance.

A 10,000-file run passed 51 target checks at a separately declared 5-second query budget. It demonstrates a larger synthetic fixture only. Full fuzzy scans still limit scaling.

## Reliability evidence

See the raw repeated-suite, soak, startup-stress and legacy-compatibility JSON receipts. The soak covers 500 seeded mutation cycles and 25 reopenings with direct checks of returned files, hashes and line evidence. Functional tests terminate an actual child process midway through an index transaction, inject KeyboardInterrupt, check concurrent readers/writers and confirm source bytes remain unchanged.

Build-time receipts are pre-seal. Final release packaging checks the manifest and reruns the tests from an independently extracted ZIP. Hashes identify tested sources; they are not signatures or a proof of absence of defects.

## Remaining limitations

Native Windows/PowerShell, macOS and Python 3.11/3.12 were not executed here. CI configuration is not CI evidence. Filesystem reads are not a hostile-race-proof sandbox. Refreshes are non-atomic, stat-based unless forced, and exclude oversized/unsupported content. Network filesystems, power-loss durability, million-file scale, independent MCP-client interoperability and real agent task outcomes remain unverified.

## Release recommendation

Ship as a small, evidence-backed local tool with a visible native-Windows acceptance gate. Preserve the four-tool contract. Do not add memory, orchestration or autonomous features until the target-host checks pass and a measured workload calls for them.
