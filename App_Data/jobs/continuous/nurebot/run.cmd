@echo off
setlocal enableextensions

REM Navigate to the app root
cd /d %HOME%\site\wwwroot

REM Optional: ensure pip is up to date
python -m pip install --upgrade pip

REM Install dependencies (idempotent; skips if already satisfied)
pip install -r requirements.txt

REM Start the Telegram bot
python bot.py
