@echo off
title Annomate (DEMO MODE) - No VPN or Cloud Required
cd /d "%~dp0"

set ANNOMATE_DEMO_MODE=true

echo ====================================================================
echo   annomate - OFFLINE DEMO MODE (No VPN or Google Cloud Needed!)
echo ====================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [First-Time Setup] Setting up Python environment in .venv ...
    echo                    This takes 1-2 minutes on the very first run.
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        python -m venv .venv
    ) else if exist "C:\Users\Administrator\Documents\Anaconda\python.exe" (
        "C:\Users\Administrator\Documents\Anaconda\python.exe" -m venv .venv
    ) else (
        echo [Error] Python 3.10+ was not found on this computer.
        echo         Please install Python from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo [Starting] Launching Annomate in DEMO MODE at http://127.0.0.1:8000 ...
echo [Info]     Includes 180 multi-day bioacoustic calls, 3 hydrophone sites,
echo            playable synthetic audio, Marimo review plots, and safe demo commits.
echo [Note]     Keep this window open while using Annomate. Close to stop.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
