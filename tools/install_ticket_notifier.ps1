param(
    [string]$SiteUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "ticket_notifier.py"
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $pythonw = Join-Path (Split-Path $python) "pythonw.exe"
}
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "pythonw.exe was not found. Install Python for Windows and try again."
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"{0}"' -f $scriptPath) -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "IT Service Ticket Notifications" -Action $action -Trigger $trigger -Settings $settings -Description "Polls $SiteUrl and shows Windows notifications for new IT tickets." -Force | Out-Null
Start-ScheduledTask -TaskName "IT Service Ticket Notifications"
Write-Output "Ticket notifications are installed and running. They will start again when you sign in to Windows."
