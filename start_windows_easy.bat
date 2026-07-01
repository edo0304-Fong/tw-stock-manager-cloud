@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title TW Stock Manager - Safe Launcher

echo ======================================================
echo TW Stock Manager - Safe Launcher
echo Project folder: %cd%
echo ======================================================
echo.

if not exist "app.py" (
  echo [ERROR] app.py not found.
  echo Please extract the ZIP first, then run this BAT inside the tw_stock_manager_mvp folder.
  echo.
  pause
  exit /b 1
)

REM Prefer py / Python install manager first, then python.
set "PY_CMD="
where py >nul 2>nul
if %errorlevel%==0 set "PY_CMD=py"

if not defined PY_CMD (
  where python >nul 2>nul
  if %errorlevel%==0 set "PY_CMD=python"
)

if not defined PY_CMD (
  where pymanager >nul 2>nul
  if %errorlevel%==0 set "PY_CMD=pymanager exec"
)

if not defined PY_CMD (
  echo [ERROR] Python command not found.
  echo Please open Windows Terminal and run:
  echo   py install --configure -y
  echo then run this file again.
  echo.
  pause
  exit /b 1
)

echo [1/5] Using Python command: !PY_CMD!
!PY_CMD! --version
if %errorlevel% neq 0 (
  echo.
  echo [WARNING] Python command exists but could not run normally.
  echo If you installed Python Install Manager, please open Windows Terminal and run:
  echo   py install --configure -y
  echo   py install 3.13
  echo Then run this BAT again.
  echo.
  pause
  exit /b 1
)

echo.
echo [2/5] Creating virtual environment .venv
if not exist ".venv\Scripts\python.exe" (
  !PY_CMD! -m venv .venv
  if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to create virtual environment.
    echo Try opening Windows Terminal in this folder and run:
    echo   py -m venv .venv
    echo.
    pause
    exit /b 1
  )
) else (
  echo .venv already exists. Skip.
)

echo.
echo [3/5] Activating virtual environment
call ".venv\Scripts\activate.bat"
if %errorlevel% neq 0 (
  echo [ERROR] Failed to activate .venv.
  pause
  exit /b 1
)

echo.
echo [4/5] Installing required packages. First time may take several minutes.
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
  echo.
  echo [ERROR] Package installation failed.
  echo Please check the error messages above.
  pause
  exit /b 1
)

echo.
echo [5/5] Starting app...
echo If browser does not open automatically, open:
echo   http://localhost:8501
echo.
python -m streamlit run app.py

echo.
echo App stopped or failed. Please screenshot the messages above.
pause
