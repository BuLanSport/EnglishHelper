@echo off
rem EnglishHelper - build Windows installer (output: dist\installer\EnglishHelper_Setup_*.exe)
rem Step 1: run build.bat to produce dist\EnglishHelper
rem Step 2: run this script (requires Inno Setup 6, see README)
cd /d %~dp0

if not exist "dist\EnglishHelper\EnglishHelper.exe" (
  echo [ERROR] dist\EnglishHelper\EnglishHelper.exe not found.
  echo         Run build.bat first, then run this script again.
  pause
  exit /b 1
)

set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo [ERROR] Inno Setup 6 not found. Install it with:
  echo         winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)

"%ISCC%" installer.iss
if errorlevel 1 (
  echo.
  echo [FAILED] Installer build failed. See messages above.
  pause
  exit /b 1
)

echo.
echo Build done: %~dp0dist\installer\
pause
