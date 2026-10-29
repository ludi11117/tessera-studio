@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
set TESSERA_QUICK_DIR=D:\CodexWork\temp
if exist ".venv-research\Scripts\python.exe" (
  ".venv-research\Scripts\python.exe" -B server.py --quick
) else (
  python -B server.py --quick
)
if errorlevel 1 pause
