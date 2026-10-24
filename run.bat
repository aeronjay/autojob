@echo off
cd /d "%~dp0"
if "%1"=="fetch" (python autojob.py fetch & pause & exit /b)
echo Starting dashboard at http://127.0.0.1:5000  (close this window to stop)
python autojob.py serve
