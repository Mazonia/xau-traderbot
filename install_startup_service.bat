@echo off
echo Adding XAUUSD Trading Bot to Windows Startup (Background Daemon)...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.Environment]::GetFolderPath('Startup') + '\XAUUSD_TradingBot.lnk'); $s.TargetPath = '%~dp0start_bot_background.vbs'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
echo.
echo [SUCCESS] XAUUSD Trading Bot will now start automatically in active trading mode on PC startup!
echo Automated trading will be active immediately upon boot. You can pause, monitor, or control it anytime via Telegram.
pause

