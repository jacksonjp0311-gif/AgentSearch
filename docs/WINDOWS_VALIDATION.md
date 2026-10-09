# Native Windows acceptance gate

**RC4 update:** Native Windows, PowerShell 5.1/7, junction and extended-path
acceptance were executed on the target computer. See [current RC4 evidence](releases/v1.0.0-rc4.md).
The text below records the earlier Linux delivery's outstanding checks.

**Not executed on the Linux build host.** Four native-platform tests are included: Windows path handling, parent traversal, Windows PowerShell 5.1 launch, and PowerShell 7 launch. They are skipped on non-Windows systems; a missing PowerShell executable is separately reported as a skip on Windows.

## Run on the target computer

Open PowerShell in the extracted AgentSearch folder:

```powershell
.\AgentSearch.ps1 -Action Verify -Repeat 5
.\AgentSearch.ps1 -Action Setup -Root 'C:\Users\jacks\PEGASUS'
.\AgentSearch.ps1 -Action Index
.\AgentSearch.ps1 -Action Check
.\AgentSearch.ps1 -Action Grep -Query 'checkpoint' -Fresh
```

Use your actual project path. The verification receipt is `state/verification.json`. Retain the OS, Python, SQLite version, test IDs and skip reasons. The software is not Windows-validated merely because its portable tests ran on Linux.

## What the automated Windows gates do

The launcher tests copy the script and runtime into isolated temporary folders and create a Unicode/spaces fixture. They run Setup, Index, Search, Grep, Check, forced Index, and Status through the installed PowerShell executable. They do not overwrite the user's actual package configuration.

The general suite also exercises concurrent first opens, multiple reader connections, writer interruption, Unicode content, JSONL/MCP subprocess calls and release integrity on the host running it.

## Additional real-host acceptance

Check the intended NTFS directories, long paths, permissions, junctions, antivirus interaction and any cloud-synced folders separately. Confirm the selected roots and exclusions match the intended policy. Measure real project indexing and query latency rather than using the synthetic Linux measurements as Windows estimates.

The included GitHub Actions matrix is prepared for Ubuntu and Windows, Python 3.11/3.12/3.13. No remote jobs were started in this delivery. Additional Python runtimes could not be downloaded in the build container because DNS resolution failed; only Python 3.13.5 was executed here.
