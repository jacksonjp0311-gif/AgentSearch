# Git release checklist

Release candidate prepared for a **new Git repository**. No remote is configured and no push was made.

1. Run `python -m unittest discover -s tests -q`.
2. On Windows, run `./AgentSearch.ps1 -Action Verify -Repeat 5` and Windows-specific acceptance tests.
3. Inspect `.gitignore` and ensure no secrets, personal config, or state are staged.
4. Create an empty GitHub repository, then from this directory run:

```bash
git init
git branch -M main
git add .
git status --short
git commit -m "release: AgentSearch 1.0.0 RC2"
git remote add origin https://github.com/YOUR_ACCOUNT/AgentSearch.git
git push -u origin main
```

Replace `YOUR_ACCOUNT`. Tag stable `v1.0.0` only after native Windows, concurrency, crash recovery, security, and real harness integration gates pass.
