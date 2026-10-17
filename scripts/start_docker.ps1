param(
    [switch]$NoBrowser,
    [switch]$Gpu,
    [string]$ModelDirectory = '',
    [ValidateRange(120, 7200)][int]$WaitSeconds = 1800
)

$ErrorActionPreference = 'Stop'
$posttechRoot = Split-Path -Parent $PSScriptRoot
Push-Location $posttechRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop is required. Install and start it first.'
    }
    & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers first.' }
    $localEnv = Join-Path $posttechRoot '.local\docker.env'
    if (-not (Test-Path -LiteralPath $localEnv)) {
        # No host Python installation and no shared .env are required.
        & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_docker.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not generate local Docker configuration.' }
    }
    $compose = @('compose', '--env-file', $localEnv)
    if ($Gpu) { $compose += @('-f', 'compose.yaml', '-f', 'compose.gpu.yaml') }
    Write-Host 'Building the isolated local PostTech stack...'
    & docker @compose build
    if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
    if (-not $ModelDirectory) {
        $candidate = Join-Path $posttechRoot '.models\reader'
        if (Test-Path -LiteralPath $candidate) { $ModelDirectory = $candidate }
    }
    if ($ModelDirectory) {
        $sourceModels = (Resolve-Path -LiteralPath $ModelDirectory).Path
        & docker @compose run --rm --no-deps --volume "${sourceModels}:/model-source:ro" model-init --source /model-source
        if ($LASTEXITCODE -ne 0) { throw 'Could not verify and import the pinned model into its volume.' }
    }
    & docker @compose up --detach --wait --wait-timeout $WaitSeconds
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker startup failed. Check the output above and ensure Docker Desktop is running.'
    }
    $portLine = Get-Content -LiteralPath $localEnv | Where-Object { $_ -match '^POSTTECH_HTTP_PORT=' } | Select-Object -First 1
    $port = if ($portLine) { ($portLine -split '=', 2)[1] } else { '8000' }
    $posttechUrl = "http://127.0.0.1:$port"
    $posttechPage = Invoke-WebRequest -Uri $posttechUrl -UseBasicParsing -TimeoutSec 15
    if ($posttechPage.Content -notmatch '/assets/.*\.js') {
        throw 'The container started, but the built portal was not found.'
    }
    Write-Host "PostTech is ready: $posttechUrl"
    Write-Host 'Use employee@posttech.demo, manager@posttech.demo, director@posttech.demo or hr@posttech.demo.'
    Write-Host 'Their local password is POSTTECH_DEMO_PASSWORD in .local/docker.env; do not share the file.'
    if (-not $NoBrowser) { Start-Process $posttechUrl }
}
finally { Pop-Location }
