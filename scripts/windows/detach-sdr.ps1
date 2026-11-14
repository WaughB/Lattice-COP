# SPDX-License-Identifier: Apache-2.0
<#
.SYNOPSIS
    Returns the RTL-SDR dongle from WSL2 to Windows.

.DESCRIPTION
    Detaches the dongle found by USB ID. Close any attach-sdr.ps1 window first,
    or auto-attach will attach it again. Add -Unbind to also stop sharing the
    device (needs an administrator PowerShell).

.PARAMETER HardwareId
    USB vendor:product ID of the dongle. The default is the Realtek RTL2838.

.PARAMETER Unbind
    Also remove the usbipd binding, so the device is no longer shared.

.EXAMPLE
    .\scripts\windows\detach-sdr.ps1
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$')]
    [string]$HardwareId = '0bda:2838',
    [switch]$Unbind
)

$ErrorActionPreference = 'Stop'

function Stop-WithError {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
    Stop-WithError "usbipd-win is not installed, so there is nothing to detach."
}

$vendorId, $productId = $HardwareId.ToUpper().Split(':')
$instancePattern = "VID_$vendorId&PID_$productId"

$state = usbipd state | ConvertFrom-Json
$devices = @($state.Devices | Where-Object { $_.InstanceId -like "*$instancePattern*" })

if ($devices.Count -eq 0) {
    Write-Host "No device with ID $HardwareId is known to usbipd. Nothing to do."
    exit 0
}

foreach ($device in $devices) {
    if ($device.BusId -and $device.ClientIPAddress) {
        Write-Host "Detaching bus ID $($device.BusId)..."
        usbipd detach --busid $device.BusId
        if ($LASTEXITCODE -ne 0) { Stop-WithError "usbipd detach failed with exit code $LASTEXITCODE." }
    }
    else {
        Write-Host "The dongle is not attached to WSL2."
    }

    if ($Unbind -and $device.PersistedGuid) {
        Write-Host "Removing the usbipd binding (needs administrator rights)..."
        usbipd unbind --guid $device.PersistedGuid
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError "usbipd unbind failed. Run this script from an administrator PowerShell."
        }
    }
}

Write-Host "Done."
