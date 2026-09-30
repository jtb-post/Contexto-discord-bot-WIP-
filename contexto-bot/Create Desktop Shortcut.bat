@echo off
rem Puts a "Contexto Bot" shortcut on your desktop that runs Start Contexto.bat.
rem The work is done by create-shortcut.ps1, which handles folder names in any language.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Double-clicking this inside a .zip runs a temporary copy with nothing next to it.
if not exist "create-shortcut.ps1" (
    echo Can't find the other Contexto files next to this one.
    echo If you opened the download's .zip, right-click it, choose Extract All,
    echo then run this file from the extracted folder.
    goto :done
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create-shortcut.ps1"
if errorlevel 1 echo Couldn't create the shortcut. The message above says why.

:done
pause
