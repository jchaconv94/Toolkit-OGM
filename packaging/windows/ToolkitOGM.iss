#define MyAppId "{{E2C6BAA5-3F07-43F5-9B83-9A0F912C3B24}"
#define MyAppName "ToolKit SISMED"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef RepoRoot
  #define RepoRoot "..\.."
#endif
#define MyAppExeName "ToolkitOGM.exe"
#define MyBuildDir RepoRoot + "\dist\ToolkitOGM"
#define MyInstallerDir RepoRoot + "\dist\installer"
#define MyIconFile RepoRoot + "\packaging\windows\ToolkitOGM.ico"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Jordan Chacon Villacis
DefaultDirName={localappdata}\Programs\ToolKit SISMED
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyInstallerDir}
OutputBaseFilename=ToolkitOGM-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#MyIconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent