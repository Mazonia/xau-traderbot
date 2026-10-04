@echo off
echo Removing XAUUSD Trading Bot from Windows Startup...
powershell -Command "Remove-Item ([System.Environment]::GetFolderPath('Startup') + '\XAUUSD_TradingBot.lnk') -ErrorAction SilentlyContinue"
echo.
echo [SUCCESS] Startup shortcut removed.
pause
