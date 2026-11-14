# SPDX-License-Identifier: Apache-2.0
<#
.SYNOPSIS
    Shares the RTL-SDR dongle into WSL2 with usbipd-win.

.DESCRIPTION
    Finds the dongle by USB ID, binds it if needed (needs an administrator
    PowerShell the first time), then attaches it to WSL2 with --auto-attach.
    Leave the window open: auto-attach re-attaches the dongle after an unplug
    for as long as this script keeps running. Press Ctrl+C to stop.

.PARAMETER HardwareId
    USB vendor:product ID of the dongle. The default is the Realtek RTL2838.

.EXAMPLE
    .\scripts\windows\attach-sdr.ps1
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$')]
    [string]$HardwareId = '0bda:2838'
)

$ErrorActionPreference = 'Stop'

function Stop-WithError {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
    Stop-WithError ("usbipd-win is not installed. Install it, then open a new PowerShell window:`n" +
        "    winget install --exact dorssel.usbipd-win")
}

$vendorId, $productId = $HardwareId.ToUpper().Split(':')
$instancePattern = "VID_$vendorId&PID_$productId"

$state = usbipd state | ConvertFrom-Json
$device = @($state.Devices | Where-Object { $_.InstanceId -like "*$instancePattern*" -and $_.BusId })

if ($device.Count -eq 0) {
    Stop-WithError ("No connected USB device with ID $HardwareId was found. Plug in the RTL-SDR, " +
        "then run 'usbipd list' to check it shows up.")
}
if ($device.Count -gt 1) {
    Stop-WithError ("More than one device with ID $HardwareId is connected. Unplug the extras, " +
        "or attach one by hand: usbipd attach --wsl --busid <id> --auto-attach")
}

$busId = $device[0].BusId
Write-Host "Found $($device[0].Description) on bus ID $busId."

if (-not $device[0].PersistedGuid) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Stop-WithError ("The dongle is not shared yet. Binding needs administrator rights, once. " +
            "Open PowerShell as Administrator and run this script again, or run:`n" +
            "    usbipd bind --busid $busId")
    }
    Write-Host "Binding bus ID $busId (one-time step)..."
    usbipd bind --busid $busId
    if ($LASTEXITCODE -ne 0) { Stop-WithError "usbipd bind failed with exit code $LASTEXITCODE." }
}

if ($device[0].ClientIPAddress) {
    Write-Host "The dongle is already attached to WSL2. Detaching first so auto-attach can take over..."
    usbipd detach --busid $busId
}

Write-Host "Attaching to WSL2 with auto-attach. Keep this window open. Press Ctrl+C to stop."
Write-Host "Check from Ubuntu (WSL2) with: lsusb"
usbipd attach --wsl --busid $busId --auto-attach
if ($LASTEXITCODE -ne 0) {
    Stop-WithError ("usbipd attach failed with exit code $LASTEXITCODE. Make sure a WSL2 distribution " +
        "is running (open an Ubuntu terminal) and try again.")
}
