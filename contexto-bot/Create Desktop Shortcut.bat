@echo off
rem Puts a "Contexto Bot" shortcut on your desktop that runs Start Contexto.bat.
setlocal
cd /d "%~dp0"

rem Double-clicking this inside a .zip runs a temporary copy with nothing next to it.
if not exist "Start Contexto.bat" (
    echo Can't find "Start Contexto.bat" next to this file.
    echo If you opened the download's .zip, right-click it, choose Extract All,
    echo then run this file from the extracted folder.
    goto :done
)
echo "%~dp0" | findstr /i /c:"%TEMP%" >nul && (
    echo This is running from a temporary folder, probably inside a .zip.
    echo Right-click the .zip, choose Extract All, then run this file from the extracted folder.
    goto :done
)

set "CONTEXTO_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$dir = $env:CONTEXTO_DIR.TrimEnd('\');" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "if (-not $desktop -or -not (Test-Path -LiteralPath $desktop)) { $desktop = Join-Path $env:USERPROFILE 'Desktop' };" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut((Join-Path $desktop 'Contexto Bot.lnk'));" ^
  "$lnk.TargetPath = Join-Path $dir 'Start Contexto.bat';" ^
  "$lnk.WorkingDirectory = $dir;" ^
  "$lnk.IconLocation = (Join-Path $dir 'assets\contexto.ico') + ',0';" ^
  "$lnk.Description = 'Start the Contexto Discord bot';" ^
  "$lnk.Save();" ^
  "Write-Host ('Added \"Contexto Bot\" to ' + $desktop + '. Double-click it to start the bot.')"
if errorlevel 1 echo Couldn't create the shortcut. The message above says why.

:done
pause
