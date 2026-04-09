@echo off
chcp 65001 >nul
title UTAMEMO Training Agent

REM ============================================================
REM  UTAMEMO Training Agent - 完全自動起動スクリプト
REM  PC起動時にタスクスケジューラから自動実行される
REM  スマホから https://utamemo.com/staff/training/ で操作可能
REM ============================================================

REM === 設定 ===================================================
set PROJECT_DIR=C:\Users\YU\OneDrive\デスクトップ\UTAMEMO
set REPORT_URL=https://utamemo.com/api/training/update/
set API_KEY=fc07b6d36ebebc9141bf37a5ceb0e8fe5656f55cfa8a3f0b5b95f329eca6e12f
set GEMINI_KEY=AIzaSyAagi0pgFhVh4E_quS1iGKb6RotBKpWhHw
set GEN_COUNT=5
set LOG_FILE=%PROJECT_DIR%\training\agent.log
REM ===========================================================

cd /d "%PROJECT_DIR%"

REM --- 最新コードを取得 ---
echo [%date% %time%] Git pull... >> "%LOG_FILE%"
git pull origin main 2>&1 >> "%LOG_FILE%"

REM --- venv の Python を検出 ---
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else if exist "training\venv\Scripts\python.exe" (
    set PYTHON=training\venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM --- 依存パッケージ確認 (初回のみ時間がかかる) ---
echo [%date% %time%] pip check... >> "%LOG_FILE%"
%PYTHON% -m pip install -r training\requirements_training.txt --quiet 2>&1 >> "%LOG_FILE%"

REM --- エージェント起動 (クラッシュ時は自動再起動) ---
:loop
echo.
echo ============================================================
echo  [%date% %time%] UTAMEMO Training Agent 起動
echo  スマホから操作: https://utamemo.com/staff/training/
echo  停止: Ctrl+C または ダッシュボードの「停止」ボタン
echo ============================================================
echo.

echo [%date% %time%] Agent starting... >> "%LOG_FILE%"

%PYTHON% -u training\training_agent.py ^
    --api_key %API_KEY% ^
    --report_url %REPORT_URL% ^
    --gemini_key %GEMINI_KEY% ^
    --gen_count %GEN_COUNT%

echo.
echo [%date% %time%] エージェントが停止しました。10秒後に自動再起動...
echo [%date% %time%] Agent stopped, restarting... >> "%LOG_FILE%"
timeout /t 10 /nobreak >nul
goto loop
