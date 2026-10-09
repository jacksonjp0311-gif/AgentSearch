# AgentSearch engineering review — v0.1.1

## Strengths
- Separated index, bounded retrieval, and agent transports.
- Explicit roots and index persistence.
- JSON output with query completeness and freshness indicators.

## Critical gaps
1. No completed native Windows/PowerShell acceptance test in this environment.
2. Fuzzy and short-pattern fallback latency is high on the recorded synthetic corpus.
3. Polling-based change detection scales with filesystem traversal.
4. No independently verified task-level model token or accuracy improvements.
5. No comprehensive adversarial-input/security review.
6. Retrieved text can contain malicious agent instructions; never promote to authority.

## Verification gates
- Run Windows test suite and PowerShell smoke tests with Unicode and long NTFS paths.
- Fuzz malformed protocol input, symlink escapes, unexpected encodings and oversized files.
- Stress concurrent indexing, reads and interrupted processes.
- Benchmark real repos at 10k, 100k and 1M files.
- A/B test same model/tasks with and without retrieval; track accuracy, recall, latency, tokens and cost.

## Recommendation
Preserve the stable agent contract. Fix correctness and native Windows readiness first, then optimize the slow query paths. Add Rust only after measuring bottlenecks.
