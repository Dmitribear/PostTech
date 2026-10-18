param([switch]$Gpu, [int]$WaitSeconds = 1800)
$ErrorActionPreference = 'Stop'
$posttechRoot = Split-Path -Parent $PSScriptRoot
Push-Location $posttechRoot
try {
    & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers first.' }
    $dockerEnv = Join-Path $posttechRoot '.local\docker.env'
    $telegramEnv = Join-Path $posttechRoot '.local\telegram.env'
    if (-not (Test-Path -LiteralPath $dockerEnv)) {
        & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_docker.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare local Docker settings.' }
    }
    if (-not (Test-Path -LiteralPath $telegramEnv)) {
        & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_telegram.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare Telegram settings.' }
        throw 'Save the BotFather token in .local/telegram.env, then run this script again.'
    }
    # Only verifies getMe and fills the public bot username. No message is sent.
    & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_telegram.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Telegram settings are not ready; see the message above.' }
    $compose = @('compose', '--env-file', $dockerEnv, '--env-file', $telegramEnv, '-f', 'compose.yaml')
    if ($Gpu) { $compose += @('-f', 'compose.gpu.yaml') }
    $compose += @('-f', 'compose.telegram.yaml')
    & docker @compose up --detach --build --wait --wait-timeout $WaitSeconds
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Check the container status; do not publish secret configuration.' }
    Write-Host 'Telegram worker started. Open Settings on the site and connect your Telegram account.'
    Write-Host 'For the portal inside Telegram, configure a reachable HTTPS PORTAL_PUBLIC_URL.'
}
finally { Pop-Location }
