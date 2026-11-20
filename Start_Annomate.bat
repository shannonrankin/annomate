@echo off
title Annomate - Bioacoustic Annotation Platform
cd /d "%~dp0"

echo ====================================================================
echo   annomate - Bioacoustic Annotation ^& Cloud Metadata Platform
echo ====================================================================
echo.

REM 1. Ensure .env configuration file exists
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [Setup] Created a new .env file from .env.example.
        echo         If needed, open .env in Notepad to enter the database password.
        echo.
    )
)

REM 2. Check for virtual environment; if missing, try to create it automatically
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

echo [Starting] Launching Annomate at http://127.0.0.1:8000 ...
echo [Note] Keep this window open while using Annomate. Close this window to stop.
echo.

REM Open the default web browser after 3 seconds in the background
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
