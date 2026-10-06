@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
title XAUUSD-AI-Trader
set VENV_PY=%~dp0.venv\Scripts\python.exe
if exist "%VENV_PY%" (
    if not exist "%~dp0.venv\Scripts\xau-trader.exe" (
        copy "%VENV_PY%" "%~dp0.venv\Scripts\xau-trader.exe" >nul
    )
    "%~dp0.venv\Scripts\xau-trader.exe" "%~dp0main.py" %*
) else (
    for /f "delims=" %%i in ('where python') do set SYSTEM_PY=%%i & goto :found_sys_py
    :found_sys_py
    if not exist "%~dp0xau-trader.exe" (
        copy "%SYSTEM_PY%" "%~dp0xau-trader.exe" >nul
    )
    "%~dp0xau-trader.exe" "%~dp0main.py" %*
)

