param([string]$DataDir)
. (Join-Path $PSScriptRoot 'common.ps1')
Import-KwEnvironment
if (-not $DataDir) { $DataDir = if ($env:KW_DATA_DIR) { $env:KW_DATA_DIR } else { Join-Path $script:KwProjectRoot 'data' } }
$runtimeFile = Join-Path ([IO.Path]::GetFullPath($DataDir)) '.runtime.json'
if (-not (Test-Path -LiteralPath $runtimeFile)) { Write-Host 'No recorded services.'; exit 0 }
$record = Get-Content -LiteralPath $runtimeFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.root -ne $script:KwProjectRoot) { throw 'Runtime record belongs to a different project. No process stopped.' }
foreach ($item in $record.processes) {
    $process = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($process.StartTime.ToUniversalTime().Ticks.ToString() -ne $item.started_ticks -or $process.Path -ne $item.executable) { Write-Host "PID $($item.pid) no longer matches the recorded service; skipped."; continue }
    # Python virtualenv launchers and Vite can own child processes.
    & taskkill.exe /PID $process.Id /T /F | Out-Null
    Write-Host "Stopped $($item.name)."
}
Remove-Item -LiteralPath $runtimeFile
