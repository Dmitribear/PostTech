param(
    [string]$Python = '',
    [string]$ReportDirectory = '.local/backend-tests'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) { $Python = Join-Path $projectRoot '.venv/Scripts/python.exe' }
$reportPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $ReportDirectory))
if (-not $reportPath.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The report directory must be inside the project.'
}
$previousDatabaseUrl = $env:POSTTECH_TEST_DATABASE_URL
$testContainerId = $null
$testImage = 'postgres:16-alpine'
$testPassword = [guid]::NewGuid().ToString('N')
$testContainerName = 'posttech-pytest-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$testExitCode = 1
Push-Location $projectRoot
try {
    & $Python -c 'import pytest, psycopg'
    if ($LASTEXITCODE -ne 0) { throw 'Install requirements-dev.txt and tests/requirements-db.txt in the project environment.' }
    New-Item -ItemType Directory -Path $reportPath -Force | Out-Null
    $testContainerId = & docker run --rm --detach --name $testContainerName `
        --publish '127.0.0.1::5432' --mount type=tmpfs,destination=/var/lib/postgresql/data `
        --env "POSTGRES_PASSWORD=$testPassword" --env POSTGRES_DB=posttech_test_control $testImage
    if ($LASTEXITCODE -ne 0) { throw 'Could not start isolated PostgreSQL.' }
    $testContainerId = ($testContainerId -join '').Trim()
    if ($testContainerId -notmatch '^[0-9a-f]{64}$') { throw 'Unexpected container identifier.' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        & docker exec $testContainerId pg_isready -U postgres -d posttech_test_control *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Test PostgreSQL did not become ready.' }
    $portOutput = & docker port $testContainerId 5432/tcp
    if ($LASTEXITCODE -ne 0 -or ($portOutput -join '').Trim() -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'Expected a loopback-only test database port.'
    }
    $testPort = $Matches[1]
    $env:POSTTECH_TEST_DATABASE_URL = "postgresql://postgres:${testPassword}@127.0.0.1:${testPort}/posttech_test_control"
    $junitPath = Join-Path $reportPath 'pytest.xml'
    & $Python -X utf8 -m pytest tests -q -ra "--junitxml=$junitPath"
    $testExitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $junitPath) {
        [xml]$junit = Get-Content -LiteralPath $junitPath -Raw
        $suite = $junit.testsuites.testsuite
        $summary = [ordered]@{
            checked_at = [DateTime]::UtcNow.ToString('o')
            database = $testImage
            isolation = 'Disposable local PostgreSQL; UUID databases per fixture; synthetic auth.users, real application SQL and RLS.'
            total = [int]$suite.tests
            failures = [int]$suite.failures
            errors = [int]$suite.errors
            skipped = [int]$suite.skipped
            passed = [int]$suite.tests - [int]$suite.failures - [int]$suite.errors - [int]$suite.skipped
            exit_code = $testExitCode
        }
        if ($testExitCode -eq 0 -and $summary.skipped -gt 0) {
            $testExitCode = 1
            $summary.exit_code = 1
        }
        $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportPath 'summary.json') -Encoding utf8
    }
}
finally {
    $env:POSTTECH_TEST_DATABASE_URL = $previousDatabaseUrl
    if ($testContainerId -match '^[0-9a-f]{64}$') {
        & docker rm --force --volumes $testContainerId | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not remove test container $testContainerName" }
    }
    Pop-Location
}
exit $testExitCode
