param([string]$DataDir, [ValidateRange(1024,65535)][int]$Port = 8000, [string]$BindAddress = '127.0.0.1', [switch]$SkipBuild, [switch]$TestAdapter)
. (Join-Path $PSScriptRoot 'common.ps1')
Initialize-KwRuntime $DataDir $Port $TestAdapter.IsPresent $false
Install-KwDependencies
if (-not $SkipBuild) {
    Push-Location (Join-Path $script:KwProjectRoot 'frontend')
    try {
        $buildLog = Join-Path $script:KwLogDir 'build.log'
        $previousErrorAction = $ErrorActionPreference
        try {
            # Windows PowerShell treats redirected native stderr as ErrorRecord.
            # Vite warnings are not build failures; use npm's exit code instead.
            $ErrorActionPreference = 'Continue'
            & npm.cmd run build *> $buildLog
            $buildExitCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $previousErrorAction }
        if ($buildExitCode -ne 0) { throw "Frontend build failed (exit $buildExitCode). See $buildLog" }
    } finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath (Join-Path $script:KwProjectRoot 'frontend/dist/index.html'))) { throw 'Build output is missing. Run without -SkipBuild.' }
$python = Join-Path $script:KwProjectRoot 'backend/.venv/Scripts/python.exe'
$backend = Join-Path $script:KwProjectRoot 'backend'
$processes = @()
try {
    $processes += Start-KwProcess 'api' $python @('-m','uvicorn','knowledge_world.api:app','--host',$BindAddress,'--port',"$Port",'--no-access-log') $backend
    Save-KwProcesses $processes $Port
    Wait-KwHealth $Port
    $processes += Start-KwProcess 'worker' $python @('-m','knowledge_world.worker') $backend
    Save-KwProcesses $processes $Port
    Write-Host "Knowledge World ready: http://127.0.0.1:$Port"
    Write-Host "Data: $env:KW_DATA_DIR"
    if ($TestAdapter) { Write-Host 'TEST ADAPTER ENABLED. These results are not real AI evidence.' }
} catch {
    Save-KwProcesses $processes $Port
    throw
}
