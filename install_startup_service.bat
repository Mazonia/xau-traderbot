@echo off
echo Adding XAUUSD Trading Bot to Windows Startup (Background Daemon)...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.Environment]::GetFolderPath('Startup') + '\XAUUSD_TradingBot.lnk'); $s.TargetPath = '%~dp0start_bot_background.vbs'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
echo.
echo [SUCCESS] XAUUSD Trading Bot will now start automatically in the background on PC startup!
echo You can control it, start/stop trading, and check status from your phone via Telegram.
pause
