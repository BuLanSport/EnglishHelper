# 英译通 EnglishHelper

一个专为**英文困难者**设计的 Windows 桌面翻译学习软件。全中文界面，托盘常驻，开箱即用。

## 功能

- **划词翻译**：任何软件里选中文字，按 `Alt+Q` 即时弹出翻译
- **截图翻译**：文字选不中（图片里、特殊软件里），按 `Alt+W` 框选，由 Qwen 视觉模型**直接识别图片并翻译**（无本地 OCR，需联网）
- **智能方向**：划英文出中文，划中文自动出英文——写英文内容时随手可得地道表达
- **翻译浮窗**：即时反馈"翻译中"、可拖动、📌图钉固定、长文滚动、鼠标悬停不消失
- **朗读**：Windows SAPI 语音朗读原文/译文
- **翻译引擎**：通义千问 Qwen 大模型翻译（阿里云百炼，`qwen3.7-flash` 支持文本与图片视觉翻译，需自己的 API Key）
- **单实例唤醒**：重复启动不弹窗，自动把已运行实例的主窗口调到前台
- **数据安全**：翻译历史/配置存放在系统数据目录（`%LOCALAPPDATA%\EnglishHelper`），更新重装不丢失

## 环境

- Windows 10 / 11
- Python 3.10+（推荐 3.13；开发环境用 venv）

## 构建

```bat
pip install -r requirements.txt
pip install pyinstaller
build.bat
```

产出 `dist\EnglishHelper\EnglishHelper.exe`（onedir）。想打成单个 exe 用 `--onefile`。

### 制作安装包（分发给其他用户）

1. 先运行 `build.bat` 生成 `dist\EnglishHelper`
2. 安装 Inno Setup 6（`winget install JRSoftware.InnoSetup`）
3. 运行 `build_installer.bat`

产出 `dist\installer\EnglishHelper_Setup_<版本号>.exe`（约 38 MB）：中文安装向导、免管理员权限安装、
自动创建开始菜单/桌面快捷方式、自带卸载程序（卸载时可选是否删除翻译历史与设置）。
把 Setup.exe 发给别人，双击即可安装。发新版本时只需改 `installer.iss` 顶部的 `MyAppVersion`
再重新编译。

## 运行

开发运行：`run.bat`——若本机没有现成环境，首次运行会自动创建 venv 并安装依赖（约 5~10 分钟），之后每次秒启动。
日常使用直接双击 `dist\EnglishHelper\EnglishHelper.exe`，托盘常驻。

## 项目结构

```
main.py            主程序：托盘、全局热键、单实例唤醒、划词/截图流程
core.py            核心：Qwen 文本/视觉翻译、数据库、朗读、开机自启
ui.py              界面：翻译浮窗、截图遮罩、主窗口
gen_icon.py        图标生成
requirements.txt   依赖清单（pip install -r requirements.txt）
installer.iss      安装包制作脚本（Inno Setup；版本号在文件顶部）
build_installer.bat 一键生成安装包（输出 dist\installer\*.exe）
test_core.py       Qwen 翻译/视觉截图翻译实测脚本
test_hotkey_e2e.py 划词端到端自动化测试（真实记事本）
test_popup_ui.py   浮窗 UI 自动化测试（拖动/滚动/图钉/悬停）
```

## 详细说明

见《使用说明.txt》（全中文，含故障排查与数据位置说明）。
