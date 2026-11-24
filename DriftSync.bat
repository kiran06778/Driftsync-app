@echo off
REM --- DriftSync first-time setup and troubleshooting (Windows). Day to day, use the DriftSync shortcut ---
cd /d "%~dp0"

REM Use a local virtual environment if one exists, otherwise the Python launcher (py) or python
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto no_python
REM "python" can be the Microsoft Store placeholder that only opens the Store: make sure it really runs
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto no_python

REM Quick check (under a second). If packages are missing, offer to install them into .venv (first run only)
%PY% check_setup.py --quiet
if not errorlevel 1 goto run
if exist ".venv" goto still_broken
echo.
set "ans="
set /p ans="Install what DriftSync needs into a local .venv folder now? (about 150 MB) [Y/n] "
if /i "%ans%"=="n" goto still_broken
%PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt
set "PY=.venv\Scripts\python.exe"
%PY% check_setup.py --quiet
if errorlevel 1 goto still_broken

:run
REM First time it works: put DriftSync (with its icon) on the Desktop and in the Start menu
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\DriftSync.lnk" (
    wscript //nologo "launcher\Create shortcuts.vbs" /quiet
    echo DriftSync is now on your Desktop and in the Start menu. Next time, open it from there.
)
%PY% desktop_app.py
if errorlevel 1 (
    echo.
    echo DriftSync stopped with an error.
    pause
)
exit /b 0

:still_broken
echo DriftSync can't start yet (see FIX above).
pause
exit /b 1

:no_python
echo Python is not installed. Get Python 3.9 or newer from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, then double-click DriftSync.bat again.
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1
