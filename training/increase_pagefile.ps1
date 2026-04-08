# ページファイルサイズ増加スクリプト (管理者権限で実行)
# 右クリック > 「PowerShellで実行」> UAC許可

$ErrorActionPreference = "Stop"

Write-Host "=== ページファイルサイズ変更 ===" -ForegroundColor Cyan
Write-Host ""

# 管理者チェック
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "管理者権限が必要です。管理者として再起動します..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

# 現在の設定を表示
Write-Host "現在のページファイル:" -ForegroundColor Yellow
wmic pagefile list /format:list | Where-Object { $_ -ne "" }

# 自動管理を無効化
$cs = Get-CimInstance -ClassName Win32_ComputerSystem
if ($cs.AutomaticManagedPagefile) {
    Write-Host "`n自動管理を無効化中..." -ForegroundColor Yellow
    Set-CimInstance -InputObject $cs -Property @{AutomaticManagedPagefile=$false}
    Write-Host "  完了" -ForegroundColor Green
}

# ページファイルを32GB初期/64GB最大に設定
try {
    $pf = Get-CimInstance -ClassName Win32_PageFileSetting -Filter 'Name="C:\\pagefile.sys"' -ErrorAction SilentlyContinue
    if ($pf) {
        Set-CimInstance -InputObject $pf -Property @{InitialSize=32768; MaximumSize=65536}
    } else {
        New-CimInstance -ClassName Win32_PageFileSetting -Property @{Name="C:\pagefile.sys"; InitialSize=32768; MaximumSize=65536}
    }
    Write-Host "`nページファイルを 32GB-64GB に設定しました!" -ForegroundColor Green
    Write-Host "再起動後に反映されます。" -ForegroundColor Yellow
} catch {
    Write-Host "エラー: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Enterで閉じます..." -ForegroundColor Gray
Read-Host
