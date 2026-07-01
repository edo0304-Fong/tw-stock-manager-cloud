@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title 台股持股管理系統 MVP 啟動器

echo ========================================
echo 台股持股管理系統 MVP 啟動器
echo 目前資料夾：%cd%
echo ========================================
echo.

REM 檢查是否從壓縮檔暫存位置執行
if not exist "app.py" (
  echo [錯誤] 找不到 app.py。
  echo 請先將 tw_stock_manager_mvp.zip 完整解壓縮到桌面或文件資料夾，
  echo 再進入 tw_stock_manager_mvp 資料夾執行本檔案。
  echo.
  pause
  exit /b 1
)

REM 找 Python：優先 python，其次 py -3
where python >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=python"
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
  ) else (
    echo [錯誤] 找不到 Python。
    echo 請先安裝 Python 3.10 以上，安裝時記得勾選 Add python.exe to PATH。
    echo 下載位置：https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
  )
)

echo [1/4] 使用的 Python：!PYTHON_CMD!
!PYTHON_CMD! --version
if %errorlevel% neq 0 (
  echo [錯誤] Python 可以找到，但無法正常執行。
  pause
  exit /b 1
)

echo.
echo [2/4] 建立虛擬環境 .venv
if not exist ".venv\Scripts\activate.bat" (
  !PYTHON_CMD! -m venv .venv
  if %errorlevel% neq 0 (
    echo [錯誤] 建立虛擬環境失敗。
    echo 可能原因：Python 安裝不完整，或 Microsoft Store 版本 Python 異常。
    pause
    exit /b 1
  )
) else (
  echo 已存在 .venv，略過建立。
)

echo.
echo [3/4] 安裝套件，第一次可能需要幾分鐘
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
  echo.
  echo [錯誤] 套件安裝失敗。
  echo 請檢查網路是否可連線，或把上方錯誤訊息截圖給 ChatGPT。
  pause
  exit /b 1
)

echo.
echo [4/4] 啟動 Streamlit Web App
echo 如果瀏覽器沒有自動開啟，請手動打開：
echo http://localhost:8501
echo.
streamlit run app.py

echo.
echo App 已結束或啟動失敗。請把上方錯誤訊息截圖給 ChatGPT。
pause
