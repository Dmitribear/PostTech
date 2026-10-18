param(
    [switch]$Telegram,
    [string]$LanHost,
    [ValidateRange(30, 3600)][int]$WaitSeconds = 180,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$posttechRoot = Split-Path -Parent $PSScriptRoot
$savedLanHost = $env:POSTTECH_LAN_HOST
$telegramKeys = @('TELEGRAM_BOT_TOKEN', 'TELEGRAM_BOT_USERNAME', 'TELEGRAM_WORKER_SECRET')
$savedTelegramEnvironment = @{}
foreach ($key in $telegramKeys) { $savedTelegramEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }

function Read-Setting([string]$Path, [string]$Name) {
    $line = Get-Content -LiteralPath $Path | Where-Object { ($_ -split '=', 2)[0].Trim() -eq $Name } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim().Trim('"').Trim("'") }
    return ''
}

function Test-LanAddress([string]$Value) {
    $address = $null
    if (-not [Net.IPAddress]::TryParse($Value, [ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { return $false }
    $bytes = $address.GetAddressBytes()
    return $Value -eq $address.ToString() -and (
        $bytes[0] -eq 10 -or
        ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
        ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
    )
}

Push-Location $posttechRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install and start Docker Desktop first.' }
    $sharedEnv = Join-Path $posttechRoot '.env'
    if (-not (Test-Path -LiteralPath $sharedEnv)) { throw 'Create .env with the existing Supabase settings; see .env.example.' }
    $engine = & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0 -or $engine -ne 'linux') { throw 'Start the Docker Linux engine, then retry.' }
    if ($PSBoundParameters.ContainsKey('Telegram') -and -not $Telegram) { throw 'This launcher only enables Telegram or preserves its current state. Omit -Telegram to keep the configured stack; disabling a running bot requires a separate stop.' }

    $statePath = Join-Path $posttechRoot '.local/portal-docker.json'
    $state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } else { $null }
    $projectsJson = & docker compose ls --all --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the current Docker project. Existing containers were not changed.' }
    $project = @($projectsJson | ConvertFrom-Json) | Where-Object { $_.Name -eq 'posttech' } | Select-Object -First 1
    $currentFiles = @()
    if ($project) {
        foreach ($file in ($project.ConfigFiles -split ',')) {
            $fullPath = [IO.Path]::GetFullPath($file.Trim())
            if ([IO.Path]::GetDirectoryName($fullPath) -ne $posttechRoot) { throw 'The posttech Docker project belongs to another folder. Existing containers were not changed.' }
            $name = [IO.Path]::GetFileName($fullPath)
            if ($name -notin @('compose.yaml', 'compose.telegram.yaml', 'compose.lan.yaml', 'compose.ai.yaml')) { throw 'The current project uses another Compose override. Start it with its original configuration.' }
            $currentFiles += $name
        }
        if ('compose.yaml' -notin $currentFiles) { throw 'The existing posttech project is not the Supabase portal stack.' }
    }

    $useTelegram = if ($PSBoundParameters.ContainsKey('Telegram')) { [bool]$Telegram } elseif ($project) { 'compose.telegram.yaml' -in $currentFiles } else { [bool]$state.telegram }
    $useLocalModel = if ($project) { 'compose.ai.yaml' -in $currentFiles } else { [bool]$state.local_model }
    if (-not $PSBoundParameters.ContainsKey('LanHost')) {
        $LanHost = if ($project) { '' } else { [string]$state.lan_host }
        if ('compose.lan.yaml' -in $currentFiles) {
            $ids = @(& docker ps --all --filter 'label=com.docker.compose.project=posttech' --filter 'label=com.docker.compose.service=frontend' --format '{{.ID}}')
            if ($LASTEXITCODE -ne 0 -or $ids.Count -ne 1) { throw 'Cannot recover the current LAN address. Retry with -LanHost <private IPv4>.' }
            $bindingsJson = & docker inspect --format '{{json .HostConfig.PortBindings}}' $ids[0]
            if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the frontend LAN binding.' }
            $bindings = $bindingsJson | ConvertFrom-Json
            $lanBindings = @($bindings.'80/tcp' | Where-Object { $_.HostPort -eq '8011' })
            if ($lanBindings.Count -ne 1) { throw 'Cannot recover the current LAN address. Retry with -LanHost <private IPv4>.' }
            $LanHost = [string]$lanBindings[0].HostIp
        }
    }
    if ($LanHost -and -not (Test-LanAddress $LanHost)) { throw 'LanHost must be a private IPv4 address of this computer, for example 192.168.1.5.' }
    $env:POSTTECH_LAN_HOST = $LanHost

    $compose = @('compose', '--project-name', 'posttech', '--env-file', $sharedEnv, '-f', 'compose.yaml')
    if ($useLocalModel) { $compose += @('-f', 'compose.ai.yaml') }
    if ($useTelegram) {
        $telegramEnv = Join-Path $posttechRoot '.local/telegram.env'
        if (-not (Test-Path -LiteralPath $telegramEnv)) {
            & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.13-slim python scripts/prepare_telegram.py
            if ($LASTEXITCODE -ne 0) { throw 'Could not prepare .local/telegram.env.' }
        }
        if (-not (Read-Setting $telegramEnv 'TELEGRAM_BOT_TOKEN')) { throw 'Save the BotFather token in .local/telegram.env, then run this launcher with -Telegram again. The existing portal was not changed.' }
        & docker run --rm --volume "${posttechRoot}:/workspace" --workdir /workspace python:3.13-slim python scripts/prepare_telegram.py --check
        if ($LASTEXITCODE -ne 0) { throw 'Telegram token verification failed. The existing portal was not changed.' }
        foreach ($key in $telegramKeys) { [Environment]::SetEnvironmentVariable($key, (Read-Setting $telegramEnv $key), 'Process') }
        $compose += @('-f', 'compose.telegram.yaml')
    }
    if ($LanHost) { $compose += @('-f', 'compose.lan.yaml') }

    Write-Host 'Building the current portal and starting its configured services...'
    & docker @compose up --detach --build --wait --wait-timeout $WaitSeconds
    if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. For Telegram, check the token and database migration 0019_telegram.sql. See docs/telegram.md.' }
    $publishedPorts = @(& docker @compose port frontend 80)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot determine the frontend port.' }
    $desktopPorts = @($publishedPorts | Where-Object { $_ -match '^127\.0\.0\.1:[0-9]+$' })
    if ($desktopPorts.Count -ne 1) { throw 'Cannot determine the desktop address. Check the frontend port binding.' }
    $url = 'http://' + $desktopPorts[0].Trim()
    $page = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch '/assets/.*\.js') { throw 'The frontend did not return the built portal.' }
    try {
        $ready = Invoke-RestMethod -Uri "$url/api/v1/health/ready" -TimeoutSec 30
        if ($ready.status -ne 'ready') { throw 'Database is not ready.' }
    } catch { throw 'The UI is running, but Supabase is not ready. Check credentials and the migration plan; see docs/docker.md.' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $statePath) -Force | Out-Null
    @{ telegram = $useTelegram; lan_host = $LanHost; local_model = $useLocalModel } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Host "PostTech is ready: $url"
    if ($useTelegram) { Write-Host 'Telegram worker is running. Connect an account in the portal settings.' }
    if ($LanHost) { Write-Host "Phone on the same network: http://${LanHost}:8011" }
    if ($OpenBrowser) { Start-Process -FilePath $url }
}
finally {
    $env:POSTTECH_LAN_HOST = $savedLanHost
    foreach ($key in $telegramKeys) { [Environment]::SetEnvironmentVariable($key, $savedTelegramEnvironment[$key], 'Process') }
    Pop-Location
}
