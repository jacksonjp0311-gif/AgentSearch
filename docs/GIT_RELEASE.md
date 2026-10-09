# Publication and release procedure

Canonical public repository: https://github.com/jacksonjp0311-gif/AgentSearch

Preserve the original RC3 import commit and historical documentation. Never move a published release tag. Regenerate topology and schemas, run the suite, inspect the staged scope, then seal MANIFEST.json and run sealed verification. Keep private state and credentials excluded. Verify remote HEAD equals the local commit after pushing. Inspect CI for that exact SHA before tagging an RC. Stable v1.0.0 remains gated by docs/RELEASE_GATES.md.
