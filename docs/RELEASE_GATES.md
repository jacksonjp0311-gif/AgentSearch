# Release gates — 1.0.0 RC1

## Completed here
- Portable unit/integration suite: 79 collected, 75 passed, 4 platform skips.
- MCP tool-list contract updated for `verify_evidence`.
- Changed and unauthorized evidence verification tested.
- Source files are never modified by the evidence helper.

## Required before stable 1.0.0
- Native Windows PowerShell + NTFS acceptance (not available in this environment).
- 10,000 repeated requests and 32 concurrent clients on target hardware.
- Crash-recovery, symlink, junction, path-race and malicious-content audit on Windows.
- Compatibility tests with a real Hermes/Pegasus harness.
- Reproducible benchmarks and retrieval-accuracy comparisons on real projects.

The release candidate is suitable for evaluation, not an independently certified production deployment.
