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
set GEN_COUNT=5
set LOG_FILE=%PROJECT_DIR%\training\agent.log

REM --- APIキーは .env ファイルから読み込む ---
set ENV_FILE=%PROJECT_DIR%\training\.env
if exist "%ENV_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        if "%%A"=="UTAMEMO_API_KEY" set API_KEY=%%B
        if "%%A"=="GEMINI_API_KEY" set GEMINI_KEY=%%B
    )
)
if "%API_KEY%"=="" (
    echo エラー: training\.env にUTAMEMO_API_KEYが未設定です
    echo   training\.env.example を参考に .env を作成してください
    pause
    exit /b 1
)

REM --- serve.py 用に環境変数をセット ---
set UTAMEMO_API_KEY=%API_KEY%
set GEMINI_API_KEY=%GEMINI_KEY%
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

set PYTHONIOENCODING=utf-8

%PYTHON% -u training\training_agent.py ^
    --api_key %API_KEY% ^
    --report_url %REPORT_URL% ^
    --gemini_key %GEMINI_KEY% ^
    --gen_count %GEN_COUNT% >> "%LOG_FILE%" 2>&1

echo.
echo [%date% %time%] エージェントが停止しました。10秒後に自動再起動...
echo [%date% %time%] Agent stopped, restarting... >> "%LOG_FILE%"
timeout /t 10 /nobreak >nul
goto loop
