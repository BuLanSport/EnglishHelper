@echo off
cd /d "%~dp0"
echo ==============================================
echo  Push EnglishHelper source code to GitHub
echo  (BuLanSport/EnglishHelper)
echo ==============================================
echo.
echo NOTE: If a browser window opens, please login
echo       to GitHub and click Authorize.
echo.
git push -u origin main
echo.
if errorlevel 1 (
  echo [FAILED] Push did not finish.
  echo Tips: 1. Check internet / VPN (Clash) is running.
  echo       2. Run this file again after login.
) else (
  echo [SUCCESS] Code pushed!
  echo Open: https://github.com/BuLanSport/EnglishHelper
)
echo.
pause
