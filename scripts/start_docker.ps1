param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start_portal.ps1') -OpenBrowser:(-not $NoBrowser)
