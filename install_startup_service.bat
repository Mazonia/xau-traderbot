@echo off
echo Adding XAUUSD Trading Bot to Windows Startup (Silent Background Daemon)...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.Environment]::GetFolderPath('Startup') + '\XAUUSD_TradingBot.lnk'); $s.TargetPath = '%~dp0start_bot_background.vbs'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
echo.
echo [SUCCESS] XAUUSD Trading Bot is registered in Windows Startup!
echo.
echo  * On PC boot, the bot starts SILENTLY in the background.
echo  * MetaTrader 5 terminal window will remain HIDDEN so nobody sees your charts.
echo  * You will receive a Telegram message once the bot is online.
echo  * Control trading or show/hide MT5 anytime directly from Telegram!
echo.
pause
