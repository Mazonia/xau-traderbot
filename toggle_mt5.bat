@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Toggle MT5 Visibility
set PY_BIN=python
if exist "%~dp0xau-trader.exe" set PY_BIN="%~dp0xau-trader.exe"
if exist "%~dp0.venv\Scripts\python.exe" set PY_BIN="%~dp0.venv\Scripts\python.exe"
%PY_BIN% -c "import sys; from core.mt5_connector import MT5Connector; c = MT5Connector(); vis = c.toggle_terminal_visibility(); print('============================================================'); print('  [STATUS] MetaTrader 5 Terminal is now: ' + ('VISIBLE on Desktop' if vis else 'HIDDEN in Background')); print('============================================================')"
timeout /t 3

