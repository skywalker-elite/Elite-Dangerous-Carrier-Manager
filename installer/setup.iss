#define AppVersion GetEnv("APP_VERSION")
#define InputDir   GetEnv("INPUT_DIR")
#define OutputDirA GetEnv("OUTPUT_DIR")
#define AppExe      "Elite Dangerous Carrier Manager.exe"

#pragma message "AppVersion = {#AppVersion}"
#pragma message "InputDir   = {#InputDir}"
#pragma message "OutputDirA = {#OutputDirA}"
#pragma message "AppExe      = {#AppExe}"

[Setup]
AppName=Elite Dangerous Carrier Manager
AppVersion={#AppVersion}
AppId={{4BDCB69F-A22E-4297-83E8-29DA3465C9D4}}
WizardStyle=modern
WizardImageFile="{#InputDir}\..\..\installer\Inno_wizard_image.png"
SetupIconFile="{#InputDir}\_internal\images\EDCM.ico"
DefaultDirName={autopf}\EDCM
DefaultGroupName=Skywalker-Elite
OutputDir={#OutputDirA}
OutputBaseFilename=EDCM-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#InputDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\EDCM"; Filename: "{app}\{#AppExe}"
Name: "{commondesktop}\EDCM"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Additional shortcuts:"
Name: "quicklaunchicon"; Description: "Create a &Quick Launch shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch EDCM"; Flags: nowait postinstall skipifsilent
