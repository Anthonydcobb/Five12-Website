param(
    [string]$Mode = ""
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
    $env:PATH = "$pythonScripts;" + $env:PATH
    # --no-reload is load-bearing, not a preference. Werkzeug's auto-reloader
    # runs the app in TWO processes; both start the Bluetooth service and race
    # for the adapter's single-owner lock. Whichever one loses serves your
    # requests reporting "another Five12 process owns the Bluetooth adapter"
    # and scans nothing, so the Cintennas tab stays empty while the radio is
    # sitting right there. Observed 2026-07-28. Cost: you restart the backend
    # by hand after editing Python.
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:PATH = '$pythonScripts;' + `$env:PATH; cd '$root\backend'; & '$pythonExe' -m flask run --port 5000 --no-reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\app'; npm run dev"
    Write-Host "Backend:  http://localhost:5000" -ForegroundColor Cyan
    Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
}
