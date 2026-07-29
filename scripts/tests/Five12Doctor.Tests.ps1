<#
    Tests for the preflight doctor's check logic.

    The point of these is narrow and specific: prove that every check FAILS
    when its invariant is violated. On 2026-07-28 a missing package and an
    unreachable fixture produced identical output — an empty grid and no error
    — which is how three hours went. A check that cannot fail is a green light
    with nothing behind it.

    Pester on this rig is 3.4.0 (the version Windows ships), so this file uses
    Pester 3/4 assertion syntax (`Should Be`, not `Should -Be`).

    Run:  pwsh -File scripts\tests\Run-DoctorTests.ps1
#>

$modulePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'Five12Doctor.psm1'
Remove-Module Five12Doctor -Force -ErrorAction SilentlyContinue
Import-Module $modulePath -Force

Describe 'IPv4 and CIDR arithmetic' {

    It 'places an address inside its own block' {
        (Test-Five12IpInCidr -Address '172.31.0.220' -Cidr '172.31.0.0/16') | Should Be $true
    }

    It 'keeps an address outside a neighbouring block' {
        (Test-Five12IpInCidr -Address '172.30.192.1' -Cidr '172.31.0.0/16') | Should Be $false
    }

    It 'handles the sACN /8 that overlaps several interfaces' {
        (Test-Five12IpInCidr -Address '10.220.220.220' -Cidr '10.0.0.0/8') | Should Be $true
        (Test-Five12IpInCidr -Address '10.0.0.1' -Cidr '10.0.0.0/8') | Should Be $true
    }

    It 'rejects a non-address rather than silently returning false' {
        # `Should Throw` with no argument is broken in Pester 3.4.0 under
        # PowerShell 7 — even `{ throw 'x' } | Should Throw` reports no
        # exception. The message form works, so use it.
        { ConvertTo-Five12UInt32Address -Address 'not-an-ip' } | Should Throw 'Not an IPv4 address'
        { ConvertTo-Five12UInt32Address -Address '999.1.1.1' } | Should Throw 'Not an IPv4 address'
        { ConvertFrom-Five12Cidr -Cidr '172.31.0.0' } | Should Throw 'Not a CIDR block'
    }

    It 'converts prefix lengths to netsh masks' {
        (ConvertTo-Five12MaskString -Prefix 16) | Should Be '255.255.0.0'
        (ConvertTo-Five12MaskString -Prefix 24) | Should Be '255.255.255.0'
        (ConvertTo-Five12MaskString -Prefix 8)  | Should Be '255.0.0.0'
    }
}

Describe 'Fault 1 - repo identity' {

    It 'passes on the canonical checkout, clean, on a feature branch' {
        $r = Test-Five12RepoIdentity -Root 'C:\dev\Five12-TheApp' -ExpectedRoot 'C:\dev\Five12-TheApp' `
            -Branch 'feat/claude/preflight-doctor' -Dirty $false `
            -OriginUrl 'https://github.com/Anthonydcobb/Five12-Website.git'
        $r.Status | Should Be 'OK'
    }

    It 'FAILS when launched from the stale OneDrive clone' {
        $r = Test-Five12RepoIdentity -Root 'C:\Users\antho\OneDrive\Documents\Five12-TheApp' `
            -ExpectedRoot 'C:\dev\Five12-TheApp' -Branch 'feature/old-branch' -Dirty $false `
            -OriginUrl 'https://github.com/Anthonydcobb/Five12-Website.git'
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'OneDrive'
        ($r.Fix -join ' ') | Should Match 'C:\\dev\\Five12-TheApp'
    }

    It 'FAILS when the directory is not a git working tree' {
        $r = Test-Five12RepoIdentity -Root 'C:\dev\Five12-TheApp' -ExpectedRoot 'C:\dev\Five12-TheApp' `
            -Branch '' -Dirty $false -OriginUrl ''
        $r.Status | Should Be 'FAIL'
    }

    It 'FAILS when origin points at some other repository' {
        $r = Test-Five12RepoIdentity -Root 'C:\dev\Five12-TheApp' -ExpectedRoot 'C:\dev\Five12-TheApp' `
            -Branch 'main' -Dirty $false -OriginUrl 'https://github.com/someone/other-project.git'
        $r.Status | Should Be 'FAIL'
    }

    It 'WARNs on main, because main is integration-only' {
        $r = Test-Five12RepoIdentity -Root 'C:\dev\Five12-TheApp' -ExpectedRoot 'C:\dev\Five12-TheApp' `
            -Branch 'main' -Dirty $false -OriginUrl 'https://github.com/Anthonydcobb/Five12-Website.git'
        $r.Status | Should Be 'WARN'
    }

    It 'WARNs, not FAILs, from a sibling worktree' {
        $r = Test-Five12RepoIdentity -Root 'C:\dev\Five12-worktrees\hermes-thing' `
            -ExpectedRoot 'C:\dev\Five12-TheApp' -Branch 'fix/hermes/thing' -Dirty $false `
            -OriginUrl 'https://github.com/Anthonydcobb/Five12-Website.git'
        $r.Status | Should Be 'WARN'
    }

    It 'reports the branch and whether the tree is clean' {
        $r = Test-Five12RepoIdentity -Root 'C:\dev\Five12-TheApp' -ExpectedRoot 'C:\dev\Five12-TheApp' `
            -Branch 'feat/x' -Dirty $true -OriginUrl 'https://github.com/Anthonydcobb/Five12-Website.git'
        $r.Status | Should Be 'WARN'
        ($r.Details -join ' ') | Should Match 'uncommitted changes'
    }
}

Describe 'Fault 3 - python deps on the app interpreter' {

    $appPython = 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe'

    It 'passes when every requirement is installed at the pinned version' {
        $packages = [pscustomobject]@{
            missing = @(); mismatched = @(); checked = 35; import_failures = $null
        }
        $r = Test-Five12PythonPackages -Packages $packages -Interpreter $appPython
        $r.Status | Should Be 'OK'
    }

    It 'FAILS when websocket-client is missing - the exact fault 3 shape' {
        $packages = [pscustomobject]@{
            missing = @('websocket-client'); mismatched = @(); checked = 35; import_failures = $null
        }
        $r = Test-Five12PythonPackages -Packages $packages -Interpreter $appPython
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'websocket-client'
    }

    It 'names the app interpreter in the fix, not whatever is on PATH' {
        $packages = [pscustomobject]@{
            missing = @('bleak'); mismatched = @(); checked = 35; import_failures = $null
        }
        $r = Test-Five12PythonPackages -Packages $packages -Interpreter $appPython -RepoRoot 'C:\dev\Five12-TheApp'
        ($r.Fix -join ' ') | Should Match 'Python312'
        ($r.Fix -join ' ') | Should Match 'requirements.txt'
    }

    It 'FAILS when a package is installed but will not import (--Full)' {
        $packages = [pscustomobject]@{
            missing         = @()
            mismatched      = @()
            checked         = 35
            import_failures = @([pscustomobject]@{
                    name = 'bleak'; module = 'bleak'; error = 'ImportError: DLL load failed'
                })
        }
        $r = Test-Five12PythonPackages -Packages $packages -Interpreter $appPython
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'DLL load failed'
    }

    It 'WARNs on version drift without blocking the launch' {
        $packages = [pscustomobject]@{
            missing         = @()
            mismatched      = @([pscustomobject]@{ name = 'Flask'; wanted = '3.1.1'; installed = '3.1.0' })
            checked         = 35
            import_failures = $null
        }
        $r = Test-Five12PythonPackages -Packages $packages -Interpreter $appPython
        $r.Status | Should Be 'WARN'
    }
}

Describe 'Packet capture - installed is not the same as working' {

    It 'passes when scapy is installed and the Npcap service is running' {
        $r = Test-Five12PacketCapture -ScapyRequired $true -ScapyInstalled $true `
            -DriverPresent $true -ServiceStatus 'Running' -DriverVersion '1.88'
        $r.Status | Should Be 'OK'
        ($r.Details -join ' ') | Should Match '1.88'
    }

    It 'FAILS when scapy is installed but no capture driver exists' {
        # The false green this check exists for: metadata says installed,
        # `--full` imports it fine, and every packet send still fails.
        $r = Test-Five12PacketCapture -ScapyRequired $true -ScapyInstalled $true `
            -DriverPresent $false -ServiceStatus ''
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'import cleanly and then fail'
        ($r.Fix -join ' ') | Should Match 'npcap.com'
    }

    It 'FAILS when the driver is installed but its service is stopped' {
        $r = Test-Five12PacketCapture -ScapyRequired $true -ScapyInstalled $true `
            -DriverPresent $true -ServiceStatus 'Stopped' -DriverVersion '1.88'
        $r.Status | Should Be 'FAIL'
        ($r.Fix -join ' ') | Should Match 'Start-Service npcap'
    }

    It 'FAILS when scapy itself reports no capture provider, whatever is on disk' {
        # -Full asks scapy directly, and scapy outranks the filesystem.
        $r = Test-Five12PacketCapture -ScapyRequired $true -ScapyInstalled $true `
            -DriverPresent $true -ServiceStatus 'Running' -UsePcap $false
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'conf.use_pcap = False'
    }

    It 'records the direct answer from scapy when it is affirmative' {
        $r = Test-Five12PacketCapture -ScapyRequired $true -ScapyInstalled $true `
            -DriverPresent $true -ServiceStatus 'Running' -UsePcap $true
        $r.Status | Should Be 'OK'
        ($r.Details -join ' ') | Should Match 'conf.use_pcap = True'
    }

    It 'does not double-FAIL when scapy is simply not installed' {
        # The Python deps check already owns that failure.
        $r = Test-Five12PacketCapture -ScapyRequired $true -ScapyInstalled $false `
            -DriverPresent $false -ServiceStatus ''
        $r.Status | Should Be 'INFO'
        ($r.Details -join ' ') | Should Match 'ARP cache'
    }

    It 'stays quiet when scapy is not a requirement of the app' {
        $r = Test-Five12PacketCapture -ScapyRequired $false -ScapyInstalled $false `
            -DriverPresent $false -ServiceStatus ''
        $r.Status | Should Be 'INFO'
    }
}

Describe 'Fault 4 - .env completeness' {

    It 'passes when every key config.py reads is present' {
        $envSection = [pscustomobject]@{
            env_file_exists           = $true
            missing_required          = @()
            missing_optional          = @('FIVE12_BLE_TOOLS')
            from_process_env          = @()
            present                   = @(
                [pscustomobject]@{ key = 'DB_PASSWORD'; length = 12 },
                [pscustomobject]@{ key = 'DB_USER'; length = 4 }
            )
            unreferenced_in_env_file  = @()
            config_keys               = [pscustomobject]@{ DB_PASSWORD = $false; DB_USER = $true }
        }
        $r = Test-Five12EnvKeys -EnvReport $envSection
        $r.Status | Should Be 'OK'
    }

    It 'FAILS when .env has DB_PASS and config.py reads DB_PASSWORD' {
        $envSection = [pscustomobject]@{
            env_file_exists           = $true
            missing_required          = @('DB_PASSWORD')
            missing_optional          = @()
            from_process_env          = @()
            present                   = @()
            unreferenced_in_env_file  = @('DB_PASS')
            config_keys               = [pscustomobject]@{ DB_PASSWORD = $false }
        }
        $r = Test-Five12EnvKeys -EnvReport $envSection
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'DB_PASSWORD'
        # The half that sends the operator hunting for a wrong password: a key
        # that IS set but that nothing reads.
        ($r.Details -join ' ') | Should Match 'DB_PASS'
        ($r.Fix -join ' ') | Should Match 'backend\\.env'
    }

    It 'FAILS when backend\.env does not exist at all' {
        $envSection = [pscustomobject]@{
            env_file_exists           = $false
            missing_required          = @()
            missing_optional          = @()
            from_process_env          = @()
            present                   = @()
            unreferenced_in_env_file  = @()
            config_keys               = [pscustomobject]@{ }
        }
        $r = Test-Five12EnvKeys -EnvReport $envSection
        $r.Status | Should Be 'FAIL'
    }

    It 'reports lengths and never values' {
        $envSection = [pscustomobject]@{
            env_file_exists           = $true
            missing_required          = @()
            missing_optional          = @()
            from_process_env          = @()
            present                   = @([pscustomobject]@{ key = 'DB_PASSWORD'; length = 12 })
            unreferenced_in_env_file  = @()
            config_keys               = [pscustomobject]@{ DB_PASSWORD = $false }
        }
        $r = Test-Five12EnvKeys -EnvReport $envSection
        ($r.Details -join ' ') | Should Match 'DB_PASSWORD: present, length 12'
    }
}

Describe 'Database' {

    It 'reports the database name on success' {
        $db = [pscustomobject]@{
            ok = $true; database = 'five12_website'; server_version = '9.7.0'
            host = 'localhost'; user = 'root'; error = $null
        }
        $r = Test-Five12Database -Database $db
        $r.Status | Should Be 'OK'
        $r.Message | Should Match 'five12_website'
    }

    It 'FAILS when the credentials do not work' {
        $db = [pscustomobject]@{
            ok = $false; database = $null; server_version = $null
            host = 'localhost'; user = 'root'
            error = 'OperationalError: (1045, "Access denied for user")'
        }
        $r = Test-Five12Database -Database $db
        $r.Status | Should Be 'FAIL'
        ($r.Fix -join ' ') | Should Match 'DB_PASSWORD'
    }
}

Describe 'Fault 2 - flask process hygiene' {

    It 'passes with no backend running' {
        $r = Test-Five12FlaskProcesses -PortOwners @() -FlaskProcesses @()
        $r.Status | Should Be 'OK'
    }

    It 'passes with exactly one backend started with --no-reload' {
        $procs = @([pscustomobject]@{
                ProcessId = 111; ParentProcessId = 9
                CommandLine = 'python.exe -m flask run --port 5000 --no-reload'
            })
        $r = Test-Five12FlaskProcesses -PortOwners @(111) -FlaskProcesses $procs
        $r.Status | Should Be 'OK'
    }

    It 'FAILS on the reloader pair that raced the Bluetooth adapter lock' {
        $procs = @(
            [pscustomobject]@{ ProcessId = 111; ParentProcessId = 9; CommandLine = 'python.exe -m flask run --port 5000' },
            [pscustomobject]@{ ProcessId = 222; ParentProcessId = 111; CommandLine = 'python.exe -m flask run --port 5000' }
        )
        # Only the child binds the socket under the reloader, so the port shows
        # exactly one owner. Port counting alone would call this healthy.
        $r = Test-Five12FlaskProcesses -PortOwners @(222) -FlaskProcesses $procs
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'reloader'
        ($r.Fix -join ' ') | Should Match '--no-reload'
    }

    It 'FAILS on a single flask process missing --no-reload' {
        $procs = @([pscustomobject]@{
                ProcessId = 111; ParentProcessId = 9
                CommandLine = 'python.exe -m flask run --port 5000'
            })
        $r = Test-Five12FlaskProcesses -PortOwners @(111) -FlaskProcesses $procs
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'without --no-reload'
    }

    It 'FAILS when two unrelated processes hold port 5000' {
        $r = Test-Five12FlaskProcesses -PortOwners @(111, 222) -FlaskProcesses @()
        $r.Status | Should Be 'FAIL'
        ($r.Fix -join ' ') | Should Match 'Stop-Process'
    }
}

Describe 'Fault 5 - bluetooth feature gates' {

    It 'states both gates ON from a running backend' {
        $r = Test-Five12FeatureGates -BackendGates @{ ToolsEnabled = $true; WriteEnabled = $true }
        $r.Status | Should Be 'OK'
        ($r.Details -join ' ') | Should Match 'FIVE12_BLE_TOOLS = ON'
        ($r.Details -join ' ') | Should Match 'FIVE12_BLE_WRITE = ON'
    }

    It 'WARNs when the running backend has Bluetooth switched off' {
        $r = Test-Five12FeatureGates -BackendGates @{ ToolsEnabled = $false; WriteEnabled = $false }
        $r.Status | Should Be 'WARN'
        ($r.Details -join ' ') | Should Match 'FIVE12_BLE_TOOLS = OFF'
    }

    It 'WARNs when nothing sets the gates - the launcher fault' {
        $r = Test-Five12FeatureGates -BackendGates $null -LauncherGates @{} -ProcessEnv @{}
        $r.Status | Should Be 'WARN'
        ($r.Details -join ' ') | Should Match "unset anywhere"
        ($r.Fix -join ' ') | Should Match 'start.ps1'
    }

    It 'reports the value the launcher will actually set, and says so' {
        $r = Test-Five12FeatureGates -BackendGates $null `
            -LauncherGates @{ FIVE12_BLE_TOOLS = '1'; FIVE12_BLE_WRITE = '1' } -ProcessEnv @{}
        $r.Status | Should Be 'OK'
        ($r.Details -join ' ') | Should Match 'start.ps1 sets'
    }

    It 'WARNs when the launcher explicitly sets a gate to 0' {
        $r = Test-Five12FeatureGates -BackendGates $null `
            -LauncherGates @{ FIVE12_BLE_TOOLS = '1'; FIVE12_BLE_WRITE = '0' } -ProcessEnv @{}
        $r.Status | Should Be 'WARN'
        ($r.Details -join ' ') | Should Match 'FIVE12_BLE_WRITE = OFF'
    }
}

Describe 'Fault 6 - subnet coverage and network category' {

    $showSubnets = @(
        [pscustomobject]@{ label = 'Hognet'; cidr = '172.31.0.0/16'; active = $true; ignoreCidrs = $null },
        [pscustomobject]@{ label = 'sACN'; cidr = '10.0.0.0/8'; active = $true; ignoreCidrs = $null },
        [pscustomobject]@{ label = 'Bolero'; cidr = '192.168.1.0/24'; active = $true; ignoreCidrs = $null },
        [pscustomobject]@{ label = 'Management'; cidr = '172.16.0.0/16'; active = $true; ignoreCidrs = '172.16.10.0/23' }
    )
    $showNics = @(
        [pscustomobject]@{ IPAddress = '172.31.0.220'; PrefixLength = 16; InterfaceAlias = 'HOG' },
        [pscustomobject]@{ IPAddress = '10.220.220.220'; PrefixLength = 8; InterfaceAlias = 'sACN' },
        [pscustomobject]@{ IPAddress = '192.168.1.220'; PrefixLength = 24; InterfaceAlias = 'COMS' },
        [pscustomobject]@{ IPAddress = '172.16.220.220'; PrefixLength = 16; InterfaceAlias = 'Management' },
        [pscustomobject]@{ IPAddress = '172.16.10.228'; PrefixLength = 23; InterfaceAlias = 'Wi-Fi' }
    )

    It 'passes when all four subnets have an interface at the right prefix' {
        $r = Test-Five12SubnetCoverage -Subnets $showSubnets -Interfaces $showNics
        $r.Status | Should Be 'OK'
        $r.ShowNics.Count | Should Be 4
    }

    It 'does not mistake the venue Wi-Fi for the Management show NIC' {
        # 172.16.10.228/23 is inside Management 172.16.0.0/16 but is listed in
        # that subnet's ignoreCidrs and carries a different prefix. Calling it
        # a show NIC would demand the venue Wi-Fi be made Private.
        $r = Test-Five12SubnetCoverage -Subnets $showSubnets -Interfaces $showNics
        @($r.ShowNics | ForEach-Object { $_.InterfaceAlias }) -contains 'Wi-Fi' | Should Be $false
    }

    It 'FAILS when a NIC has drifted to the wrong prefix length' {
        $drifted = @(
            [pscustomobject]@{ IPAddress = '172.31.0.220'; PrefixLength = 24; InterfaceAlias = 'HOG' }
        )
        $r = Test-Five12SubnetCoverage -Subnets @($showSubnets[0]) -Interfaces $drifted
        $r.Status | Should Be 'FAIL'
        ($r.Details -join ' ') | Should Match 'WRONG prefix'
        ($r.Fix -join ' ') | Should Match '255.255.0.0'
    }

    It 'WARNs, not FAILs, when a show NIC is simply absent' {
        $r = Test-Five12SubnetCoverage -Subnets @($showSubnets[0]) -Interfaces @()
        $r.Status | Should Be 'WARN'
        ($r.Details -join ' ') | Should Match 'no local interface'
    }

    It 'ignores inactive subnets' {
        $inactive = @([pscustomobject]@{ label = 'Old'; cidr = '10.9.0.0/16'; active = $false; ignoreCidrs = $null })
        $r = Test-Five12SubnetCoverage -Subnets ($showSubnets + $inactive) -Interfaces $showNics
        $r.Status | Should Be 'OK'
    }

    It 'passes when every show NIC is Private' {
        $coverage = Test-Five12SubnetCoverage -Subnets $showSubnets -Interfaces $showNics
        $profiles = @(
            [pscustomobject]@{ InterfaceAlias = 'HOG'; NetworkCategory = 'Private' },
            [pscustomobject]@{ InterfaceAlias = 'sACN'; NetworkCategory = 'Private' },
            [pscustomobject]@{ InterfaceAlias = 'COMS'; NetworkCategory = 'Private' },
            [pscustomobject]@{ InterfaceAlias = 'Management'; NetworkCategory = 'Private' }
        )
        $r = Test-Five12NetworkCategories -ShowNics $coverage.ShowNics -Profiles $profiles
        $r.Status | Should Be 'OK'
    }

    It 'FAILS when all four show NICs have drifted to Public' {
        $coverage = Test-Five12SubnetCoverage -Subnets $showSubnets -Interfaces $showNics
        $profiles = @(
            [pscustomobject]@{ InterfaceAlias = 'HOG'; NetworkCategory = 'Public' },
            [pscustomobject]@{ InterfaceAlias = 'sACN'; NetworkCategory = 'Public' },
            [pscustomobject]@{ InterfaceAlias = 'COMS'; NetworkCategory = 'Public' },
            [pscustomobject]@{ InterfaceAlias = 'Management'; NetworkCategory = 'Public' }
        )
        $r = Test-Five12NetworkCategories -ShowNics $coverage.ShowNics -Profiles $profiles
        $r.Status | Should Be 'FAIL'
        ($r.Fix -join ' ') | Should Match 'Set-NetConnectionProfile'
        @($r.Fix).Count | Should Be 4
    }

    It 'FAILS when even one show NIC is Public' {
        $coverage = Test-Five12SubnetCoverage -Subnets @($showSubnets[0]) -Interfaces $showNics
        $profiles = @([pscustomobject]@{ InterfaceAlias = 'HOG'; NetworkCategory = 'Public' })
        $r = Test-Five12NetworkCategories -ShowNics $coverage.ShowNics -Profiles $profiles
        $r.Status | Should Be 'FAIL'
    }

    It 'says so, rather than passing quietly, when a NIC has no connection profile' {
        # Windows publishes no profile for a disconnected or unidentified
        # network. That is not fault 6 (it cannot be Public), so it must not
        # FAIL — but it must not vanish either.
        $coverage = Test-Five12SubnetCoverage -Subnets @($showSubnets[0]) -Interfaces $showNics
        $r = Test-Five12NetworkCategories -ShowNics $coverage.ShowNics -Profiles @()
        $r.Status | Should Be 'INFO'
        ($r.Details -join ' ') | Should Match 'no connection profile'
    }
}

Describe 'Exit code' {

    It 'is 1 when any check FAILed' {
        $checks = @(
            (New-Five12Check -Name 'a' -Status 'OK' -Message 'x'),
            (New-Five12Check -Name 'b' -Status 'FAIL' -Message 'y')
        )
        Get-Five12ExitCode -Checks $checks | Should Be 1
    }

    It 'is 0 when the worst is a WARN, so a warning never blocks a launch' {
        $checks = @(
            (New-Five12Check -Name 'a' -Status 'OK' -Message 'x'),
            (New-Five12Check -Name 'b' -Status 'WARN' -Message 'y')
        )
        Get-Five12ExitCode -Checks $checks | Should Be 0
    }
}
