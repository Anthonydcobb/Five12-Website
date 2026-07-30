<#
.SYNOPSIS
    Five12 preflight doctor. Read-only. Checks the invariants that broke
    silently on 2026-07-28/29.

.DESCRIPTION
    Six faults cost a session most of a day. Not one of them printed anything:
    no error in the UI, nothing in the log, nothing at startup. The app came
    up, looked healthy, and was subtly misconfigured.

      1. A shortcut launched a stale OneDrive clone on an old branch.
      2. `flask run` without --no-reload ran two processes; both grabbed for
         the Bluetooth adapter's single-owner lock and the loser served the
         requests, reporting an empty device list.
      3. websocket-client was missing from the app's Python. The import sits
         inside a blanket `except Exception`, so a broken install looked
         exactly like an unreachable fixture.
      4. backend/.env had DB_PASS; config.py reads DB_PASSWORD.
      5. FIVE12_BLE_TOOLS / FIVE12_BLE_WRITE default off and the launcher did
         not set them.
      6. All four show NICs had drifted to the Windows "Public" category.

    Each check below maps to one of those. Every failure prints the exact
    command that fixes it.

    This script diagnoses and instructs. It never changes firewall rules,
    network categories, .env contents, or installed packages — those are the
    operator's to change.

.PARAMETER Full
    Additionally import every requirement for real, instead of reading
    installed-distribution metadata. Catches a package that is present but
    broken. Costs several seconds, so it is off by default.

.PARAMETER Detailed
    Print detail lines for passing checks too.

.PARAMETER PythonExe
    The APP interpreter. Deliberately not the one on PATH: bleak and
    websocket-client are installed only on this one, and that split is exactly
    how fault 3 stayed hidden.

.EXAMPLE
    pwsh -File scripts\doctor.ps1

.EXAMPLE
    pwsh -File scripts\doctor.ps1 -Full -Detailed

.OUTPUTS
    Exit code 1 if any check FAILed, else 0. WARN never blocks a launch.
#>
[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$Detailed,
    [int]$Port = 5000,
    [string]$PythonExe = 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe',
    [string]$ExpectedRoot = 'C:\dev\Five12-TheApp',
    # The branch everything integrates through. HEAD is compared against this as
    # well as against its own upstream, because a pushed-but-abandoned feature
    # branch matches its upstream exactly and tells you nothing.
    [string]$IntegrationRef = 'origin/main',
    # Set by start.ps1. About to launch a backend, so an EXISTING backend is a
    # conflict rather than a healthy state — the launch would create a second
    # process and the two would race for the Bluetooth adapter's single-owner
    # lock. Without this the doctor blesses the state that then breaks.
    [switch]$PreLaunch
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

$repoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Five12Doctor.psm1') -Force

$checks = @()

# ---------------------------------------------------------------------------
# Fault 1 — repo identity
# ---------------------------------------------------------------------------

$branch = ''
$dirty = $false
$originUrl = ''
try {
    # Note: do not gate these on $LASTEXITCODE. It is $null until a native
    # command has run in this session, and `$null -ne 0` is true, which
    # silently turned a healthy repo into "not a git working tree".
    $branchOut = @(& git -C $repoRoot rev-parse --abbrev-ref HEAD 2>$null)
    if ($branchOut.Count -gt 0 -and $branchOut[0]) { $branch = ([string]$branchOut[0]).Trim() }
    if ($branch) {
        $statusOut = @(& git -C $repoRoot status --porcelain 2>$null)
        $dirty = ($statusOut.Count -gt 0)
        $originOut = @(& git -C $repoRoot remote get-url origin 2>$null)
        if ($originOut.Count -gt 0 -and $originOut[0]) { $originUrl = ([string]$originOut[0]).Trim() }
    }
}
catch {
    $branch = ''
}

# Staleness from refs already on disk — no fetch. A network call on every launch
# would be wrong on an offline show rig and would blow the time budget, so the
# answer is reported with its own age instead.
$localHead = ''
$upstreamRef = ''
$behind = 0
$ahead = 0
$fetchAge = ''
$behindIntegration = 0
$integrationRefAvailable = $false
if ($branch) {
    try {
        $headOut = @(& git -C $repoRoot rev-parse --short HEAD 2>$null)
        if ($headOut.Count -gt 0) { $localHead = ([string]$headOut[0]).Trim() }

        $upOut = @(& git -C $repoRoot rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null)
        if ($upOut.Count -gt 0 -and $upOut[0]) { $upstreamRef = ([string]$upOut[0]).Trim() }

        if ($upstreamRef) {
            $countOut = @(& git -C $repoRoot rev-list --left-right --count "$upstreamRef...HEAD" 2>$null)
            if ($countOut.Count -gt 0 -and $countOut[0]) {
                $parts = ([string]$countOut[0]).Trim() -split '\s+'
                if ($parts.Count -ge 2) {
                    $behind = [int]$parts[0]
                    $ahead = [int]$parts[1]
                }
            }
        }

        # In a linked worktree `.git` is a FILE holding a gitdir: pointer, so
        # "$repoRoot\.git\FETCH_HEAD" never resolves and the age silently went
        # missing. Ask git for the path instead. FETCH_HEAD is also per-worktree
        # while remote-tracking refs are shared, so a worktree that has never
        # fetched still benefits from a fetch done in the main clone — take
        # whichever record is newer.
        $fetchCandidates = @()
        foreach ($arg in @('--git-path', '--git-common-dir')) {
            $out = @(& git -C $repoRoot rev-parse $arg $(if ($arg -eq '--git-path') { 'FETCH_HEAD' }) 2>$null)
            if ($out.Count -gt 0 -and $out[0]) {
                $p = ([string]$out[0]).Trim()
                if ($arg -eq '--git-common-dir') { $p = Join-Path $p 'FETCH_HEAD' }
                if (-not [System.IO.Path]::IsPathRooted($p)) { $p = Join-Path $repoRoot $p }
                if (Test-Path $p) { $fetchCandidates += (Get-Item $p).LastWriteTime }
            }
        }
        if ($fetchCandidates.Count -gt 0) {
            $newest = ($fetchCandidates | Sort-Object -Descending)[0]
            $span = (Get-Date) - $newest
            if ($span.TotalHours -lt 1) { $fetchAge = "$([math]::Round($span.TotalMinutes)) min" }
            elseif ($span.TotalDays -lt 1) { $fetchAge = "$([math]::Round($span.TotalHours)) h" }
            else { $fetchAge = "$([math]::Round($span.TotalDays)) days" }
        }

        # Matching your own remote copy is not the same as being current. A
        # pushed-but-abandoned feature branch matches its upstream exactly.
        if ($branch -ne 'main') {
            $intOut = @(& git -C $repoRoot rev-list --count "HEAD..$IntegrationRef" 2>$null)
            $integrationExitCode = $LASTEXITCODE
            if ($integrationExitCode -eq 0 -and $intOut.Count -gt 0 -and $intOut[0]) {
                [int]$parsedBehindIntegration = 0
                if ([int]::TryParse(([string]$intOut[0]).Trim(), [ref]$parsedBehindIntegration)) {
                    $behindIntegration = $parsedBehindIntegration
                    $integrationRefAvailable = $true
                }
            }
        }
    }
    catch { }
}

$checks += Test-Five12RepoIdentity -Root $repoRoot -ExpectedRoot $ExpectedRoot `
    -Branch $branch -Dirty $dirty -OriginUrl $originUrl `
    -LocalHead $localHead -UpstreamRef $upstreamRef -Behind $behind -Ahead $ahead `
    -FetchAge $fetchAge -IntegrationRef $IntegrationRef `
    -IntegrationRefAvailable $integrationRefAvailable -BehindIntegration $behindIntegration

# ---------------------------------------------------------------------------
# Faults 3 and 4, plus the database — all answered by the Python probe, run on
# the APP interpreter so it reports what the app itself would see
# ---------------------------------------------------------------------------

$probe = $null
if (-not (Test-Path $PythonExe)) {
    $checks += New-Five12Check -Name 'Python runtime' -Status 'FAIL' `
        -Message "app interpreter not found at $PythonExe" `
        -Fix @("Install Python 3.12 there, or re-run with -PythonExe <path>")
}
else {
    $probeArgs = @((Join-Path $PSScriptRoot 'doctor_probe.py'), '--repo-root', $repoRoot)
    if ($Full) { $probeArgs += '--full' }
    $probeJson = & $PythonExe @probeArgs 2>&1
    try {
        $probe = ($probeJson | Out-String) | ConvertFrom-Json
    }
    catch {
        $checks += New-Five12Check -Name 'Python runtime' -Status 'FAIL' `
            -Message 'the probe did not return JSON' `
            -Details @(($probeJson | Out-String).Trim()) `
            -Fix @("& '$PythonExe' '$(Join-Path $PSScriptRoot 'doctor_probe.py')' --repo-root '$repoRoot'")
    }
}

if ($null -ne $probe) {
    $checks += Test-Five12PythonPackages -Packages $probe.packages -Interpreter $PythonExe -RepoRoot $repoRoot

    # scapy needs a capture driver, and "installed" is not "working": with no
    # Npcap it imports cleanly and fails on every send, where scanner.py hides
    # the failure in log.debug. Driver presence is a file check and a service
    # query — cheap enough for the fast path.
    $npcapDll = @(
        (Join-Path $env:SystemRoot 'System32\Npcap\wpcap.dll'),   # Npcap's own directory
        (Join-Path $env:SystemRoot 'System32\wpcap.dll')          # WinPcap-compatible mode
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    $driverVersion = ''
    if ($npcapDll) {
        try { $driverVersion = [string](Get-Item $npcapDll).VersionInfo.ProductVersion } catch { $driverVersion = '' }
    }
    $npcapService = ''
    try {
        $svc = Get-Service npcap -ErrorAction SilentlyContinue
        if ($null -ne $svc) { $npcapService = [string]$svc.Status }
    }
    catch { $npcapService = '' }

    $usePcap = $null
    if ($null -ne $probe.packet_capture -and $probe.packet_capture.available) {
        $usePcap = [bool]$probe.packet_capture.use_pcap
    }

    $checks += Test-Five12PacketCapture `
        -ScapyRequired (@($probe.packages.required) -contains 'scapy') `
        -ScapyInstalled (-not (@($probe.packages.missing) -contains 'scapy')) `
        -DriverPresent ([bool]$npcapDll) `
        -ServiceStatus $npcapService `
        -DriverVersion $driverVersion `
        -UsePcap $usePcap

    $checks += Test-Five12EnvKeys -EnvReport $probe.env -RepoRoot $repoRoot
    $checks += Test-Five12Database -Database $probe.database
}

# ---------------------------------------------------------------------------
# Fault 2 — process hygiene
# ---------------------------------------------------------------------------

$portOwners = @()
try {
    $portOwners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { $_.OwningProcess })
}
catch { $portOwners = @() }

$flaskProcs = @()
try {
    $flaskProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -match 'flask\s+run' } |
            ForEach-Object {
                [pscustomobject]@{
                    ProcessId       = $_.ProcessId
                    ParentProcessId = $_.ParentProcessId
                    CommandLine     = $_.CommandLine
                }
            })
}
catch { $flaskProcs = @() }

$checks += Test-Five12FlaskProcesses -PortOwners $portOwners -FlaskProcesses $flaskProcs -Port $Port -PreLaunch:$PreLaunch

# ---------------------------------------------------------------------------
# Fault 5 — feature gates. Never guess: ask the running backend, and otherwise
# report what the launcher will set and say which source the value came from.
# ---------------------------------------------------------------------------

# "Something is listening" is not "our backend is up". Only treat the port as
# ours when its owner is one of the Flask processes we identified, or the
# feature-gate check will interrogate an unrelated service and believe its
# answer — a 404 from someone else's app would read as "Bluetooth is off".
$flaskPidSet = @($flaskProcs | ForEach-Object { $_.ProcessId })
$backendUp = @($portOwners | Where-Object { $flaskPidSet -contains $_ }).Count -gt 0
$baseUrl = "http://127.0.0.1:$Port"

$backendGates = $null
if ($backendUp) {
    try {
        # This route is registered only when ENABLE_BLE_TOOLS is on, so a 404
        # is itself the answer.
        $caps = Invoke-RestMethod -Uri "$baseUrl/api/ble/capabilities" -TimeoutSec 2 -ErrorAction Stop
        $backendGates = @{ ToolsEnabled = $true; WriteEnabled = [bool]$caps.bleWriteEnabled }
    }
    catch {
        $code = $null
        try { $code = [int]$_.Exception.Response.StatusCode } catch { $code = $null }
        if ($code -eq 404) {
            $backendGates = @{ ToolsEnabled = $false; WriteEnabled = $false }
        }
    }
}

$launcherGates = @{}
$startScript = Join-Path $repoRoot 'start.ps1'
if (Test-Path $startScript) {
    $startText = Get-Content $startScript -Raw
    foreach ($gate in @('FIVE12_BLE_TOOLS', 'FIVE12_BLE_WRITE')) {
        # start.ps1 sets these inside the nested command string it hands to the
        # backend's shell, where the sigil is backtick-escaped: `$env:NAME = '1'
        $pattern = '`?\$env:' + $gate + "\s*=\s*'([^']*)'"
        $m = [regex]::Match($startText, $pattern)
        if ($m.Success) { $launcherGates[$gate] = $m.Groups[1].Value }
    }
}

$processGates = @{}
foreach ($gate in @('FIVE12_BLE_TOOLS', 'FIVE12_BLE_WRITE')) {
    $value = [Environment]::GetEnvironmentVariable($gate)
    if ($null -ne $value -and $value -ne '') { $processGates[$gate] = $value }
}

$checks += Test-Five12FeatureGates -BackendGates $backendGates -LauncherGates $launcherGates -ProcessEnv $processGates

# ---------------------------------------------------------------------------
# Fault 6 — network. Prefer the running backend's own view of the subnets;
# fall back to the database when it is not up.
# ---------------------------------------------------------------------------

$subnets = @()
$subnetSource = 'none'
if ($backendUp) {
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/network/subnets" -TimeoutSec 2 -ErrorAction Stop
        # Never iterate the response directly — see ConvertTo-Five12SubnetList.
        $subnets = @(ConvertTo-Five12SubnetList -Response $response)
        $subnetSource = 'GET /api/network/subnets'
    }
    catch { $subnets = @() }
}
if ($subnets.Count -eq 0 -and $null -ne $probe -and $probe.subnets.ok) {
    $subnets = @($probe.subnets.subnets)
    $subnetSource = 'network_subnets table'
}

$interfaces = @()
try {
    # Which interfaces carry a default route. A show NIC has none — that is why
    # Windows cannot identify it — so this is what separates a real show NIC
    # from an internet connection that merely happens to share the address
    # range (a home router on 192.168.1.0/24 collides with Bolero exactly).
    $gatewayAliases = @()
    try {
        $gatewayAliases = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
                ForEach-Object { $_.InterfaceAlias } | Select-Object -Unique)
    }
    catch { $gatewayAliases = @() }

    $interfaces = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -ne '127.0.0.1' } |
            ForEach-Object {
                [pscustomobject]@{
                    IPAddress          = $_.IPAddress
                    PrefixLength       = $_.PrefixLength
                    InterfaceAlias     = $_.InterfaceAlias
                    HasDefaultGateway  = ($gatewayAliases -contains $_.InterfaceAlias)
                }
            })
}
catch { $interfaces = @() }

if ($subnets.Count -eq 0) {
    $checks += New-Five12Check -Name 'Network' -Status 'WARN' `
        -Message 'could not read the configured subnets' `
        -Fix @("$baseUrl/api/network/subnets   # is the backend up, and is the database reachable?")
    $showNics = @()
    $coincidentalNics = @()
}
else {
    $coverage = Test-Five12SubnetCoverage -Subnets $subnets -Interfaces $interfaces
    $coverage.Details = @("source: $subnetSource") + $coverage.Details
    $checks += $coverage
    $showNics = $coverage.ShowNics
    $coincidentalNics = $coverage.CoincidentalNics
}

$profiles = @()
try {
    $profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
            ForEach-Object {
                [pscustomobject]@{
                    InterfaceAlias  = $_.InterfaceAlias
                    NetworkCategory = [string]$_.NetworkCategory
                }
            })
}
catch { $profiles = @() }

# Is the durable fix in place? Without this the doctor cannot tell an operator
# who has already applied the policy from one who never has, and it would keep
# prescribing a fix that is already applied. A reimage silently loses it.
$policyState = 'NotSet'
$policyLocked = $false
try {
    $sigPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\CurrentVersion\NetworkList\Signatures'
    if (Test-Path $sigPath) {
        $entries = @(Get-ChildItem -Recurse $sigPath -ErrorAction SilentlyContinue | ForEach-Object {
                $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
                $category = $null
                $readOnly = $null
                if ($null -ne $props) {
                    if ($props.PSObject.Properties['Category']) { $category = $props.Category }
                    if ($props.PSObject.Properties['CategoryReadOnly']) { $readOnly = $props.CategoryReadOnly }
                }
                [pscustomobject]@{ Name = $_.PSChildName; Category = $category; CategoryReadOnly = $readOnly }
            })
        $policy = ConvertFrom-Five12NlmPolicy -Entries $entries
        $policyState = $policy.State
        $policyLocked = $policy.Locked
    }
}
catch {
    $policyState = 'NotSet'
}

$checks += Test-Five12NetworkCategories -ShowNics $showNics -Profiles $profiles `
    -UnidentifiedPolicy $policyState -PolicyLocked $policyLocked -CoincidentalNics $coincidentalNics

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

$colors = @{ 'OK' = 'Green'; 'INFO' = 'Gray'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }

Write-Host ''
Write-Host '  Five12 preflight' -ForegroundColor Cyan
Write-Host '  ───────────────────────────' -ForegroundColor DarkGray

foreach ($check in $checks) {
    $tag = $check.Status.PadRight(4)
    Write-Host "  $tag " -ForegroundColor $colors[$check.Status] -NoNewline
    Write-Host ("{0,-18} {1}" -f $check.Name, $check.Message)

    $showDetails = $Detailed -or ($check.Status -ne 'OK') -or ($check.Name -eq 'Feature gates')
    if ($showDetails) {
        foreach ($line in $check.Details) {
            if ($line) { Write-Host "         $line" -ForegroundColor DarkGray }
        }
    }
    foreach ($fix in $check.Fix) {
        if ($fix) { Write-Host "         fix: $fix" -ForegroundColor Cyan }
    }
}

$exitCode = Get-Five12ExitCode -Checks $checks
$elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)

Write-Host '  ───────────────────────────' -ForegroundColor DarkGray
if ($exitCode -eq 0) {
    Write-Host "  preflight passed in ${elapsed}s" -ForegroundColor Green
}
else {
    $failed = @($checks | Where-Object { $_.Status -eq 'FAIL' })
    Write-Host "  preflight FAILED in ${elapsed}s — $($failed.Count) check(s): $(($failed | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor Red
}
if (-not $Full) {
    Write-Host '  (-Full also imports every requirement; -Detailed shows passing detail)' -ForegroundColor DarkGray
}
Write-Host ''

exit $exitCode
