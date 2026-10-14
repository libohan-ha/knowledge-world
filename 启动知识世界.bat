@echo off
setlocal
cd /d "%~dp0"
set "PORT=18350"
set "URL=http://127.0.0.1:%PORT%"
set "DATA_DIR=%~dp0artifacts\runtime\owner-preview"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if($c){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c[0].OwningProcess); if($p.CommandLine -match 'knowledge_world.api:app'){Start-Process $env:URL; exit 0}; Write-Host 'Port %PORT% is occupied by another program.'; exit 2}; exit 1"
if errorlevel 2 (pause & exit /b 2)
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\start.ps1" -DataDir "%DATA_DIR%" -Port %PORT% -BindAddress 0.0.0.0
  if errorlevel 1 (pause & exit /b 1)
)
start "Knowledge World" "%URL%"
endlocal
