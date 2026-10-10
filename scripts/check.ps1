param([switch]$Browser)
. (Join-Path $PSScriptRoot 'common.ps1')
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
Install-KwDependencies
Push-Location (Join-Path $script:KwProjectRoot 'backend')
try {
    & uv run --frozen ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
    & uv run --frozen pytest -q --junitxml=../artifacts/backend-tests.xml
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    & uv run --frozen python -m knowledge_world.cli openapi --file ../artifacts/openapi.json
    if ($LASTEXITCODE -ne 0) { throw 'OpenAPI generation failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $script:KwProjectRoot 'frontend')
try {
    & npm.cmd run generate-api
    if ($LASTEXITCODE -ne 0) { throw 'API type generation failed.' }
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Frontend type check failed.' }
    & npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Component tests failed.' }
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & npm.cmd run build *> (Join-Path $script:KwProjectRoot 'artifacts/frontend-build.log')
        $buildExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousErrorAction }
    if ($buildExitCode -ne 0) { throw 'Frontend build failed.' }
    if ($Browser) {
        & npm.cmd run e2e
        if ($LASTEXITCODE -ne 0) { throw 'Browser tests failed.' }
    }
} finally { Pop-Location }
Write-Host 'Requested checks passed. Real provider acceptance is separate.'
