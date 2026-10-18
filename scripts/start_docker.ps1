param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$posttechRoot = Split-Path -Parent $PSScriptRoot
Push-Location $posttechRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop is required. Install and start it first.'
    }
    Write-Host 'Building the current PostTech version and starting Docker...'
    & docker compose up --build --detach --remove-orphans --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker startup failed. Check the output above and ensure Docker Desktop is running.'
    }
    $posttechPort = & docker compose port frontend 80
    if ($LASTEXITCODE -ne 0) { throw 'Cannot determine the frontend port.' }
    $posttechUrl = 'http://' + $posttechPort.Trim()
    $posttechPage = Invoke-WebRequest -Uri $posttechUrl -UseBasicParsing -TimeoutSec 15
    if ($posttechPage.Content -notmatch '/assets/.*\.js') {
        throw 'The container started, but the built portal was not found.'
    }
    try {
        $posttechReady = Invoke-RestMethod -Uri "$posttechUrl/api/v1/health/ready" -TimeoutSec 30
        if ($posttechReady.status -ne 'ready') { throw 'Database is not ready.' }
    }
    catch {
        throw 'The UI is running, but the database is not ready. Check Supabase connectivity, server credentials and migrations 0001-0016. See docs/docker.md.'
    }
    Write-Host "PostTech is ready: $posttechUrl"
    if (-not $NoBrowser) { Start-Process $posttechUrl }
}
finally { Pop-Location }
