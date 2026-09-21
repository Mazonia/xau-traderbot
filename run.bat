@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set VENV_PY=C:\Users\Mazonia\.gemini\antigravity-ide\scratch\XAUUSD-AI-Trading-Bot\venv\Scripts\python.exe
if exist "%VENV_PY%" (
    "%VENV_PY%" main.py %*
) else (
    python main.py %*
)
