@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title RocketBot - Smart Money Concept
color 0A

echo ============================================================
echo   RocketBot Python v1.0  ^|  Smart Money Concept
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

:: Check .env
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Copy .env.example to .env and fill in your credentials.
    pause
    exit /b 1
)

:: Install dependencies if needed
if not exist "requirements.txt" goto :run
echo Installing dependencies...
pip install -r requirements.txt --timeout 30 --retries 2 --quiet
echo.

:run
echo Starting bot...
echo Press Ctrl+C to stop.
echo.
python bot.py

echo.
echo Bot stopped.
pause
