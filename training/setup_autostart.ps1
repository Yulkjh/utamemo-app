<#
.SYNOPSIS
    UTAMEMO Training Agent をWindowsタスクスケジューラに登録する
.DESCRIPTION
    PC起動・ログオン時に自動でトレーニングエージェントを起動する
    管理者権限で実行してください
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
#>

$ErrorActionPreference = "Stop"

$taskName = "UTAMEMO-Training-Agent"
$batPath = Join-Path $PSScriptRoot "autostart_agent.bat"

if (-not (Test-Path $batPath)) {
    Write-Error "autostart_agent.bat が見つかりません: $batPath"
    exit 1
}

# 既存タスクがあれば削除
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "既存タスク '$taskName' を更新します..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# アクション: バッチファイルを実行
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $PSScriptRoot

# トリガー: ログオン時
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# 設定
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# 登録
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "UTAMEMO LLM Training Agent - PC起動時に自動起動。https://utamemo.com/staff/training/ から操作" `
    -RunLevel Highest

Write-Host ""
Write-Host "====================================" -ForegroundColor Green
Write-Host " 登録完了!" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host ""
Write-Host "タスク名: $taskName"
Write-Host "トリガー: ログオン時 ($env:USERNAME)"
Write-Host ""
Write-Host "確認: タスクスケジューラ > $taskName"
Write-Host "手動実行: schtasks /run /tn $taskName"
Write-Host "削除: schtasks /delete /tn $taskName /f"
Write-Host ""
Write-Host "次回PC起動時から自動でエージェントが起動します。" -ForegroundColor Cyan
Write-Host "スマホから https://utamemo.com/staff/training/ で操作できます。" -ForegroundColor Cyan
