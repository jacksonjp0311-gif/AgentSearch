# Operations and recovery

## Normal use

1. Keep source files in their ordinary project folders. Put the SQLite index in a dedicated local state directory.
2. Run Setup with narrow authorized roots, then Index and Check.
3. Use Search/Grep/Read. Use fresh content search when recency matters.
4. Run Watch only when needed; it remains in the foreground and stops on Ctrl+C. It is not silently restarted.

The default single-folder distribution stores config/search.json, state/index.sqlite3, and state/rootmirror.json locally. Setup reanchors a moved package; it does not automatically change already configured source roots.

## Repeatable software verification

```powershell
.\AgentSearch.ps1 -Action Verify -Repeat 5
```

The output is state/verification.json. Tests use temporary fixtures, including child-process termination and concurrency. They do not target configured personal source roots. Verify is stricter than Test: it checks the release manifest before running tests. An intentionally edited checkout can use the developer-only `python -m agentsearch.verify --allow-unsealed`, whose receipt explicitly does not establish release integrity.

## Index check and forced refresh

```powershell
.\AgentSearch.ps1 -Action Check
.\AgentSearch.ps1 -Action Index -Force
```

Check validates SQLite, FTS internals and row relationships. It does not certify current filesystem coverage. Force rechecks eligible bytes even when metadata appears unchanged. Neither command repairs damaged source files or scans excluded content.

## Incomplete results

Read warnings and coverage. A deleted candidate, failed directory traversal, changed file, result cap, excerpt cap or expired budget can make a response incomplete. Refresh or narrow the query and retry. Do not convert a failure into “no matches.”

## Corrupt index

Stop watchers and clients first. Preserve the diagnostic receipt. Build at a NEW database path using the existing explicit configuration:

```bash
python -m agentsearch --config config/search.json --db state/rebuilt.sqlite3 index
python -m agentsearch --config config/search.json --db state/rebuilt.sqlite3 check
```

Point clients at the verified replacement. The tool does not automatically delete the old index or source files. Replacement of the default index is an operator decision; do not copy only a live SQLite main file while ignoring its WAL state.

## Upgrade

Stop old-version processes. Extract the complete new release to one folder. Rerun Setup and index. Schema-1 legacy reuse is supported and tested; mixed-version concurrent writers are not. Do not overlay a partially downloaded package or retain unlisted Python files.

## Sharing and secrecy

The cached index may contain source text and secrets. Protect its state directory with host permissions. Share code and test receipts, not a personal source index. The manifest is not a publisher signature or an access-control mechanism.
