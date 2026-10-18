param(
    [switch]$LocalModel,
    [switch]$Gpu,
    [ValidateRange(30, 3600)][int]$WaitSeconds = 1800,
    [switch]$Interactive,
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
function Get-DockerEngineState {
    # Windows PowerShell 5 treats native stderr as ErrorRecords. An inactive
    # daemon is expected here and must not prevent launching Docker Desktop.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $engine = & docker info --format '{{.OSType}}' 2>$null
        return @{ Ready = ($LASTEXITCODE -eq 0); Engine = $engine }
    }
    finally { $ErrorActionPreference = $previousPreference }
}
$posttechRoot = Split-Path -Parent $PSScriptRoot
Push-Location $posttechRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop, then restart this launcher. Use Linux containers.'
    }
    $dockerState = Get-DockerEngineState
    if (-not $dockerState.Ready -and $Interactive) {
        $desktopPaths = @(
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
        )
        $desktop = $desktopPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $desktop) { throw 'Open Docker Desktop, wait until it is running, then try again.' }
        Write-Host 'Starting Docker Desktop. Waiting up to 3 minutes...'
        Start-Process -FilePath $desktop -WindowStyle Hidden
        $deadline = (Get-Date).AddMinutes(3)
        do {
            Start-Sleep -Seconds 3
            $dockerState = Get-DockerEngineState
        } while (-not $dockerState.Ready -and (Get-Date) -lt $deadline)
    }
    if (-not $dockerState.Ready -or $dockerState.Engine -ne 'linux') {
        throw 'Docker Linux engine is not ready. Check Docker Desktop and virtualization, then try again.'
    }
    $dockerEnv = Join-Path $posttechRoot '.local\docker.env'
    $telegramEnv = Join-Path $posttechRoot '.local\telegram.env'
    $openaiEnv = Join-Path $posttechRoot '.local\openai.env'
    if (-not (Test-Path -LiteralPath $dockerEnv)) {
        & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_docker.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare local Docker settings.' }
    }
    if (-not (Test-Path -LiteralPath $telegramEnv)) {
        & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_telegram.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare Telegram settings.' }
    }
    $tokenLine = Get-Content -LiteralPath $telegramEnv | Where-Object { $_ -match '^\s*TELEGRAM_BOT_TOKEN\s*=' } | Select-Object -Last 1
    $savedToken = if ($tokenLine) { ($tokenLine -split '=', 2)[1].Trim().Trim('"').Trim("'") } else { '' }
    if (-not $savedToken) {
        if (-not $Interactive) { throw 'Save the BotFather token in .local/telegram.env, then run this script again.' }
        Write-Host 'FIRST SETUP: paste the BotFather token at the hidden prompt and press Enter.'
        Write-Host 'It is saved only in .local/telegram.env. No token is sent to GitHub.'
        & docker run --rm -it --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_telegram.py --set-token
        if ($LASTEXITCODE -ne 0) { throw 'Token setup failed. Check the token/network and try again.' }
    }
    $savedToken = $null
    if (-not ($LocalModel -or $Gpu)) {
        Write-Host 'Jana uses OpenAI API. No local model will be downloaded.'
        Write-Host 'Save your API key in .local/openai.env or paste it at the hidden first-setup prompt.'
        $setup = @('run', '--rm')
        if ($Interactive) { $setup += '-it' }
        $setup += @('--volume', "${posttechRoot}:/workspace", '--workdir', '/workspace', 'python:3.12-slim', 'python', '-m', 'scripts.prepare_openai')
        if ($Interactive) { $setup += '--interactive' }
        & docker @setup
        if ($LASTEXITCODE -ne 0) { throw 'OpenAI setup failed. Check .local/openai.env and retry; your key is never printed.' }
    }
    # Only verifies getMe and fills the public bot username. No message is sent.
    & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.12-slim python scripts/prepare_telegram.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Telegram settings are not ready; see the message above.' }
    $compose = @('compose', '--env-file', $dockerEnv, '--env-file', $telegramEnv)
    if (-not ($LocalModel -or $Gpu)) { $compose += @('--env-file', $openaiEnv) }
    $compose += @('-f', 'compose.demo.yaml')
    if ($Gpu) { $compose += @('-f', 'compose.gpu.yaml') }
    $compose += @('-f', 'compose.telegram.yaml')
    if (-not ($LocalModel -or $Gpu)) {
        $compose += @('-f', 'compose.openai.yaml')
        # Switching an existing demo must also release the old local model's RAM.
        # stop does not pull images, delete volumes or affect another project.
        & docker @compose --profile local-model stop jana-reader model-init
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the previous local reader. Check Docker Compose (2.24.4+).' }
    }
    Write-Host 'Starting the site, database, Jana and Telegram bot.'
    Write-Host 'First startup downloads Docker images. Keep this window open.'
    if ($LocalModel -or $Gpu) { Write-Host 'Local mode additionally downloads about 6.2 GB of model weights.' }
    & docker @compose up --detach --build --wait --wait-timeout $WaitSeconds
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Check the container status; do not publish secret configuration.' }
    $portLine = Get-Content -LiteralPath $dockerEnv | Where-Object { $_ -match '^POSTTECH_HTTP_PORT=' } | Select-Object -Last 1
    $port = 0
    if (-not $portLine -or -not [int]::TryParse(($portLine -split '=', 2)[1], [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw 'Invalid POSTTECH_HTTP_PORT in .local/docker.env; the browser was not opened.'
    }
    $url = "http://127.0.0.1:$port"
    $page = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch '/assets/.*\.js') {
        throw 'Containers started, but the portal did not respond correctly. Check the frontend service.'
    }
    Write-Host "Site and Telegram worker started: $url"
    Write-Host 'Login: employee@posttech.demo (ordinary login, not Demo mode).'
    Write-Host 'Password: POSTTECH_DEMO_PASSWORD in .local/docker.env. It is preserved on subsequent launches.'
    Write-Host 'Connect Telegram in Settings. Keep Docker, power and internet on during the demonstration.'
    if ($LocalModel -or $Gpu) { Write-Host 'Local Jana may still be warming up.' }
    Write-Host 'Rehearse a Jana question before the presentation; OpenAI requires available API quota.'
    Write-Host 'For the portal inside Telegram, configure a reachable HTTPS PORTAL_PUBLIC_URL.'
    if ($OpenBrowser) { Start-Process -FilePath $url }
}
finally { Pop-Location }
