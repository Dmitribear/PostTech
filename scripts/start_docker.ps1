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
    Write-Host "PostTech is ready: $posttechUrl"
    if (-not $NoBrowser) { Start-Process $posttechUrl }
}
finally { Pop-Location }
