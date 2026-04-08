@echo off
chcp 65001 >nul
cd /d %~dp0

echo ========================================
echo   UTAMEMO Local Monitor Dashboard
echo ========================================

echo monitor_targets.json が無い場合は example から作成します
if not exist "monitor_targets.json" (
    copy /Y "monitor_targets.example.json" "monitor_targets.json" >nul
)

if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo 起動中... http://127.0.0.1:8765
%PYTHON% monitor_dashboard.py --host 127.0.0.1 --port 8765
pause
