param(
    [ValidateRange(2048, 16384)][int]$ContextSize = 12288,
    [ValidateRange(0, 99)][int]$GpuLayers = 99,
    [ValidateRange(1, 8)][int]$Threads = 4
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'prepare_jana_reader.py') --verify-only
if ($LASTEXITCODE -ne 0) { throw 'Prepare the local reader first: python scripts/prepare_jana_reader.py' }
$readerRoot = Join-Path $projectRoot '.models\reader'
$manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'knowledge_base\reader-model.json') -Raw | ConvertFrom-Json
if (-not $PSBoundParameters.ContainsKey('ContextSize')) { $ContextSize = [int]$manifest.server.context_size }
if (-not $PSBoundParameters.ContainsKey('GpuLayers')) { $GpuLayers = [int]$manifest.server.gpu_layers }
if (-not $PSBoundParameters.ContainsKey('Threads')) { $Threads = [int]$manifest.server.threads }
if ($ContextSize -lt 2048 -or $ContextSize -gt 16384 -or $GpuLayers -lt 0 -or $GpuLayers -gt 99 -or $Threads -lt 1 -or $Threads -gt 8) {
    throw 'Local reader settings exceed the resource bounds supported by this launcher.'
}
$serverFiles = @(Get-ChildItem -LiteralPath (Join-Path $readerRoot 'runtime') -Filter 'llama-server.exe' -Recurse)
if ($serverFiles.Count -ne 1) { throw 'Expected exactly one verified llama-server.exe' }
$serverPath = $serverFiles[0].FullName
$modelPath = Join-Path $readerRoot $manifest.model.filename
$probe = [System.Net.Sockets.TcpClient]::new()
$portInUse = $false
try {
    $probe.Connect('127.0.0.1', 8081)
    $portInUse = $true
} catch [System.Net.Sockets.SocketException] {
    # A refused loopback connection means the port is available; no admin rights needed.
} finally {
    $probe.Dispose()
}
if ($portInUse) {
    throw 'Port 8081 is already in use. Reuse the existing local reader or stop that process explicitly.'
}
# No remote host switch: the model endpoint must remain private to this computer.
$arguments = @(
    '--model', ('"' + $modelPath + '"'), '--alias', 'jana-reader',
    '--host', '127.0.0.1', '--port', '8081',
    '--ctx-size', "$ContextSize", '--parallel', '1',
    '--threads', "$Threads", '--threads-batch', "$Threads",
    '--gpu-layers', "$GpuLayers", '--batch-size', '512', '--ubatch-size', '128',
    '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0',
    '--flash-attn', 'on', '--jinja', '--reasoning', 'off',
    '--no-ui', '--no-agent', '--no-context-shift',
    '--cors-origins', 'http://127.0.0.1:8081', '--no-cors-credentials'
)
$stdoutPath = Join-Path $readerRoot 'server.out.log'
$stderrPath = Join-Path $readerRoot 'server.err.log'
$process = Start-Process -FilePath $serverPath -ArgumentList $arguments -WorkingDirectory $serverFiles[0].DirectoryName -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $readerRoot 'server.pid') -Encoding ascii
Write-Output "Jana reader started: PID $($process.Id), http://127.0.0.1:8081, model jana-reader"
Write-Output "Readiness: http://127.0.0.1:8081/health; logs: $stderrPath"
