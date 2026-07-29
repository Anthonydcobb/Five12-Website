<#
.SYNOPSIS
    Run the doctor's Pester tests.

.DESCRIPTION
    Pester on this rig is 3.4.0 — the version Windows bundles — so the tests
    use Pester 3/4 assertion syntax (`Should Be`). Pester 5 removed that
    syntax, so this runner pins the module version and fails loudly rather
    than letting a version mismatch look like a passing run.

    Exits non-zero if any test fails.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$available = Get-Module -ListAvailable Pester |
    Where-Object { $_.Version -lt [version]'5.0.0' } |
    Sort-Object Version -Descending |
    Select-Object -First 1

if ($null -eq $available) {
    Write-Host "No Pester 3.x/4.x found. These tests use legacy 'Should Be' syntax." -ForegroundColor Red
    Write-Host "Installed Pester versions:" -ForegroundColor Yellow
    Get-Module -ListAvailable Pester | Select-Object Name, Version | Format-Table | Out-Host
    Write-Host "Fix: Install-Module Pester -RequiredVersion 4.10.1 -Scope CurrentUser -SkipPublisherCheck" -ForegroundColor Yellow
    exit 2
}

Import-Module $available.Path -Force
Write-Host "Pester $($available.Version)" -ForegroundColor DarkGray

$testFile = Join-Path $PSScriptRoot 'Five12Doctor.Tests.ps1'
$result = Invoke-Pester -Script $testFile -PassThru

if ($result.FailedCount -gt 0) { exit 1 }
exit 0
