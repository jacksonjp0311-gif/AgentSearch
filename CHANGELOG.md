## 1.0.0 RC3 — Topology and integration map

- Added machine-readable module graph with logical geometric coordinates and source hashes.
- Added conceptual Mermaid architecture and topology documentation.
- Added clone-and-test PowerShell helper and topology consistency tests.
- Kept runtime search and agent tools unchanged; Windows-native acceptance remains pending.

## 1.0.0 RC2 — Git preparation and documentation corrections

- Five-tool README and release identity updated.
- Added Git push checklist.
- Preserved conservative content-search annotations (fresh indexing writes derived state, never source files).
- Native Windows acceptance remains pending.

## 1.0.0 RC1 — Agent evidence verification\n\n- Exposed `verify_evidence` through the existing agent adapter/MCP tool contract.\n- Restricted verification to configured roots and made malformed digests explicit failures.\n- Added integration regression test and updated protocol contract assertion.\n- Added release gates and honest RC documentation.\n- Native Windows acceptance still pending.\n\n## v0.3.0 — Verifiable evidence

- Added content-addressed evidence receipt and verification helper.
- Added dedicated regression tests.
- Added linked README directory and release notes.
- Existing search interfaces unchanged; native Windows verification pending.

# Changelog

## 0.2.0 — Reliability and targeted optimization

Implemented safe fuzzy pruning/caches, deterministic top-k ties, cached short-pattern scans, read snapshots, writer-safe reader startup, bounded first-open WAL retries, stronger file identity checks, UTF-32 support, strict JSON parsing, forced scans and administrative integrity checks. Added repeatable release verification, mutation soak, crash/concurrency regressions and native PowerShell acceptance tests. Aligned runtime/package/manifest version and repaired the original demo filename.

**Behavior changes:** all content lengths use indexed candidate selection; short queries now require refresh to see newly added terms, just like longer queries. `matched` is explicitly qualified as indexed candidates. Unstable reads fail/omit rather than returning uncertain evidence. Fuzzy acceptance scores remain compatible; tie order is intentionally fixed. Optional content refresh is honestly annotated as modifying derived state.

**Measured:** only Linux / Python 3.13.5 / SQLite 3.46.1. Native Windows and other platform/runtime gates remain pending. See docs/validation for detailed evidence, including the startup race caught and fixed during development.

## 0.1.1 — Prior presentation package

Documentation and visual changes; underlying runtime remained 0.1.0. Original documents and receipts are preserved under docs/history/0.1.1. Prior concept art is archived and not a current technical specification.

## 0.1.0 — Portable baseline

Python/SQLite engine with explicit roots, filename/content search, bounded reads, CLI, JSONL and a minimal MCP stdio adapter.
