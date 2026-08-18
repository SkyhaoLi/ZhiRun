$ErrorActionPreference = 'Stop'

Set-Service -Name SharedAccess -StartupType Automatic
Start-Service -Name SharedAccess

$existing = Get-NetNat -Name 'ZhiRunAtlasNAT' -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetNat -Name 'ZhiRunAtlasNAT' -InternalIPInterfaceAddressPrefix '192.168.137.0/24' | Out-Null
}

Get-NetNat -Name 'ZhiRunAtlasNAT' | Select-Object Name, InternalIPInterfaceAddressPrefix
