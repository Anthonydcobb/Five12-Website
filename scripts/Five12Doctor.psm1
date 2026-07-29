<#
.SYNOPSIS
    Pure check logic for the Five12 preflight doctor.

.DESCRIPTION
    Every function here is a pure function of its arguments. Nothing in this
    module reads the machine, the network, or the clock, and nothing writes
    anything anywhere. `scripts/doctor.ps1` does the collecting and the
    printing; this module decides OK / WARN / FAIL.

    That split exists so the checks can be tested against synthetic inputs —
    see `scripts/tests/Five12Doctor.Tests.ps1`, which proves each check FAILS
    when its invariant is violated. A preflight check that cannot fail is
    worse than no check at all: it is a green light with nothing behind it.
    That is the lesson of fault 3 (2026-07-28), where a missing package and a
    dead fixture produced byte-identical output.

    Written for Windows PowerShell 5.1 syntax so it runs under whatever shell
    the operator happens to have.
#>

Set-StrictMode -Version 2.0

# INFO outranks OK so that an informational detail is never folded into a
# silent pass — the doctor prints detail lines for anything that is not OK.
# Only FAIL affects the exit code.
$script:StatusRank = @{ 'OK' = 0; 'INFO' = 1; 'WARN' = 2; 'FAIL' = 3 }

function New-Five12Check {
    <#
    .SYNOPSIS
        Build one check result.
    .OUTPUTS
        PSCustomObject with Name, Status ('OK'|'INFO'|'WARN'|'FAIL'), Message,
        Details (string[]), Fix (string[]).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet('OK', 'INFO', 'WARN', 'FAIL')][string]$Status,
        [Parameter(Mandatory = $true)][string]$Message,
        [string[]]$Details = @(),
        [string[]]$Fix = @()
    )
    return [pscustomobject]@{
        Name    = $Name
        Status  = $Status
        Message = $Message
        Details = @($Details)
        Fix     = @($Fix)
    }
}

function Get-Five12WorstStatus {
    <#
    .SYNOPSIS
        The most severe status in a set. 'OK' for an empty set.
    #>
    param([string[]]$Statuses)
    $worst = 'OK'
    foreach ($s in $Statuses) {
        if ($null -eq $s -or -not $script:StatusRank.ContainsKey($s)) { continue }
        if ($script:StatusRank[$s] -gt $script:StatusRank[$worst]) { $worst = $s }
    }
    return $worst
}

function Get-Five12ExitCode {
    <#
    .SYNOPSIS
        1 if any check FAILed, else 0. WARN never blocks a launch.
    #>
    param($Checks)
    foreach ($c in @($Checks)) {
        if ($c.Status -eq 'FAIL') { return 1 }
    }
    return 0
}

# ---------------------------------------------------------------------------
# IPv4 / CIDR arithmetic
# ---------------------------------------------------------------------------

function ConvertTo-Five12UInt32Address {
    <#
    .SYNOPSIS
        Dotted-quad IPv4 to UInt32. Throws on anything that is not one.
    #>
    param([Parameter(Mandatory = $true)][string]$Address)
    $parts = $Address.Trim().Split('.')
    if ($parts.Count -ne 4) { throw "Not an IPv4 address: '$Address'" }
    [uint32]$value = 0
    foreach ($p in $parts) {
        if ($p -notmatch '^\d{1,3}$') { throw "Not an IPv4 address: '$Address'" }
        $octet = [int]$p
        if ($octet -gt 255) { throw "Not an IPv4 address: '$Address'" }
        $value = ($value * 256) + $octet
    }
    return $value
}

function ConvertFrom-Five12Cidr {
    <#
    .SYNOPSIS
        'A.B.C.D/nn' to @{ Base; Prefix; Mask }.
    #>
    param([Parameter(Mandatory = $true)][string]$Cidr)
    $bits = $Cidr.Trim().Split('/')
    if ($bits.Count -ne 2) { throw "Not a CIDR block: '$Cidr'" }
    $prefix = [int]$bits[1]
    if ($prefix -lt 0 -or $prefix -gt 32) { throw "Not a CIDR block: '$Cidr'" }
    $address = ConvertTo-Five12UInt32Address -Address $bits[0]
    if ($prefix -eq 0) { [uint32]$mask = 0 } else { [uint32]$mask = [uint32]0xFFFFFFFFL -shl (32 - $prefix) }
    return [pscustomobject]@{
        Base   = [uint32]($address -band $mask)
        Prefix = $prefix
        Mask   = $mask
    }
}

function Test-Five12IpInCidr {
    <#
    .SYNOPSIS
        Is this IPv4 address inside this CIDR block?
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][string]$Cidr
    )
    $net = ConvertFrom-Five12Cidr -Cidr $Cidr
    $ip = ConvertTo-Five12UInt32Address -Address $Address
    return ([uint32]($ip -band $net.Mask) -eq $net.Base)
}

# ---------------------------------------------------------------------------
# Fault 1 — a desktop shortcut launched a stale OneDrive clone on an old branch
# ---------------------------------------------------------------------------

function Test-Five12RepoIdentity {
    <#
    .SYNOPSIS
        Is this the repo we think it is, and what state is it in?
    .PARAMETER Root
        Repo root the doctor is actually running from.
    .PARAMETER ExpectedRoot
        Canonical checkout path.
    .PARAMETER Branch
        Current branch name; empty/null means "not a git repo".
    .PARAMETER Dirty
        $true when the working tree has uncommitted changes.
    .PARAMETER OriginUrl
        `git remote get-url origin`, may be empty.
    #>
    param(
        [string]$Root,
        [string]$ExpectedRoot,
        [string]$Branch,
        [bool]$Dirty = $false,
        [string]$OriginUrl = '',
        [string]$ExpectedOriginPattern = 'Five12-Website'
    )

    $details = @()
    $fixes = @()
    $statuses = @()

    $normalize = {
        param($p)
        if ([string]::IsNullOrWhiteSpace($p)) { return '' }
        return ($p.TrimEnd('\', '/')).ToLowerInvariant()
    }
    $normRoot = & $normalize $Root
    $normExpected = & $normalize $ExpectedRoot

    if ([string]::IsNullOrWhiteSpace($Branch)) {
        $statuses += 'FAIL'
        $details += "not a git working tree: $Root"
        $fixes += "cd $ExpectedRoot"
    }
    else {
        $cleanliness = 'clean'
        if ($Dirty) { $cleanliness = 'uncommitted changes' }
        $details += "branch $Branch ($cleanliness)"
    }

    # The stale clone lived under OneDrive. A OneDrive path is never the live
    # tree, and the app ran fine from it — just without half the features.
    if ($normRoot -like '*onedrive*') {
        $statuses += 'FAIL'
        $details += "running from a OneDrive copy, which is never the live checkout"
        $fixes += "cd $ExpectedRoot   # and repoint any desktop shortcut at $ExpectedRoot\start.ps1"
    }
    elseif ($normExpected -ne '' -and $normRoot -ne $normExpected) {
        # A worktree or second clone is legitimate (coordination README allows
        # sibling worktrees), so this is a WARN that names both paths.
        $statuses += 'WARN'
        $details += "running from $Root, not the canonical $ExpectedRoot"
    }

    if ($OriginUrl -and $ExpectedOriginPattern -and ($OriginUrl -notmatch [regex]::Escape($ExpectedOriginPattern))) {
        $statuses += 'FAIL'
        $details += "origin is $OriginUrl, expected a *$ExpectedOriginPattern* remote"
        $fixes += "cd $ExpectedRoot"
    }

    if ($Dirty) {
        $statuses += 'WARN'
        $fixes += 'git status --short'
    }

    if ($Branch -eq 'main') {
        $statuses += 'WARN'
        $details += 'on main; docs/coordination/README.md rule 1 makes main integration-only'
        $fixes += 'git checkout -b <type>/<agent>/<slug>'
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    $message = "$Root"
    if ($Branch) { $message = "$Root @ $Branch" }
    return New-Five12Check -Name 'Repo identity' -Status $status -Message $message -Details $details -Fix $fixes
}

# ---------------------------------------------------------------------------
# Fault 3 — websocket-client missing from the APP runtime, swallowed by a
# blanket `except Exception`
# ---------------------------------------------------------------------------

function Test-Five12PythonPackages {
    <#
    .SYNOPSIS
        Turn the probe's package section into a check result.
    .PARAMETER Packages
        The `packages` object from scripts/doctor_probe.py.
    .PARAMETER Interpreter
        Path to the app interpreter, for the fix command.
    #>
    param(
        [Parameter(Mandatory = $true)]$Packages,
        [Parameter(Mandatory = $true)][string]$Interpreter,
        [string]$RepoRoot = '.'
    )
    $details = @()
    $fixes = @()
    $statuses = @()

    $missing = @($Packages.missing)
    $mismatched = @($Packages.mismatched)
    $importFailures = @()
    if ($null -ne $Packages.PSObject.Properties['import_failures'] -and $null -ne $Packages.import_failures) {
        $importFailures = @($Packages.import_failures)
    }

    if ($missing.Count -gt 0) {
        $statuses += 'FAIL'
        $details += "not installed: $($missing -join ', ')"
        $fixes += "& '$Interpreter' -m pip install -r '$RepoRoot\backend\requirements.txt'"
    }
    if ($importFailures.Count -gt 0) {
        $statuses += 'FAIL'
        foreach ($f in $importFailures) {
            $details += "import $($f.module) failed: $($f.error)"
        }
        $fixes += "& '$Interpreter' -m pip install --force-reinstall -r '$RepoRoot\backend\requirements.txt'"
    }
    if ($mismatched.Count -gt 0) {
        $statuses += 'WARN'
        foreach ($m in $mismatched) {
            $details += "$($m.name): pinned $($m.wanted), installed $($m.installed)"
        }
        $fixes += "& '$Interpreter' -m pip install -r '$RepoRoot\backend\requirements.txt'"
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    $message = "$($Packages.checked) requirements against the app interpreter"
    if ($missing.Count -gt 0) { $message += "; $($missing.Count) missing" }
    if ($mismatched.Count -gt 0) { $message += "; $($mismatched.Count) version drift" }
    return New-Five12Check -Name 'Python deps' -Status $status -Message $message -Details $details -Fix ($fixes | Select-Object -Unique)
}

function Test-Five12PacketCapture {
    <#
    .SYNOPSIS
        scapy needs a packet-capture driver. Installed is not the same as working.
    .DESCRIPTION
        This check exists because the dependency check alone can go green over a
        dead capability. On Windows, scapy imports perfectly well with no Npcap
        installed — metadata check passes, `--full` real-import check passes —
        and then every send and receive fails at runtime, down in
        `scanner.py` where the failure is swallowed into `log.debug`. Discovery
        quietly degrades to the OS ARP cache and nothing anywhere says so.

        That is fault 3 wearing a different hat: a check that cannot fail is a
        green light with nothing behind it.
    .PARAMETER ScapyRequired
        Is scapy in requirements.txt at all?
    .PARAMETER ScapyInstalled
        Is the distribution present on the app interpreter?
    .PARAMETER DriverPresent
        Is wpcap.dll on disk (Npcap's own directory or WinPcap-compatible mode)?
    .PARAMETER ServiceStatus
        'Running', 'Stopped', or '' when the service does not exist.
    .PARAMETER UsePcap
        scapy's own `conf.use_pcap`, from the probe under -Full. $null when not
        collected — the authoritative answer when it is.
    #>
    param(
        [bool]$ScapyRequired = $true,
        [bool]$ScapyInstalled = $true,
        [bool]$DriverPresent = $false,
        [string]$ServiceStatus = '',
        [string]$DriverVersion = '',
        $UsePcap = $null
    )

    if (-not $ScapyRequired) {
        return New-Five12Check -Name 'Packet capture' -Status 'INFO' `
            -Message 'scapy is not a requirement of this app'
    }
    if (-not $ScapyInstalled) {
        # The Python deps check already FAILs on this. Say why it matters here
        # rather than failing the same fact twice.
        return New-Five12Check -Name 'Packet capture' -Status 'INFO' `
            -Message 'scapy is not installed — see the Python deps line' `
            -Details @('without it the active ARP sweep degrades to the OS ARP cache, silently')
    }

    $details = @()
    $fixes = @()
    $statuses = @()

    if (-not $DriverPresent) {
        $statuses += 'FAIL'
        $details += 'scapy is installed but there is no packet-capture driver (Npcap) — it will import cleanly and then fail on every send'
        $details += 'scanner.py swallows that failure into log.debug, so discovery silently falls back to the OS ARP cache'
        $fixes += 'Install Npcap from https://npcap.com (needs Administrator; tick "WinPcap API-compatible mode" if anything else on this rig wants it)'
    }
    else {
        # Label this as the wpcap.dll file version, not the Npcap product
        # version — Npcap ships a wpcap.dll versioned after the WinPcap API it
        # emulates (1.10.6 on Npcap 1.88), and reading it as "Npcap 1.10" would
        # send someone chasing a downgrade that never happened.
        $version = 'version unreadable'
        if ($DriverVersion) { $version = "wpcap.dll $DriverVersion" }
        $details += "capture driver present ($version)"

        if ($ServiceStatus -eq '') {
            $statuses += 'WARN'
            $details += 'the npcap service does not exist, though the driver is on disk'
            $fixes += 'Reinstall Npcap from https://npcap.com (needs Administrator)'
        }
        elseif ($ServiceStatus -ne 'Running') {
            $statuses += 'FAIL'
            $details += "the npcap service is $ServiceStatus"
            $fixes += 'Start-Service npcap   # run as Administrator'
        }
    }

    if ($null -ne $UsePcap) {
        # -Full asked scapy directly, which outranks anything inferred from the
        # filesystem.
        if ($UsePcap) {
            $details += 'scapy reports conf.use_pcap = True (asked directly, -Full)'
        }
        else {
            $statuses += 'FAIL'
            $details += 'scapy reports conf.use_pcap = False — it has no capture provider regardless of what is on disk'
            $fixes += 'Install or repair Npcap from https://npcap.com (needs Administrator)'
        }
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    $message = 'scapy has a capture driver'
    if ($status -eq 'FAIL') { $message = 'scapy cannot capture packets' }
    return New-Five12Check -Name 'Packet capture' -Status $status -Message $message -Details $details -Fix $fixes
}

# ---------------------------------------------------------------------------
# Fault 4 — backend/.env had DB_PASS while config.py reads DB_PASSWORD
# ---------------------------------------------------------------------------

function Test-Five12EnvKeys {
    <#
    .SYNOPSIS
        Turn the probe's env section into a check result.
    .DESCRIPTION
        The key list is derived from config.py by the probe, never hardcoded.
        Values never appear — presence and length only.
    #>
    param(
        [Parameter(Mandatory = $true)]$EnvReport,
        [string]$RepoRoot = '.'
    )
    $details = @()
    $fixes = @()
    $statuses = @()

    if (-not $EnvReport.env_file_exists) {
        return New-Five12Check -Name '.env completeness' -Status 'FAIL' `
            -Message "backend\.env is missing" `
            -Fix @("Copy-Item '$RepoRoot\.env.example' '$RepoRoot\backend\.env'  # then fill in the values")
    }

    $missingRequired = @($EnvReport.missing_required)
    $unreferenced = @($EnvReport.unreferenced_in_env_file)
    $fromProcess = @($EnvReport.from_process_env)
    $present = @($EnvReport.present)

    if ($missingRequired.Count -gt 0) {
        $statuses += 'FAIL'
        foreach ($k in $missingRequired) {
            $details += "config.py reads $k and it has no default; backend\.env does not set it"
            $fixes += "Add $k=<value> to $RepoRoot\backend\.env   # see .env.example"
        }
    }
    if ($unreferenced.Count -gt 0) {
        # This is the shape of fault 4 from the other side: DB_PASS sitting in
        # .env that nothing reads, while the key that IS read is absent.
        $statuses += 'WARN'
        $details += "set in backend\.env but read nowhere in backend/: $($unreferenced -join ', ') — renamed or misspelled?"
    }
    foreach ($p in $fromProcess) {
        $details += "$($p.key): supplied by the process environment, not backend\.env (length $($p.length))"
    }
    foreach ($p in $present) {
        $details += "$($p.key): present, length $($p.length)"
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    $keyCount = ($EnvReport.config_keys.PSObject.Properties | Measure-Object).Count
    $defaulted = $keyCount - $present.Count - $fromProcess.Count
    $message = "config.py reads $keyCount keys: $($present.Count) from backend\.env, $defaulted using config.py defaults"
    if ($fromProcess.Count -gt 0) {
        $message += ", $($fromProcess.Count) from the environment"
    }
    if ($missingRequired.Count -gt 0) {
        $message = "$($missingRequired.Count) required key(s) missing from backend\.env"
    }
    return New-Five12Check -Name '.env completeness' -Status $status -Message $message -Details $details -Fix $fixes
}

function Test-Five12Database {
    <#
    .SYNOPSIS
        Turn the probe's database section into a check result.
    #>
    param([Parameter(Mandatory = $true)]$Database)

    if ($Database.ok) {
        return New-Five12Check -Name 'Database' -Status 'OK' `
            -Message "connected to '$($Database.database)' on $($Database.host) as $($Database.user) (MySQL $($Database.server_version))"
    }
    return New-Five12Check -Name 'Database' -Status 'FAIL' `
        -Message "cannot connect to '$($Database.host)' as $($Database.user)" `
        -Details @($Database.error) `
        -Fix @(
        'Get-Service MySQL* | Select-Object Name,Status',
        'Verify DB_HOST / DB_USER / DB_PASSWORD / DB_NAME in backend\.env — the key names, not just the values'
    )
}

# ---------------------------------------------------------------------------
# Fault 2 — `flask run` without --no-reload runs TWO processes; both grab for
# the Bluetooth adapter's single-owner lock and the loser serves the requests
# ---------------------------------------------------------------------------

function Test-Five12FlaskProcesses {
    <#
    .SYNOPSIS
        Exactly zero or one Flask backend, and it must not be running the reloader.
    .PARAMETER PortOwners
        PIDs listening on the backend port.
    .PARAMETER FlaskProcesses
        Objects with ProcessId, ParentProcessId, CommandLine.
    .NOTES
        Counting port owners alone cannot catch fault 2: under Werkzeug's
        reloader only the child binds the socket, so the port reports exactly
        one owner in the broken state. The command line is the real evidence.
    #>
    param(
        $PortOwners = @(),
        $FlaskProcesses = @(),
        [int]$Port = 5000
    )
    $details = @()
    $fixes = @()
    $statuses = @()

    $owners = @($PortOwners | Where-Object { $null -ne $_ } | Select-Object -Unique)
    $procs = @($FlaskProcesses)

    if ($owners.Count -gt 1) {
        $statuses += 'FAIL'
        $details += "$($owners.Count) processes are bound to port $Port (PIDs $($owners -join ', '))"
        foreach ($o in $owners) { $fixes += "Stop-Process -Id $o" }
    }

    if ($procs.Count -gt 1) {
        $statuses += 'FAIL'
        $ids = @($procs | ForEach-Object { $_.ProcessId })
        $children = @($procs | Where-Object { $ids -contains $_.ParentProcessId })
        if ($children.Count -gt 0) {
            $details += "$($procs.Count) flask processes and one is the child of another — this is the auto-reloader, and both halves fight over the Bluetooth adapter's single-owner lock"
        }
        else {
            $details += "$($procs.Count) independent flask processes are running (PIDs $($ids -join ', '))"
        }
        foreach ($p in $procs) { $fixes += "Stop-Process -Id $($p.ProcessId)" }
        $fixes += 'Relaunch with: python -m flask run --port 5000 --no-reload'
    }

    foreach ($p in $procs) {
        if ($p.CommandLine -and ($p.CommandLine -notmatch '--no-reload')) {
            $statuses += 'FAIL'
            $details += "PID $($p.ProcessId) is running flask without --no-reload"
            $fixes += "Stop-Process -Id $($p.ProcessId)"
            $fixes += 'Relaunch with: python -m flask run --port 5000 --no-reload'
        }
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    $message = "$($procs.Count) flask process(es), $($owners.Count) bound to port $Port"
    if ($procs.Count -eq 0 -and $owners.Count -eq 0) {
        $message = "no backend running yet on port $Port"
    }
    return New-Five12Check -Name 'Process hygiene' -Status $status -Message $message -Details $details -Fix ($fixes | Select-Object -Unique)
}

# ---------------------------------------------------------------------------
# Fault 5 — FIVE12_BLE_TOOLS / FIVE12_BLE_WRITE default off and the launcher
# did not set them, so the panel said "Bluetooth tools are switched off"
# ---------------------------------------------------------------------------

function Test-Five12FeatureGates {
    <#
    .SYNOPSIS
        State the actual value of each gate and say where the value came from.
    .PARAMETER BackendGates
        $null when the backend is not reachable. Otherwise
        @{ ToolsEnabled = $bool; WriteEnabled = $bool } read from
        GET /api/ble/capabilities — that route only exists when the tools gate
        is on, so a 404 is itself an answer.
    .PARAMETER LauncherGates
        What start.ps1 will set for the backend it spawns, e.g.
        @{ FIVE12_BLE_TOOLS = '1'; FIVE12_BLE_WRITE = '1' }.
    .PARAMETER ProcessEnv
        The doctor's own environment, e.g. @{ FIVE12_BLE_TOOLS = '0' }.
    .NOTES
        Never guess. Every line says which source it came from.
    #>
    param(
        $BackendGates = $null,
        $LauncherGates = @{},
        $ProcessEnv = @{}
    )
    $details = @()
    $fixes = @()
    $statuses = @()

    $names = @('FIVE12_BLE_TOOLS', 'FIVE12_BLE_WRITE')

    if ($null -ne $BackendGates) {
        $toolsOn = [bool]$BackendGates.ToolsEnabled
        $writeOn = [bool]$BackendGates.WriteEnabled
        $onOff = { param($b) if ($b) { 'ON' } else { 'OFF' } }
        $details += "FIVE12_BLE_TOOLS = $(& $onOff $toolsOn)  (running backend, GET /api/ble/capabilities)"
        $details += "FIVE12_BLE_WRITE = $(& $onOff $writeOn)  (running backend, GET /api/ble/capabilities)"
        if (-not $toolsOn) {
            $statuses += 'WARN'
            $details += 'the running backend has Bluetooth off; the Cintennas tab will report "Bluetooth tools are switched off"'
            $fixes += 'Restart the backend through start.ps1, which sets both gates'
        }
        elseif (-not $writeOn) {
            $statuses += 'WARN'
            $details += 'discovery is on but writes are off: mode switch, Link and Unlink will not be offered'
            $fixes += "`$env:FIVE12_BLE_WRITE = '1'   # then restart the backend"
        }
    }
    else {
        $details += 'no backend reachable — reporting what the next launch will use'
        foreach ($n in $names) {
            $launcher = $null
            if ($LauncherGates -and $LauncherGates.ContainsKey($n)) { $launcher = $LauncherGates[$n] }
            $shell = $null
            if ($ProcessEnv -and $ProcessEnv.ContainsKey($n)) { $shell = $ProcessEnv[$n] }

            if ($null -ne $launcher) {
                $state = 'OFF'
                if ($launcher -eq '1') { $state = 'ON' }
                $details += "$n = $state  (start.ps1 sets '$launcher' for the backend it spawns)"
                if ($launcher -ne '1') {
                    $statuses += 'WARN'
                    $fixes += "Set `$env:$n = '1' in start.ps1 before the backend launches"
                }
            }
            elseif ($null -ne $shell) {
                $state = 'OFF'
                if ($shell -eq '1') { $state = 'ON' }
                $details += "$n = $state  (this shell's environment: '$shell')"
                if ($shell -ne '1') { $statuses += 'WARN' }
            }
            else {
                $statuses += 'WARN'
                $details += "$n = OFF  (unset anywhere; config.py defaults it to '0')"
                $fixes += "Set `$env:$n = '1' in start.ps1 before the backend launches"
            }
        }
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    return New-Five12Check -Name 'Feature gates' -Status $status -Message 'Bluetooth gates' -Details $details -Fix ($fixes | Select-Object -Unique)
}

# ---------------------------------------------------------------------------
# Fault 6 — all four show NICs drifted to the Windows "Public" category, which
# blocks inbound traffic and broke Hog console show networking
# ---------------------------------------------------------------------------

function Test-Five12SubnetCoverage {
    <#
    .SYNOPSIS
        Every configured subnet needs a local interface inside it at the right
        prefix length.
    .PARAMETER Subnets
        Objects with label, cidr, active, ignoreCidrs.
    .PARAMETER Interfaces
        Objects with IPAddress, PrefixLength, InterfaceAlias.
    .OUTPUTS
        A check result whose ShowNics property lists the interfaces that back a
        configured subnet — the "show NICs" the category check then inspects.
    .NOTES
        Prefix length is part of the match on purpose. The venue Wi-Fi sits at
        172.16.10.228/23 inside the Management 172.16.0.0/16 subnet; matching
        on containment alone would call the venue Wi-Fi a show NIC and demand
        it be made Private. Anything listed in the subnet's ignoreCidrs is
        excluded outright.
    #>
    param(
        $Subnets = @(),
        $Interfaces = @()
    )
    $details = @()
    $fixes = @()
    $statuses = @()
    $showNics = @()

    $active = @($Subnets | Where-Object { $_.active })
    if ($active.Count -eq 0) {
        return New-Five12Check -Name 'Network' -Status 'WARN' -Message 'no active subnets configured' |
            Add-Member -NotePropertyName ShowNics -NotePropertyValue @() -PassThru
    }

    foreach ($subnet in $active) {
        $ignore = @()
        if ($subnet.ignoreCidrs) {
            $ignore = @($subnet.ignoreCidrs.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        $wantedPrefix = (ConvertFrom-Five12Cidr -Cidr $subnet.cidr).Prefix

        $exact = @()
        $wrongPrefix = @()
        foreach ($iface in @($Interfaces)) {
            $inside = $false
            try { $inside = Test-Five12IpInCidr -Address $iface.IPAddress -Cidr $subnet.cidr } catch { $inside = $false }
            if (-not $inside) { continue }

            $ignored = $false
            foreach ($ig in $ignore) {
                try { if (Test-Five12IpInCidr -Address $iface.IPAddress -Cidr $ig) { $ignored = $true } } catch { }
            }
            if ($ignored) { continue }

            if ([int]$iface.PrefixLength -eq $wantedPrefix) { $exact += $iface }
            else { $wrongPrefix += $iface }
        }

        if ($exact.Count -gt 0) {
            foreach ($i in $exact) {
                $details += "$($subnet.label) $($subnet.cidr) -> $($i.InterfaceAlias) $($i.IPAddress)/$($i.PrefixLength)"
                $showNics += $i
            }
        }
        elseif ($wrongPrefix.Count -gt 0) {
            # Drift, not absence: the interface is on the network but with the
            # wrong mask, so parts of the subnet are unreachable.
            $statuses += 'FAIL'
            foreach ($i in $wrongPrefix) {
                $details += "$($subnet.label) $($subnet.cidr) -> $($i.InterfaceAlias) $($i.IPAddress)/$($i.PrefixLength) has the WRONG prefix (want /$wantedPrefix)"
                $fixes += "netsh interface ipv4 set address name=`"$($i.InterfaceAlias)`" static $($i.IPAddress) $(ConvertTo-Five12MaskString -Prefix $wantedPrefix)"
            }
        }
        else {
            # Off-site the show NICs are legitimately unplugged, so this is a
            # WARN. A doctor that blocks every at-home launch gets switched off.
            $statuses += 'WARN'
            $details += "$($subnet.label) $($subnet.cidr) -> no local interface"
            $fixes += "Get-NetIPAddress -AddressFamily IPv4 | Where-Object InterfaceAlias -eq '$($subnet.label)'   # is the NIC up and addressed?"
        }
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    $message = "$($active.Count) configured subnets, $($showNics.Count) backed by a local interface"
    $check = New-Five12Check -Name 'Network' -Status $status -Message $message -Details $details -Fix ($fixes | Select-Object -Unique)
    return ($check | Add-Member -NotePropertyName ShowNics -NotePropertyValue $showNics -PassThru)
}

function ConvertTo-Five12MaskString {
    <#
    .SYNOPSIS
        Prefix length to dotted-quad mask, for netsh fix commands.
    #>
    param([Parameter(Mandatory = $true)][int]$Prefix)
    if ($Prefix -lt 0 -or $Prefix -gt 32) { throw "Not a prefix length: $Prefix" }
    if ($Prefix -eq 0) { [uint32]$mask = 0 } else { [uint32]$mask = [uint32]0xFFFFFFFFL -shl (32 - $Prefix) }
    $octets = @(
        ($mask -shr 24) -band 255
        ($mask -shr 16) -band 255
        ($mask -shr 8) -band 255
        $mask -band 255
    )
    return ($octets -join '.')
}

function Test-Five12NetworkCategories {
    <#
    .SYNOPSIS
        No show NIC may sit in the Windows "Public" category.
    .PARAMETER ShowNics
        Interfaces backing a configured subnet (from Test-Five12SubnetCoverage).
    .PARAMETER Profiles
        Objects with InterfaceAlias and NetworkCategory.
    .NOTES
        Public blocks inbound traffic. On 2026-07-29 all four show NICs had
        drifted to Public and Hog console show networking stopped working with
        no error anywhere. The doctor reports it and prints the fix; changing a
        Windows network category is the operator's call, never the script's.
    #>
    param(
        $ShowNics = @(),
        $Profiles = @()
    )
    $details = @()
    $fixes = @()
    $statuses = @()

    $aliases = @(@($ShowNics) | ForEach-Object { $_.InterfaceAlias } | Select-Object -Unique)
    if ($aliases.Count -eq 0) {
        return New-Five12Check -Name 'Network category' -Status 'INFO' -Message 'no show NICs to inspect'
    }

    foreach ($alias in $aliases) {
        $connProfile = @($Profiles | Where-Object { $_.InterfaceAlias -eq $alias }) | Select-Object -First 1
        if ($null -eq $connProfile) {
            # Windows only hands out a profile for a connected network, so a
            # missing one means disconnected or unidentified — not Public, and
            # not fault 6. Say so and move on rather than crying wolf on every
            # launch; an unreachable subnet is already the Network check's job.
            $statuses += 'INFO'
            $details += "$alias : no connection profile (disconnected or unidentified network)"
            continue
        }
        $category = [string]$connProfile.NetworkCategory
        if ($category -eq 'Public') {
            $statuses += 'FAIL'
            $details += "$alias : Public — inbound traffic is blocked, show networking will fail silently"
            $fixes += "Set-NetConnectionProfile -InterfaceAlias '$alias' -NetworkCategory Private   # run as Administrator"
        }
        else {
            $details += "$alias : $category"
        }
    }

    $status = Get-Five12WorstStatus -Statuses $statuses
    return New-Five12Check -Name 'Network category' -Status $status -Message "$($aliases.Count) show NIC(s)" -Details $details -Fix $fixes
}

Export-ModuleMember -Function @(
    'New-Five12Check',
    'Get-Five12WorstStatus',
    'Get-Five12ExitCode',
    'ConvertTo-Five12UInt32Address',
    'ConvertFrom-Five12Cidr',
    'ConvertTo-Five12MaskString',
    'Test-Five12IpInCidr',
    'Test-Five12RepoIdentity',
    'Test-Five12PythonPackages',
    'Test-Five12PacketCapture',
    'Test-Five12EnvKeys',
    'Test-Five12Database',
    'Test-Five12FlaskProcesses',
    'Test-Five12FeatureGates',
    'Test-Five12SubnetCoverage',
    'Test-Five12NetworkCategories'
)
