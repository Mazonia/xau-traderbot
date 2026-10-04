@echo off
echo Stopping XAUUSD Trading Bot background processes...
taskkill /F /FI "WINDOWTITLE eq XAUUSD*" >nul 2>&1
wmic process where "name='python.exe' and CommandLine like '%%main.py%%'" call terminate >nul 2>&1
echo Done.
