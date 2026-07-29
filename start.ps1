param(
    [string]$Mode = "",
    # Skip the preflight doctor. Every check it runs exists because something
    # broke silently on 2026-07-28/29 — see scripts/doctor.ps1 — so this is an
    # escape hatch, not a shortcut.
    [switch]$SkipDoctor
)

$pythonExe    = "C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe"
$pythonScripts = "C:\Users\antho\AppData\Local\Programs\Python\Python312\Scripts"
$root         = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Mode -eq "") {
    Write-Host ""
    Write-Host "  Five12 Lighting" -ForegroundColor Cyan
    Write-Host "  ───────────────────────────" -ForegroundColor DarkGray
    Write-Host "  [1] App mode   — desktop app (Electron)"  -ForegroundColor Green
    Write-Host "  [2] Dev mode   — browser + Vite dev server" -ForegroundColor Yellow
    Write-Host ""
    $choice = Read-Host "  Choose (1 or 2)"
    $Mode = if ($choice -eq "2") { "dev" } else { "app" }
}

if ($Mode -eq "app") {
    Write-Host "Launching Five12 app..." -ForegroundColor Green
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\electron'; npm start"
} else {
    Write-Host "Starting Five12 in dev mode..." -ForegroundColor Yellow

    # Preflight before anything launches. On 2026-07-28/29 six separate faults
    # cost a session most of a day and not one of them printed a thing: a stale
    # OneDrive clone, a doubled Flask process fighting over the Bluetooth
    # adapter, a missing package swallowed by a blanket `except`, a renamed
    # .env key, unset feature gates, and four show NICs on the Public network
    # category. The doctor is read-only; it names the fix, it does not apply it.
    if (-not $SkipDoctor) {
        & (Join-Path $root 'scripts\doctor.ps1')
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  Preflight FAILED. Each fault above has silently broken this app before." -ForegroundColor Red
            $answer = Read-Host "  Launch anyway? (y/N)"
            if ($answer -ne 'y') {
                Write-Host "  Aborted. Fix the FAIL lines, or re-run: .\start.ps1 -Mode dev -SkipDoctor" -ForegroundColor Yellow
                exit 1
            }
        }
    }

    $env:PATH = "$pythonScripts;" + $env:PATH
    # --no-reload is load-bearing, not a preference. Werkzeug's auto-reloader
    # runs the app in TWO processes; both start the Bluetooth service and race
    # for the adapter's single-owner lock. Whichever one loses serves your
    # requests reporting "another Five12 process owns the Bluetooth adapter"
    # and scans nothing, so the Cintennas tab stays empty while the radio is
    # sitting right there. Observed 2026-07-28. Cost: you restart the backend
    # by hand after editing Python.
    # Bluetooth is gated by two env vars that default OFF, so that a hosted
    # deploy never starts a radio scan or writes to a fixture unasked. On this
    # rig, launching Five12 IS the ask — without these the Cintennas tab just
    # reports "Bluetooth tools are switched off" every time.
    #   FIVE12_BLE_TOOLS : passive discovery + connected status reads
    #   FIVE12_BLE_WRITE : mode switch, Link, Unlink
    # Writes are still individually confirmed in the UI and re-checked
    # server-side; this only decides whether the controls exist at all.
    # To launch read-only, set either to '0' below.
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:PATH = '$pythonScripts;' + `$env:PATH; `$env:FIVE12_BLE_TOOLS = '1'; `$env:FIVE12_BLE_WRITE = '1'; cd '$root\backend'; & '$pythonExe' -m flask run --port 5000 --no-reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\app'; npm run dev"
    Write-Host "Backend:  http://localhost:5000" -ForegroundColor Cyan
    Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
    Write-Host "Bluetooth: discovery ON, writes ON (Link/Unlink available)" -ForegroundColor DarkYellow
}
