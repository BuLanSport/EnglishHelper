@echo off
rem EnglishHelper - build standalone exe (output: dist\EnglishHelper\EnglishHelper.exe)
cd /d %~dp0
C:\Users\zlq\.workbuddy\binaries\python\envs\default\Scripts\pyinstaller.exe -y --noconsole --onedir ^
  --name EnglishHelper ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --collect-all rapidocr_onnxruntime ^
  --collect-all onnxruntime ^
  --hidden-import keyboard ^
  main.py
echo.
echo Build done: %~dp0dist\EnglishHelper\EnglishHelper.exe
pause
