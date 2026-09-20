@echo off
rem EnglishHelper - build standalone exe (output: dist\EnglishHelper\EnglishHelper.exe)
rem
rem 关于速度：打包耗时几乎全在 PyInstaller 的“依赖分析”（约 1 分钟，其中 PySide6 的
rem DDL/插件分析占大头），拷贝产物只占不到 1 秒，所以慢是正常的、与磁盘无关。
rem 改过代码后必须重新分析；若代码没变（缓存命中）约 5 秒即可完成。
rem 日常调试请直接跑 run.bat（源码秒级启动），只有发版才需要打包。
cd /d %~dp0

rem 优先使用专用精简环境（只装 PySide6/keyboard/requests/pyinstaller）：
rem   python -m venv .venv-build
rem   .venv-build\Scripts\python -m pip install PySide6 keyboard requests pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
rem 专用环境比公共环境包少，能省下 PyInstaller 扫描已装包元数据的时间，产物也更小
set "PYI=C:\Users\zlq\.workbuddy\binaries\python\envs\default\Scripts\pyinstaller.exe"
if exist "%~dp0.venv-build\Scripts\pyinstaller.exe" set "PYI=%~dp0.venv-build\Scripts\pyinstaller.exe"

"%PYI%" -y --noconsole --onedir ^
  --name EnglishHelper ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --hidden-import keyboard ^
  --exclude-module tkinter ^
  --exclude-module setuptools ^
  --exclude-module pkg_resources ^
  --exclude-module cryptography ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQuickWidgets ^
  --exclude-module PySide6.QtQuickControls2 ^
  --exclude-module PySide6.QtVirtualKeyboard ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtPdfWidgets ^
  --exclude-module PySide6.QtSql ^
  --exclude-module PySide6.QtTest ^
  --exclude-module PySide6.QtDBus ^
  --exclude-module PySide6.QtDesigner ^
  --exclude-module PySide6.QtHelp ^
  --exclude-module PySide6.QtUiTools ^
  --exclude-module PySide6.QtMultimediaWidgets ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtWebEngineQuick ^
  --exclude-module PySide6.QtWebChannel ^
  --exclude-module PySide6.QtWebSockets ^
  --exclude-module PySide6.QtCharts ^
  --exclude-module PySide6.QtDataVisualization ^
  --exclude-module PySide6.QtGraphs ^
  --exclude-module PySide6.QtBluetooth ^
  --exclude-module PySide6.QtNfc ^
  --exclude-module PySide6.QtPositioning ^
  --exclude-module PySide6.QtSensors ^
  --exclude-module PySide6.QtSerialPort ^
  --exclude-module PySide6.QtScxml ^
  --exclude-module PySide6.QtRemoteObjects ^
  --exclude-module PySide6.QtSpatialAudio ^
  --exclude-module PySide6.QtNetworkAuth ^
  --exclude-module PySide6.QtHttpServer ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.Qt3DRender ^
  main.py
echo.
echo Build done: %~dp0dist\EnglishHelper\EnglishHelper.exe
pause
