@echo off
chcp 65001 >nul
echo ============================================================
echo   UTAMEMO Training - 学校PC
echo ============================================================
echo.

REM === 設定 ===================================================
REM ダッシュボードURL (Render.comのURL)
set REPORT_URL=https://utamemo.onrender.com/api/training/update/

REM APIキー (Adminで TrainingSession を作成後、そのAPIキーをここに貼る)
set UTAMEMO_TRAINING_API_KEY=ここにAPIキーを貼る

REM モデル
set MODEL_NAME=Qwen/Qwen2.5-7B-Instruct

REM 出力先 (学校PCのローカルドライブ)
set OUTPUT_DIR=C:\temp\utamemo-lora

REM エポック数
set EPOCHS=5

REM バッチサイズ (学校PCのGPUに合わせる)
set BATCH_SIZE=1

REM 勾配蓄積
set GRAD_ACCUM=8
REM ===========================================================

echo [設定]
echo   モデル: %MODEL_NAME%
echo   出力先: %OUTPUT_DIR%
echo   エポック: %EPOCHS%
echo   バッチ: %BATCH_SIZE% x %GRAD_ACCUM% = 実効%BATCH_SIZE%x%GRAD_ACCUM%
echo   ダッシュボード: %REPORT_URL%
echo.

REM venv が存在するか確認
if exist "venv\Scripts\python.exe" (
    echo venv を使用します
    set PYTHON=venv\Scripts\python.exe
) else (
    echo システムの python を使用します
    set PYTHON=python
)

REM 学習データの確認
if not exist "data\lyrics_training_data.json" (
    echo エラー: data\lyrics_training_data.json が見つかりません
    echo training フォルダに移動して実行してください
    pause
    exit /b 1
)

echo.
echo 学習を開始します... (Ctrl+C で中断)
echo.

%PYTHON% -u train.py ^
    --data_path data/lyrics_training_data.json ^
    --model_name %MODEL_NAME% ^
    --epochs %EPOCHS% ^
    --batch_size %BATCH_SIZE% ^
    --gradient_accumulation %GRAD_ACCUM% ^
    --output_dir "%OUTPUT_DIR%" ^
    --report_url "%REPORT_URL%" ^
    --api_key "%UTAMEMO_TRAINING_API_KEY%"

echo.
if %ERRORLEVEL% EQU 0 (
    echo ============================================================
    echo   学習完了!
    echo   LoRA: %OUTPUT_DIR%
    echo ============================================================
) else (
    echo ============================================================
    echo   エラーが発生しました (コード: %ERRORLEVEL%)
    echo ============================================================
)
pause
