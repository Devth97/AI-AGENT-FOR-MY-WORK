$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'run.ps1'
foreach ($mode in @('research','send')) {
    $taskName = "Growplus-Outreach-$mode"
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) { throw "$taskName already exists. Inspect it before replacing it." }
}
foreach ($mode in @('research','send')) {
    $interval = if ($mode -eq 'research') { New-TimeSpan -Hours 6 } else { New-TimeSpan -Minutes 15 }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -Mode $mode" -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval $interval
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName "Growplus-Outreach-$mode" -Action $action -Trigger $trigger -Settings $settings -Description 'Growplus prospect research and one-at-a-time outreach; config controls sending.' | Out-Null
}
Write-Output 'Research every 6 hours; one send attempt every 15 minutes. Runs while this Windows user is logged in and the PC is awake.'
