$ErrorActionPreference = 'Stop'
$log = 'C:\Windows\Temp\zhirun-ics.log'
Set-Content -LiteralPath $log -Value "started $(Get-Date -Format o)"

try {
    $manager = New-Object -ComObject HNetCfg.HNetShare
    $publicConnection = $null
    $privateConnection = $null

    foreach ($connection in $manager.EnumEveryConnection()) {
        $properties = $manager.NetConnectionProps($connection)
        Add-Content -LiteralPath $log -Value "adapter=$($properties.Name)"
        if ($properties.Name -eq 'WLAN') { $publicConnection = $connection }
        if ($properties.Name -eq '以太网') { $privateConnection = $connection }
    }

    if (-not $publicConnection -or -not $privateConnection) {
        throw 'Required network adapters were not found.'
    }

    $manager.INetSharingConfigurationForINetConnection($publicConnection).EnableSharing(0)
    $manager.INetSharingConfigurationForINetConnection($privateConnection).EnableSharing(1)
    Add-Content -LiteralPath $log -Value 'sharing_enabled'
} catch {
    Add-Content -LiteralPath $log -Value "error=$($_.Exception.Message)"
    exit 1
}
