@echo off
cd /d "%~dp0"
rem Use the project's virtual environment if there is one.
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%1"=="fetch" (%PY% autojob.py fetch & pause & exit /b)
echo Starting the dashboard in your browser  (close this window to stop)
%PY% autojob.py serve
pause
