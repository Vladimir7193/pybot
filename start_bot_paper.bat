@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title RocketBot PAPER - READY
color 0B

echo.
echo ============================================================
echo   RocketBot PAPER TRADING - READY BUILD
echo ============================================================
echo   Mode: Smart Money Concepts ^| Paper Trading
if exist ".env" (
  echo   Env:  .env found
) else (
  echo   Env:  .env NOT found
)
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10+ and check "Add Python to PATH".
    pause
    exit /b 1
)

python --version
if errorlevel 1 (
    echo [ERROR] Python failed to start.
    pause
    exit /b 1
)

echo.
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating local virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip --timeout 30 --retries 2 >nul 2>&1

echo [INFO] Installing dependencies...
pip install -r requirements.txt --timeout 30 --retries 2 --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo [ERROR] .env file not found.
    echo Copy .env.example to .env and fill in:
    echo   BYBIT_API_KEY=
    echo   BYBIT_API_SECRET=
    echo   BYBIT_TESTNET=false
    echo   TELEGRAM_TOKEN=
    echo   TELEGRAM_CHAT_ID=
    echo.
    pause
    exit /b 1
)

if "%INTERVAL%"=="" set INTERVAL=15

echo.
echo [INFO] Launching bot...
echo [INFO] Scan interval: %INTERVAL% minutes
echo [INFO] Logs: logs\rocketbot.log
echo [INFO] Press Ctrl+C to stop.
echo.
python bot_paper.py

echo.
echo Bot stopped.
pause
endlocal
