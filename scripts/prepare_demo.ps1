param(
    [switch]$Gpu,
    [switch]$StayAwake,
    [ValidateRange(1, 120)][int]$Minutes = 20,
    [ValidateRange(30, 180)][int]$PreflightTimeoutSeconds = 90,
    [ValidateRange(0, 900)][int]$WaitSeconds = 600
)

# Read-only preflight. Does not start/rebuild containers, run inference, send
# Telegram messages, create HR records, edit env files or change power plans.
$ErrorActionPreference = 'Stop'
$posttechRoot = Split-Path -Parent $PSScriptRoot
$reportPath = Join-Path $posttechRoot '.local\demo-preflight.json'
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$checks = New-Object 'System.Collections.Generic.List[object]'
$guardActive = $false
$report = [ordered]@{ checked_at = (Get-Date).ToUniversalTime().ToString('o'); mode = 'read_only'; result = 'running'; inference_tested = $false; messages_sent = $false; checks = @() }

function Save-Report {
    if (Test-Path -LiteralPath (Split-Path -Parent $reportPath)) {
        $report.checks = @($checks.ToArray())
        $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    }
}

function Confirm-Check([string]$Name, [bool]$Passed) {
    $checks.Add([ordered]@{ name = $Name; passed = $Passed })
    Save-Report
    if (-not $Passed) { throw "Check failed: $Name" }
    Write-Host "OK: $Name"
}

function Invoke-DockerBounded([string[]]$Arguments) {
    $remaining = $PreflightTimeoutSeconds - $watch.Elapsed.TotalSeconds
    if ($remaining -le 0) { throw 'Preflight time limit reached. No changes were made.' }
    # All arguments are fixed commands or existing workspace paths, never secrets.
    # Windows paths cannot contain a double quote. Python snippets use single quotes.
    $quoted = foreach ($argument in $Arguments) {
        if ($argument.Contains('"') -or $argument.EndsWith('\')) { throw 'Unsupported command argument.' }
        '"' + $argument + '"'
    }
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = (Get-Command docker -ErrorAction Stop).Source
    $info.Arguments = $quoted -join ' '
    $info.WorkingDirectory = $posttechRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit([int]([Math]::Min(20, $remaining) * 1000))) {
            try { $process.Kill() } catch { }
            throw 'Docker check timed out. Existing containers were not stopped.'
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw 'Docker check failed. Inspect service status; no configuration was changed.' }
        # Do not echo captured stderr: a library error could contain a private URL.
        return $stdout.GetAwaiter().GetResult().Trim()
    }
    finally { $process.Dispose() }
}

function Get-LocalPage([string]$Path) {
    $remaining = $PreflightTimeoutSeconds - $watch.Elapsed.TotalSeconds
    if ($remaining -le 0) { throw 'Preflight time limit reached. No changes were made.' }
    try {
        Invoke-WebRequest -Uri ($posttechUrl + $Path) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec ([int][Math]::Max(1, [Math]::Min(10, $remaining)))
    }
    catch { throw "Local portal did not answer: $Path" }
}

function Wait-JanaWarmup {
    $passwordLine = Get-Content -LiteralPath $dockerEnv | Where-Object { $_ -match '^POSTTECH_DEMO_PASSWORD=' } | Select-Object -First 1
    if (-not $passwordLine) { throw 'Local demo login is not configured.' }
    $password = ($passwordLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
    $payload = @{ email = 'employee@posttech.demo'; password = $password } | ConvertTo-Json -Compress
    try {
        $login = Invoke-WebRequest -Uri ($posttechUrl + '/api/v1/auth/login') -Method Post -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($payload)) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 15
        $token = ($login.Content | ConvertFrom-Json).access_token
    }
    catch { throw 'Local demo sign-in failed. Check the local Auth service and demo account.' }
    if (-not $token) { throw 'Local demo sign-in did not return a session.' }
    $headers = @{ Authorization = "Bearer $token" }
    $warmupWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $lastState = ''
    try {
        do {
            $timeout = if ($WaitSeconds -eq 0) { 10 } else { [int][Math]::Max(1, [Math]::Min(10, $WaitSeconds - $warmupWatch.Elapsed.TotalSeconds)) }
            $state = 'unavailable'
            try {
                $response = Invoke-WebRequest -Uri ($posttechUrl + '/api/v1/ai/status') -Headers $headers -UseBasicParsing -MaximumRedirection 0 -TimeoutSec $timeout
                $status = $response.Content | ConvertFrom-Json
                if ($status.state -notin @('warming', 'ready', 'unavailable', 'disabled')) { throw 'Unexpected warm-up status.' }
                $state = $status.state
                if ($state -eq 'ready' -and $status.enabled -ne $true) { $state = 'disabled' }
            }
            catch {
                $httpStatus = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
                if ($httpStatus -in @(401, 403, 404)) { throw 'Authenticated Jana status is not available. Rebuild the current API and check the local account.' }
            }
            if ($state -ne $lastState) { Write-Host "Jana warm-up: $state"; $lastState = $state }
            $report.jana_state = $state
            if ($state -eq 'disabled') { throw 'Jana warm-up is disabled. Start the current Docker configuration with JANA_WARMUP_ENABLED=true; see docs/telegram-demo.md.' }
            if ($state -eq 'ready') {
                $report.warmup_wait_seconds = [Math]::Round($warmupWatch.Elapsed.TotalSeconds, 2)
                Confirm-Check 'Authenticated Jana warm-up ready' $true
                return
            }
            if ($WaitSeconds -eq 0 -or $warmupWatch.Elapsed.TotalSeconds -ge $WaitSeconds) { break }
            Start-Sleep -Seconds ([int][Math]::Max(1, [Math]::Min(5, $WaitSeconds - $warmupWatch.Elapsed.TotalSeconds)))
        } while ($warmupWatch.Elapsed.TotalSeconds -lt $WaitSeconds)
        throw 'Jana did not finish warming within the limit. Do not describe the AI as ready; inspect the reader and retry preflight.'
    }
    finally { $headers = $null; $token = $null; $password = $null; $payload = $null }
}

try {
    if ($StayAwake) {
        if (-not ('PostTechDemoPower' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PostTechDemoPower {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
        }
        if ([PostTechDemoPower]::SetThreadExecutionState([uint32]2147483651) -eq 0) { throw 'Windows could not enable the temporary sleep guard.' }
        $guardActive = $true
        Write-Host 'Temporary sleep/display guard enabled during preflight. Ctrl+C releases it.'
    }
    $dockerEnv = Join-Path $posttechRoot '.local\docker.env'
    $telegramEnv = Join-Path $posttechRoot '.local\telegram.env'
    Confirm-Check 'Private local configuration files exist' ((Test-Path -LiteralPath $dockerEnv) -and (Test-Path -LiteralPath $telegramEnv))
    $projectLine = Get-Content -LiteralPath $dockerEnv | Where-Object { $_ -match '^COMPOSE_PROJECT_NAME=' } | Select-Object -First 1
    Confirm-Check 'Isolated local project selected' ($projectLine -eq 'COMPOSE_PROJECT_NAME=posttech-local')
    $portLine = Get-Content -LiteralPath $dockerEnv | Where-Object { $_ -match '^POSTTECH_HTTP_PORT=' } | Select-Object -First 1
    $port = 0
    Confirm-Check 'Local port configured' ($portLine -and [int]::TryParse(($portLine -split '=', 2)[1], [ref]$port) -and $port -gt 0 -and $port -lt 65536)
    $posttechUrl = "http://127.0.0.1:$port"
    $report.base_url = $posttechUrl
    Confirm-Check 'Docker Linux engine available' ((Invoke-DockerBounded @('info', '--format', '{{.OSType}}')) -eq 'linux')
    $compose = @('compose', '--env-file', $dockerEnv, '--env-file', $telegramEnv, '-f', 'compose.demo.yaml')
    if ($Gpu) { $compose += @('-f', 'compose.gpu.yaml') }
    $compose += @('-f', 'compose.telegram.yaml')
    $raw = Invoke-DockerBounded ($compose + @('ps', '--all', '--format', 'json'))
    $services = @()
    if ($raw.TrimStart().StartsWith('[')) { $services = @($raw | ConvertFrom-Json) }
    else { $services = @($raw -split "`r?`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }) }
    foreach ($name in @('db', 'auth', 'rest', 'supabase', 'api', 'frontend', 'jana-reader', 'telegram-bot', 'workflow-worker')) {
        $serviceRows = @($services | Where-Object { $_.Service -eq $name })
        $ready = $serviceRows.Count -eq 1 -and $serviceRows[0].State -eq 'running'
        if ($name -ne 'workflow-worker') { $ready = $ready -and $serviceRows[0].Health -eq 'healthy' }
        Confirm-Check "Service ready: $name" $ready
    }
    $portal = Get-LocalPage '/'
    Confirm-Check 'Built portal responds' ($portal.StatusCode -eq 200 -and $portal.Content -match '/assets/.*\.js')
    $ready = (Get-LocalPage '/api/v1/health/ready').Content | ConvertFrom-Json
    Confirm-Check 'API database readiness' ($ready.status -eq 'ready')
    $reader = "import json,urllib.request; r=json.load(urllib.request.urlopen('http://jana-reader:8081/health',timeout=8)); assert r.get('status')=='ok'; print('ready')"
    Confirm-Check 'Jana model process ready (not an inference speed test)' ((Invoke-DockerBounded ($compose + @('exec', '-T', 'api', 'python', '-c', $reader))) -eq 'ready')
    $heartbeat = "import pathlib,time; p=pathlib.Path('/tmp/telegram-worker-heartbeat'); assert p.exists() and 0<=time.time()-float(p.read_text())<180; print('fresh')"
    Confirm-Check 'Telegram worker heartbeat fresh' ((Invoke-DockerBounded ($compose + @('exec', '-T', 'telegram-bot', 'python', '-c', $heartbeat))) -eq 'fresh')
    $getMe = "import json,os,urllib.request; token=os.environ['TELEGRAM_BOT_TOKEN']; req=urllib.request.Request('https://api.telegram.org/bot'+token+'/getMe',data=b'',method='POST'); r=json.load(urllib.request.urlopen(req,timeout=10)); assert r.get('ok') and r.get('result',{}).get('is_bot'); print('reachable')"
    Confirm-Check 'Telegram reachable: read-only getMe, no messages' ((Invoke-DockerBounded ($compose + @('exec', '-T', 'telegram-bot', 'python', '-c', $getMe))) -eq 'reachable')
    $report.preflight_seconds = [Math]::Round($watch.Elapsed.TotalSeconds, 2)
    Wait-JanaWarmup
    $report.result = 'passed'
    Save-Report
    Write-Host "Preflight passed: $posttechUrl"
    Write-Host 'Warm-up is ready. Rehearse an answer, its source and an unknown fact; readiness does not guarantee a fixed answer time.'
    Write-Host 'Report: .local/demo-preflight.json'

    if ($StayAwake) {
        $until = (Get-Date).AddMinutes($Minutes)
        Write-Host "Temporary sleep/display guard active for $Minutes minutes. Keep this terminal open; Ctrl+C stops the guard."
        Write-Host 'Keep power and internet connected. Do not close the lid or select Sleep manually.'
        while ((Get-Date) -lt $until) { Start-Sleep -Seconds 1 }
    }
}
catch {
    if ($report.result -ne 'passed') { $report.result = 'failed' }
    $report.error = $_.Exception.Message
    Save-Report
    Write-Error $_.Exception.Message
    exit 1
}
finally {
    if ($guardActive) {
        [void][PostTechDemoPower]::SetThreadExecutionState([uint32]2147483648)
        Write-Host 'Temporary sleep/display guard released. The Windows power plan was not changed.'
    }
}
