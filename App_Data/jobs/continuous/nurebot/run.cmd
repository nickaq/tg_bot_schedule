@echo off
setlocal enableextensions

REM Navigate to the app root (deployment path)
cd /d %HOME%\site\wwwroot

REM Optional: ensure pip is up to date (no-op if not needed)
python -m pip install --upgrade pip

REM Install Python dependencies (idempotent)
if exist requirements.txt (
  pip install -r requirements.txt
)

REM Run the Telegram bot
set PYTHONUNBUFFERED=1
python bot.py
