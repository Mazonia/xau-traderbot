@echo off
echo Stopping XAUUSD Trading Bot background processes...
taskkill /F /IM xau-trader.exe >nul 2>&1
powershell -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'xau-trader.exe') -and $_.CommandLine -like '*XAUUSD-AI-Trading-Bot*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Done. Bot processes terminated.
timeout /t 2 >nul
