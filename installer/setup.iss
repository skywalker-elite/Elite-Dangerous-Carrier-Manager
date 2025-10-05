#define AppVersion GetEnv("APP_VERSION")     ; passed from Actions
#define InputDir    GetEnv("INPUT_DIR")      ; PyInstaller output dir
#define AppExe      "Elite Dangerous Carrier Manager.exe"

[Setup]
AppName=Elite Dangerous Carrier Manager
AppVersion={#AppVersion}
AppId={{4BDCB69F-A22E-4297-83E8-29DA3465C9D4}}
WizardStyle=modern
WizardImageFile="Inno_wizard_image.png"
SetupIconFile="{#InputDir}\_internal\images\EDCM.ico"
DefaultDirName={autopf}\EDCM
OutputDir=dist\installer
OutputBaseFilename=EDCM-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#InputDir}\dist\Elite Dangerous Carrier Manager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\EDCM"; Filename: "{app}\{#AppExe}"
Name: "{commondesktop}\EDCM"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch EDCM"; Flags: nowait postinstall skipifsilent
