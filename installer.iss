; 英译通 EnglishHelper 安装包脚本（Inno Setup 6）
; 用法：先运行 build.bat 生成 dist\EnglishHelper，再运行 build_installer.bat
; 产出：dist\installer\EnglishHelper_Setup_<版本号>.exe
; 发新版本时只需改下面这个版本号：
#define MyAppVersion "1.0.0"

#define MyAppName "英译通 EnglishHelper"
#define MyAppPublisher "BuLanSport"
#define MyAppURL "https://github.com/BuLanSport/EnglishHelper"
#define MyAppExeName "EnglishHelper.exe"

[Setup]
; AppId 唯一标识本软件（升级安装/卸载识别用），一旦发布请勿修改
AppId={{7C2F4A16-9E3B-4D58-A1F6-8B5C0D2E9A74}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} Setup
DefaultDirName={autopf}\EnglishHelper
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 免管理员权限安装（装到用户目录），任何人双击即可完成，不弹 UAC
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=EnglishHelper_Setup_{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 本程序托盘常驻：安装/升级时若检测到正在运行，向导会提示用户关闭（避免文件占用失败）
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes

[Languages]
Name: "chinese"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
; 整个 dist\EnglishHelper 目录（exe + _internal 依赖 + assets）原样装进安装目录
; 排除运行产物：debug.log 是程序运行时写的日志（程序开着时还被占用），
; data.db/config.json 属于用户数据（正常跑在 %LOCALAPPDATA%\EnglishHelper，这里只为防残留）
Source: "dist\EnglishHelper\*"; Excludes: "debug.log,*.log,data.db,config.json"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// 卸载完成时询问是否删除翻译历史和设置（默认保留，重装后还能接着用）
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\EnglishHelper');
    if DirExists(DataDir) then
      if MsgBox('是否同时删除翻译历史和设置？' + #13#10#13#10 +
                '位置：' + DataDir + #13#10 +
                '选“否”则保留数据，以后重新安装可直接继续使用。',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
