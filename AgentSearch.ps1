#requires -Version 5.1
<#
.SYNOPSIS
Single Windows entry point for AgentSearch 1.0.0 RC3.
.DESCRIPTION
Runs the source package with Python 3.11 or newer. Setup records the package
anchor and explicitly configured search roots. Watch runs in the foreground.
The script always returns to its own package root and emits no protocol banners.
.EXAMPLE
.\AgentSearch.ps1 -Action Setup -Root 'C:\Users\jacks\PEGASUS'
.EXAMPLE
.\AgentSearch.ps1 -Action Search -Query 'checkpoint'
#>
[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Index', 'Search', 'Grep', 'Read', 'Status', 'Stdio', 'Mcp', 'Watch', 'Test', 'Verify', 'Check')]
    [string]$Action = 'Status',

    [string[]]$Root = @(),
    [string]$Query = '',
    [string]$Path = '',
    [string]$Scope = '',
    [string]$Ext = '',

    [ValidateRange(1, 200)]
    [int]$Limit = 20,
    [ValidateRange(1, 30000)]
    [int]$BudgetMs = 1000,
    [ValidateRange(1, 20)]
    [int]$PerFile = 3,
    [ValidateRange(1, 10000000)]
    [int]$StartLine = 1,
    [ValidateRange(1, 500)]
    [int]$MaxLines = 100,
    [ValidateRange(1, 64000)]
    [int]$MaxChars = 16000,
    [ValidateRange(1, 3600)]
    [int]$IntervalSeconds = 5,

    [ValidateRange(1, 100)]
    [int]$Repeat = 5,

    [switch]$Force,
    [switch]$Fresh,
    [switch]$CaseSensitive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$TaskExitCode = 0
$CanonicalRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$ConfigDirectory = Join-Path $CanonicalRoot 'config'
$StateDirectory = Join-Path $CanonicalRoot 'state'
$ConfigFile = Join-Path $ConfigDirectory 'search.json'
$DatabaseFile = Join-Path $StateDirectory 'index.sqlite3'
$RootMirrorFile = Join-Path $StateDirectory 'rootmirror.json'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

try {
    Set-Location -LiteralPath $CanonicalRoot
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $OutputEncoding = $Utf8
    if (-not [Console]::IsInputRedirected) {
        [Console]::InputEncoding = $Utf8
    }
    if (-not [Console]::IsOutputRedirected) {
        [Console]::OutputEncoding = $Utf8
    }

    foreach ($Directory in @($ConfigDirectory, $StateDirectory)) {
        if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
            [void][System.IO.Directory]::CreateDirectory($Directory)
        }
    }

    $PythonProgram = $null
    $PythonPrefix = @()
    $VersionProbe = 'import sys; sys.exit(int(sys.version_info < (3, 11)))'
    $Launcher = Get-Command 'py' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($null -ne $Launcher) {
        $ProbeOk = $false
        try {
            & $Launcher.Source '-3' '-c' $VersionProbe 2>$null
            $ProbeOk = ($LASTEXITCODE -eq 0)
        }
        catch {
            $ProbeOk = $false
        }
        if ($ProbeOk) {
            $PythonProgram = $Launcher.Source
            $PythonPrefix = @('-3')
        }
    }

    if ($null -eq $PythonProgram) {
        $PythonCandidate = Get-Command 'python' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $PythonCandidate) {
            $ProbeOk = $false
            try {
                & $PythonCandidate.Source '-c' $VersionProbe 2>$null
                $ProbeOk = ($LASTEXITCODE -eq 0)
            }
            catch {
                $ProbeOk = $false
            }
            if ($ProbeOk) {
                $PythonProgram = $PythonCandidate.Source
                $PythonPrefix = @()
            }
        }
    }

    if ($null -eq $PythonProgram) {
        throw 'Python 3.11 or newer was not found through py -3 or python. Install a suitable Python interpreter, reopen PowerShell, and run Setup again.'
    }

    if (($Action -ne 'Setup') -and ($Action -ne 'Test') -and ($Action -ne 'Verify')) {
        if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) {
            throw 'Configuration is missing. Run .\AgentSearch.ps1 -Action Setup -Root <your-project-folder> first.'
        }
        if (-not (Test-Path -LiteralPath $RootMirrorFile -PathType Leaf)) {
            throw 'RootMirror is missing. Run .\AgentSearch.ps1 -Action Setup to anchor this package.'
        }
        $RootMirror = Get-Content -LiteralPath $RootMirrorFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $RecordedRoot = [System.IO.Path]::GetFullPath([string]$RootMirror.project_root)
        $RootComparison = [System.StringComparison]::Ordinal
        if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
            $RootComparison = [System.StringComparison]::OrdinalIgnoreCase
        }
        if (-not [string]::Equals($CanonicalRoot, $RecordedRoot, $RootComparison)) {
            throw 'RootMirror does not match this package location. Run Setup again to re-anchor the moved package; supply -Root to change the indexed folders.'
        }
    }

    $CommandArguments = @('-m', 'agentsearch', '--config', $ConfigFile, '--db', $DatabaseFile)

    if ($Action -eq 'Setup') {
        $WriteConfiguration = ($Root.Count -gt 0) -or (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf))
        if ($WriteConfiguration) {
            $SetupRoots = $Root
            if ($SetupRoots.Count -eq 0) {
                $SetupRoots = @(Join-Path $CanonicalRoot 'examples')
            }
            $CommandArguments += @('config')
            foreach ($SearchRoot in $SetupRoots) {
                if ([string]::IsNullOrWhiteSpace($SearchRoot)) {
                    throw 'Each -Root value must name a directory.'
                }
                $CommandArguments += @('--root', $SearchRoot)
            }
        }
        if (-not $WriteConfiguration) {
            $CommandArguments += @('status')
        }
    }

    if ($Action -eq 'Index') {
        $CommandArguments += @('index')
        if ($Force) {
            $CommandArguments += @('--force')
        }
    }

    if (($Action -eq 'Search') -or ($Action -eq 'Grep')) {
        if ([string]::IsNullOrWhiteSpace($Query)) {
            throw 'Search and Grep require -Query with nonempty text.'
        }
        if ($Action -eq 'Search') {
            $CommandArguments += @('search')
        }
        if ($Action -eq 'Grep') {
            $CommandArguments += @('grep', '--per-file', [string]$PerFile)
            if ($Fresh) {
                $CommandArguments += @('--fresh')
            }
            if ($CaseSensitive) {
                $CommandArguments += @('--case-sensitive')
            }
        }
        $CommandArguments += @('--limit', [string]$Limit, '--budget-ms', [string]$BudgetMs)
        if (-not [string]::IsNullOrWhiteSpace($Scope)) {
            $CommandArguments += @('--scope', $Scope)
        }
        if (-not [string]::IsNullOrWhiteSpace($Ext)) {
            $CommandArguments += @('--ext', $Ext)
        }
        $CommandArguments += @('--', $Query)
    }

    if ($Action -eq 'Read') {
        if ([string]::IsNullOrWhiteSpace($Path)) {
            throw 'Read requires -Path with a file inside a configured root.'
        }
        $CommandArguments += @('read', '--start-line', [string]$StartLine, '--max-lines', [string]$MaxLines, '--max-chars', [string]$MaxChars, '--', $Path)
    }

    if ($Action -eq 'Check') {
        $CommandArguments += @('check')
    }
    if ($Action -eq 'Verify') {
        $CommandArguments = @('-m', 'agentsearch.verify', '--repeat', [string]$Repeat, '--output', (Join-Path $StateDirectory 'verification.json'))
    }
    if ($Action -eq 'Status') {
        $CommandArguments += @('status')
    }
    if ($Action -eq 'Stdio') {
        $CommandArguments += @('stdio')
    }
    if ($Action -eq 'Mcp') {
        $CommandArguments += @('mcp')
    }
    if ($Action -eq 'Watch') {
        $CommandArguments += @('watch', '--interval', [string]$IntervalSeconds)
    }
    if ($Action -eq 'Test') {
        $CommandArguments = @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
    }

    & $PythonProgram @PythonPrefix @CommandArguments
    $TaskExitCode = $LASTEXITCODE

    if (($Action -eq 'Setup') -and ($TaskExitCode -eq 0)) {
        $Mirror = [ordered]@{
            schema_version = 1
            project_root = $CanonicalRoot
            recorded_at_utc = [DateTime]::UtcNow.ToString('o')
        }
        $MirrorJson = $Mirror | ConvertTo-Json
        [System.IO.File]::WriteAllText($RootMirrorFile, $MirrorJson + [Environment]::NewLine, $Utf8)
    }
}
catch {
    [Console]::Error.WriteLine('AgentSearch: ' + $_.Exception.Message)
    $TaskExitCode = 1
}
finally {
    Set-Location -LiteralPath $CanonicalRoot
}

exit $TaskExitCode
