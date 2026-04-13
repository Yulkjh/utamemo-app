@echo off
chcp 65001 >nul
echo ============================================================
echo   UTAMEMO Training - 自宅PC (RTX 4060 Ti 16GB)
echo ============================================================
echo.

REM === 設定 ===================================================
REM ダッシュボードURL (Render.comのURL)
set REPORT_URL=https://utamemo.onrender.com/api/training/update/

REM APIキー (Adminで TrainingSession を作成後、そのAPIキーをここに貼る)
set UTAMEMO_TRAINING_API_KEY=ここにAPIキーを貼る

REM モデル
set MODEL_NAME=Qwen/Qwen2.5-7B-Instruct

REM 出力先
set OUTPUT_DIR=C:\temp\utamemo-lora

REM エポック数
set EPOCHS=5

REM バッチサイズ (RTX 4060 Ti 16GB)
set BATCH_SIZE=1

REM 勾配蓄積
set GRAD_ACCUM=8
REM ===========================================================

echo [設定]
echo   モデル: %MODEL_NAME%
echo   出力先: %OUTPUT_DIR%
echo   エポック: %EPOCHS%
echo   バッチ: %BATCH_SIZE% x %GRAD_ACCUM%
echo   ダッシュボード: %REPORT_URL%
echo.

if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo 学習データを双方向同期中...
%PYTHON% sync_data.py sync --api_key "%UTAMEMO_TRAINING_API_KEY%" --base_url "https://utamemo.onrender.com"
if %ERRORLEVEL% EQU 0 (
    echo データ同期完了!
) else (
    echo データ同期失敗。ローカルデータで続行します。
)
echo.

if not exist "data\lyrics_training_data.json" (
    echo エラー: data\lyrics_training_data.json が見つかりません
    pause
    exit /b 1
)

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
    echo 学習完了! LoRA: %OUTPUT_DIR%
    echo 学習後データをサーバーにアップロード中...
    %PYTHON% sync_data.py push --api_key "%UTAMEMO_TRAINING_API_KEY%" --base_url "https://utamemo.onrender.com"
    if %ERRORLEVEL% EQU 0 (
        echo アップロード完了!
    ) else (
        echo アップロード失敗 (学習結果は保存済み)
    )
) else (
    echo エラーが発生しました (コード: %ERRORLEVEL%)
)
pause
