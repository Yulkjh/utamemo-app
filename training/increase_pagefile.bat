@echo off
:: ページファイルを32GB-64GBに増加するスクリプト
:: 右クリック → 管理者として実行
::
:: ※再起動後に反映されます

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 管理者権限で再起動します...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo =============================================
echo   ページファイルサイズ変更ツール
echo =============================================
echo.
echo 現在のページファイル:
wmic pagefile list brief
echo.

:: 自動管理を無効化
wmic computersystem where name="%COMPUTERNAME%" set AutomaticManagedPagefile=False
echo.

:: ページファイルを32GB初期/64GB最大に設定
wmic pagefileset where name="C:\\pagefile.sys" set InitialSize=32768,MaximumSize=65536
echo.

echo =============================================
echo   設定完了！PCを再起動してください。
echo   再起動後に仮想メモリが 32-64GB に増えます。
echo =============================================
echo.
pause
