@echo off
rem Double-click to run the Contexto bot.
rem First run: sets up Python packages and the word list, then asks for the bot token.
rem After that it just starts the bot, and restarts it if it crashes.
setlocal
title Contexto Bot
cd /d "%~dp0"

set "VPY=.venv\Scripts\python.exe"

rem --- Python environment (one time) ---
if exist "%VPY%" "%VPY%" -c "pass" >nul 2>nul || rmdir /s /q .venv 2>nul
if exist "%VPY%" goto :packages

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3.10 or newer is needed. Opening the download page...
    echo Install it with "Add python.exe to PATH" ticked, then double-click this file again.
    start "" https://www.python.org/downloads/
    goto :fail
)
echo [setup] Creating the Python environment...
%PY% -m venv .venv || goto :fail

:packages
rem --- Packages: installed once, and again whenever requirements.txt changes ---
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if not errorlevel 1 goto :words
echo [setup] Installing packages...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
copy /y requirements.txt ".venv\requirements.installed" >nul

:words
rem --- Word list: about 128 MB, downloaded once ---
if exist "data\vectors.npy" if exist "data\vocab.txt" goto :run
echo [setup] Downloading the word list - about 128 MB, one time only...
"%VPY%" prepare_vectors.py || goto :fail

:run
echo.
echo Starting Contexto. Keep this window open - closing it stops the bot.
echo.
"%VPY%" bot.py
set "CODE=%errorlevel%"
if "%CODE%"=="0" goto :end
if "%CODE%"=="2" goto :fail
echo.
echo The bot stopped unexpectedly - exit code %CODE%. Restarting in 10 seconds. Press Ctrl+C to cancel.
timeout /t 10 >nul
goto :run

:fail
echo.
echo Contexto didn't start. Read the message above, fix it, then double-click again.
pause
exit /b 1

:end
endlocal
