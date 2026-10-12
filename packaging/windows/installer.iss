; Inno Setup script for KCD Mod Manager (Python edition).
;
; Built by scripts/build.py:
;   iscc /DAppVersion=5.0.0 /DSourceDir=<dist\KCDModManager> /DOutputDir=<release> packaging\windows\installer.iss
;
; Installs per user by default (no administrator rights needed); the user may choose an
; all-users install in the dialog. User data in %APPDATA%\KCDModManager is never touched by
; installing or uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\KCDModManager"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

#define AppName "KCD Mod Manager"
#define AppExe "KCDModManager.exe"

[Setup]
AppId={{0A5AD17F-6487-4C6E-8817-D2792CA62251}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=KCD Mod Manager contributors
DefaultDirName={autopf}\KCD Mod Manager
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=KCDModManager-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\src\kcd_mod_manager\resources\images\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files of a previous version so stale libraries are not left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
