param([string]$DataDir, [ValidateRange(1024,65535)][int]$Port = 8000, [ValidateRange(1024,65535)][int]$WebPort = 5173, [switch]$TestAdapter)
. (Join-Path $PSScriptRoot 'common.ps1')
Initialize-KwRuntime $DataDir $Port $TestAdapter.IsPresent $true
Install-KwDependencies
if (Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue) { throw "Web port $WebPort is in use." }
$env:KW_DEV_API_PORT = "$Port"
$env:KW_DEV_WEB_PORT = "$WebPort"
$env:KW_ORIGIN = "http://127.0.0.1:$WebPort"
$python = Join-Path $script:KwProjectRoot 'backend/.venv/Scripts/python.exe'
$node = (Get-Command node.exe -ErrorAction Stop).Source
$backend = Join-Path $script:KwProjectRoot 'backend'
$frontend = Join-Path $script:KwProjectRoot 'frontend'
$processes = @()
try {
    $processes += Start-KwProcess 'api' $python @('-m','uvicorn','knowledge_world.api:app','--host','127.0.0.1','--port',"$Port",'--no-access-log') $backend
    Save-KwProcesses $processes $Port
    Wait-KwHealth $Port
    $processes += Start-KwProcess 'worker' $python @('-m','knowledge_world.worker') $backend
    $processes += Start-KwProcess 'web' $node @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',"$WebPort") $frontend
    Save-KwProcesses $processes $Port
    Write-Host "Development ready: http://127.0.0.1:$WebPort"
    if ($TestAdapter) { Write-Host 'TEST ADAPTER ENABLED. These results are not real AI evidence.' }
} catch { Save-KwProcesses $processes $Port; throw }
