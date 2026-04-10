<#
.SYNOPSIS
    Register UTAMEMO Training Agent in Windows Task Scheduler
.DESCRIPTION
    Auto-start the training agent on PC boot/logon.
    Run with administrator privileges.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
#>

$ErrorActionPreference = "Stop"

$taskName = "UTAMEMO-Training-Agent"
$batPath = Join-Path $PSScriptRoot "autostart_agent.bat"

if (-not (Test-Path $batPath)) {
    Write-Error "autostart_agent.bat not found: $batPath"
    exit 1
}

# æ—¢å­˜ã‚¿ã‚¹ã‚¯ãŒã‚ã‚Œã°å‰Šé™¤
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Updating existing task '$taskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# ã‚¢ã‚¯ã‚·ãƒ§ãƒ³: ãƒãƒƒãƒãƒ•ã‚¡ã‚¤ãƒ«ã‚’å®Ÿè¡Œ
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $PSScriptRoot

# ãƒˆãƒªã‚¬ãƒ¼: ãƒ­ã‚°ã‚ªãƒ³æ™‚
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# è¨­å®š
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# ç™»éŒ²
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "UTAMEMO LLM Training Agent - Auto-start on boot. Control from https://utamemo.com/staff/training/" `
    -RunLevel Highest

Write-Host ""
Write-Host "====================================" -ForegroundColor Green
Write-Host " Registration Complete!" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host ""
Write-Host "Task: $taskName"
Write-Host "Trigger: At logon ($env:USERNAME)"
Write-Host ""
Write-Host "Check: Task Scheduler > $taskName"
Write-Host "Run manually: schtasks /run /tn $taskName"
Write-Host "Delete: schtasks /delete /tn $taskName /f"
Write-Host ""
Write-Host "Agent will auto-start on next PC boot." -ForegroundColor Cyan
Write-Host "Control from: https://utamemo.com/staff/training/" -ForegroundColor Cyan
