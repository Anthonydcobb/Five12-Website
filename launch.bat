@echo off
where pwsh.exe >nul 2>&1
if %errorlevel% == 0 (
    pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
)
