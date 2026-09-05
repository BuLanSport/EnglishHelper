@echo off
rem EnglishHelper - one click launcher
set "PYW=C:\Users\zlq\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0main.py"
  exit /b
)
echo First run: setting up environment, please wait 5-10 minutes...
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Please install Python first.
  pause
  exit /b 1
)
python -m venv "%~dp0venv"
"%~dp0venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0main.py"
