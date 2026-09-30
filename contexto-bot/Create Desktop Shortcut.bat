@echo off
rem Puts a "Contexto Bot" shortcut on your desktop that runs Start Contexto.bat.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Contexto Bot.lnk'));" ^
  "$lnk.TargetPath = [IO.Path]::Combine((Get-Location).Path, 'Start Contexto.bat');" ^
  "$lnk.WorkingDirectory = (Get-Location).Path;" ^
  "$lnk.IconLocation = 'imageres.dll,76';" ^
  "$lnk.Description = 'Start the Contexto Discord bot';" ^
  "$lnk.Save()"
if errorlevel 1 (
    echo Couldn't create the shortcut.
) else (
    echo Added "Contexto Bot" to your desktop. Double-click it to start the bot.
)
pause
