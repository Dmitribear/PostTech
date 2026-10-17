param([int]$Port = 8010, [switch]$NoBrowser, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$posttechRoot = Split-Path -Parent $PSScriptRoot
$posttechPython = Join-Path $posttechRoot '.venv\Scripts\python.exe'
$posttechServerScript = Join-Path $PSScriptRoot 'serve_jury.py'
$posttechLocal = Join-Path $posttechRoot '.local'
$posttechStatePath = Join-Path $posttechLocal "jury-server-$Port.json"
$posttechUrl = "http://127.0.0.1:$Port"
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Use a port from 1024 to 65535.' }
New-Item -ItemType Directory -Force -Path $posttechLocal | Out-Null
$posttechOwned = $null
if (Test-Path -LiteralPath $posttechStatePath) {
    $posttechSaved = Get-Content -LiteralPath $posttechStatePath -Raw | ConvertFrom-Json
    $posttechCandidate = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$posttechSaved.pid)" -ErrorAction SilentlyContinue
    if ($posttechCandidate -and $posttechCandidate.CommandLine.Contains($posttechServerScript)) { $posttechOwned = $posttechCandidate }
}
if ($Stop) {
    if ($posttechOwned) { Stop-Process -Id $posttechOwned.ProcessId; Write-Output 'PostTech stopped.' }
    else { Write-Output 'No matching PostTech process. Other processes were not changed.' }
    exit 0
}
if (-not (Test-Path -LiteralPath $posttechPython)) { throw 'Prepare .venv first. See docs/jury-stand.md.' }
if (-not (Test-Path -LiteralPath (Join-Path $posttechRoot 'frontend\dist\index.html'))) { throw 'Build the frontend first: npm ci; npm run build (in frontend).' }
if (-not (Test-Path -LiteralPath (Join-Path $posttechRoot '.env'))) { throw 'Configure the private .env file first.' }
if (-not $posttechOwned) {
    $posttechListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($posttechListener) { throw "Port $Port is occupied by another process. Choose -Port or stop that process yourself." }
    $posttechProcess = Start-Process -FilePath $posttechPython -ArgumentList ('"' + $posttechServerScript + '"'), '--port', $Port -WorkingDirectory $posttechRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $posttechLocal "jury-$Port.stdout.log") -RedirectStandardError (Join-Path $posttechLocal "jury-$Port.stderr.log") -PassThru
    @{ pid = $posttechProcess.Id; port = $Port } | ConvertTo-Json | Set-Content -LiteralPath $posttechStatePath -Encoding UTF8
}
$posttechReady = $false
for ($posttechAttempt = 0; $posttechAttempt -lt 20; $posttechAttempt++) {
    try {
        $posttechResponse = Invoke-RestMethod "$posttechUrl/api/v1/health/ready" -TimeoutSec 5
        if ($posttechResponse.status -eq 'ready') { $posttechReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $posttechReady) { throw 'PostTech is not ready. Check Supabase connectivity, migration 0006 and the local server log.' }
Write-Output "PostTech ready: $posttechUrl"
if (-not $NoBrowser) { Start-Process $posttechUrl }
