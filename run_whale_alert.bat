@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" whale_alert.py >> whale_alert.log 2>&1