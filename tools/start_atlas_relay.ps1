param(
    [string]$BindAddress = '192.168.137.1',
    [string]$AtlasHost = '192.168.137.100',
    [string]$Upstream = 'http://47.92.195.5',
    [int]$Port = 18080
)

$ErrorActionPreference = 'Stop'
$createdNew = $false
$mutex = [Threading.Mutex]::new($true, 'Local\ZhiRunAtlasRelay', [ref]$createdNew)
if (-not $createdNew) {
    exit 0
}

try {
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $relay = (Resolve-Path (Join-Path $PSScriptRoot '..\edge\atlas_push_relay.js')).Path
    $logDirectory = Join-Path $env:LOCALAPPDATA 'ZhiRun'
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $logPath = Join-Path $logDirectory 'atlas-relay.log'

    while ($true) {
        & $node $relay --bind $BindAddress --port $Port --atlas-host $AtlasHost --upstream $Upstream *>> $logPath
        "[$(Get-Date -Format o)] relay stopped; restarting in 5 seconds" | Add-Content -LiteralPath $logPath
        Start-Sleep -Seconds 5
    }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
