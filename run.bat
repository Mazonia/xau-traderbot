@echo off
set VENV_PY=C:\Users\Mazonia\.gemini\antigravity-ide\scratch\XAUUSD-AI-Trading-Bot\venv\Scripts\python.exe
if exist "%VENV_PY%" (
    "%VENV_PY%" main.py %*
) else (
    python main.py %*
)
