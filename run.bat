@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set VENV_PY=%~dp0.venv\Scripts\python.exe
if exist "%VENV_PY%" (
    "%VENV_PY%" "%~dp0main.py" %*
) else (
    python "%~dp0main.py" %*
)
