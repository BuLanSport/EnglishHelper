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

rem 查找 Inno Setup 编译器 ISCC.exe：
rem 1) 常见安装位置（用户级安装优先，免管理员权限）
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
rem 2) 装到其它盘/自定义目录时，从注册表的卸载信息里读出安装位置
if not defined ISCC for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "$p=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'Inno Setup*' -and $_.InstallLocation } | Select-Object -First 1 -ExpandProperty InstallLocation); if ($p) { Join-Path $p 'ISCC.exe' }"`) do set "ISCC=%%A"
rem 3) PATH 里已经有 ISCC
if not defined ISCC for %%A in (ISCC.exe) do if not "%%~$PATH:A"=="" set "ISCC=%%~$PATH:A"
if not defined ISCC (
  echo [ERROR] Inno Setup 6 not found. Install it with:
  echo         winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)
if not exist "%ISCC%" (
  echo [ERROR] ISCC.exe not found at: %ISCC%
  echo         Reinstall it with: winget install JRSoftware.InnoSetup
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
