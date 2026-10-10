Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:KwProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

function Import-KwEnvironment {
    $envFile = Join-Path $script:KwProjectRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile)) { return }
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        $entry = $line.Trim()
        if (-not $entry -or $entry.StartsWith('#')) { continue }
        if ($entry -notmatch '^((?:KW_|AI_|SHIYI_)[A-Z0-9_]+)=(.*)$') { throw 'Invalid .env line. Only KW_, AI_, and SHIYI_ variables are allowed.' }
        $key = $Matches[1]; $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) { $value = $value.Substring(1, $value.Length - 2) }
        if (-not [Environment]::GetEnvironmentVariable($key, 'Process')) { [Environment]::SetEnvironmentVariable($key, $value, 'Process') }
    }
}

function Initialize-KwRuntime([string]$DataDir, [int]$Port, [bool]$TestAdapter, [bool]$Development) {
    Import-KwEnvironment
    $env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
    if ($DataDir) { $env:KW_DATA_DIR = [IO.Path]::GetFullPath($DataDir) }
    if (-not $env:KW_DATA_DIR) { $env:KW_DATA_DIR = Join-Path $script:KwProjectRoot 'data' }
    $env:KW_DATA_DIR = [IO.Path]::GetFullPath($env:KW_DATA_DIR)
    if ($TestAdapter) { $env:KW_FAKE_PROVIDER = '1'; $env:KW_MODE = 'development' }
    elseif ($Development) { $env:KW_MODE = 'development' }
    else { $env:KW_MODE = 'production'; $env:KW_FAKE_PROVIDER = '0' }
    if (-not $env:KW_ORIGIN -or $Port -ne 8000) { $env:KW_ORIGIN = "http://127.0.0.1:$Port" }
    New-Item -ItemType Directory -Path $env:KW_DATA_DIR -Force | Out-Null
    $script:KwRuntimeFile = Join-Path $env:KW_DATA_DIR '.runtime.json'
    $script:KwLogDir = Join-Path $env:KW_DATA_DIR 'logs'
    New-Item -ItemType Directory -Path $script:KwLogDir -Force | Out-Null
    if (Test-Path -LiteralPath $script:KwRuntimeFile) {
        $record = Get-Content -LiteralPath $script:KwRuntimeFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in $record.processes) {
            $process = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
            if ($process -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $item.started_ticks) { throw 'This data directory already has a running service. Use scripts/stop.ps1 first.' }
        }
    }
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw "Port $Port is in use. Select another port; no existing service was stopped." }
}

function Install-KwDependencies {
    Push-Location (Join-Path $script:KwProjectRoot 'backend')
    try {
        & uv sync --frozen --python 3.14.6
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    } finally { Pop-Location }
    Push-Location (Join-Path $script:KwProjectRoot 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules/.package-lock.json')) {
            & npm.cmd ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        }
    } finally { Pop-Location }
}

function Start-KwProcess([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$Directory) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $script:KwLogDir ($Name + '.out.log')) -RedirectStandardError (Join-Path $script:KwLogDir ($Name + '.err.log'))
    Start-Sleep -Milliseconds 150
    if ($process.HasExited) { throw "$Name exited. Check $script:KwLogDir" }
    return [pscustomobject]@{ name = $Name; pid = $process.Id; started_ticks = $process.StartTime.ToUniversalTime().Ticks.ToString(); executable = [IO.Path]::GetFullPath($Executable) }
}

function Save-KwProcesses($Processes, [int]$Port) {
    [pscustomobject]@{ root = $script:KwProjectRoot; data_dir = $env:KW_DATA_DIR; port = $Port; processes = @($Processes) } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $script:KwRuntimeFile -Encoding UTF8
}

function Wait-KwHealth([int]$Port) {
    for ($i = 0; $i -lt 40; $i++) {
        try { $null = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2; return } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "API did not become ready. Check $script:KwLogDir"
}
