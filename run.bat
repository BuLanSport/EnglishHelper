@echo off
rem EnglishHelper - one click launcher (run from source, no packaging)
rem Order: project venv -> existing dev environment -> create venv and install deps
cd /d "%~dp0"

rem 1) venv created by a previous first run on this machine
if exist "%~dp0venv\Scripts\pythonw.exe" (
  start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0main.py"
  exit /b
)

rem 2) local dev environment (preinstalled with all dependencies)
set "PYW=C:\Users\zlq\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0main.py"
  exit /b
)

rem 3) first run on a new machine: create venv and install dependencies (5-10 minutes)
echo First run: setting up environment, please wait 5-10 minutes...
if not exist "%~dp0requirements.txt" (
  echo [ERROR] requirements.txt not found.
  pause
  exit /b 1
)

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python not found. Please install Python 3.10+ first:
  echo   https://www.python.org/downloads/
  pause
  exit /b 1
)

%PY% -m venv "%~dp0venv"
if errorlevel 1 (
  echo [ERROR] Failed to create venv.
  pause
  exit /b 1
)

"%~dp0venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo [ERROR] Dependency install failed. Check your network and run this file again.
  pause
  exit /b 1
)

start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0main.py"
