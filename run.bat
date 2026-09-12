@echo off
cd /d "%~dp0"
echo MWO Team Tracker on http://localhost:8765  (Ctrl+C to stop)
.venv\Scripts\python.exe -m tracker
