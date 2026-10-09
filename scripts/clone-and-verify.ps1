#requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RepositoryUrl,[string]$Destination='AgentSearch')
$ErrorActionPreference='Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }
if (Test-Path -LiteralPath $Destination) { throw "Destination exists: $Destination" }
& git clone -- $RepositoryUrl $Destination
if ($LASTEXITCODE -ne 0) { throw 'Clone failed.' }
Push-Location -LiteralPath $Destination
try {
    & git status --short
    & .\AgentSearch.ps1 -Action Test
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    Write-Host 'Clone and portable tests completed. Configure roots before indexing.'
} finally { Pop-Location }
