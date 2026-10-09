## v0.1.1 — Pro README and design review

- Added graphic, architecture diagram, security model, performance caveats, prioritized roadmap and engineering review.
- No changes to runtime code.

# Changelog

## 0.1.0 — 2026-10-08

Initial independent, portable implementation inspired by the agent-facing use
case discussed around FSearch. No FSearch source code is included.

- Persistent SQLite metadata and FTS5 trigram indexes for selected roots.
- Literal name/path lookup with bounded fuzzy fallback.
- Literal text search with fresh verification, source hashes and line numbers.
- Explicit refresh, polling, bounded file reads, and index status.
- Python tool adapter, JSON CLI, JSONL and minimal MCP stdio interfaces.
- One PowerShell entry script and native Windows validation instructions.
- Reproducible tests and a synthetic benchmark with recorded limitations.

During validation, fixed an overbroad database-directory exclusion and Unicode
casefold-to-source snippet offsets. Added negative-search errors before initial
indexing, visible partial coverage, and an aggregate text-output cap.

Native Windows/PowerShell execution, real harness adoption, native filesystem
notifications, whole-disk scale and comparative speed remain unverified or
future work. See the validation and benchmark receipts in `docs/`.
