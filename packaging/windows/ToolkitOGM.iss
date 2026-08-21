#define MyAppId "{{E2C6BAA5-3F07-43F5-9B83-9A0F912C3B24}"
#define MyAppName "ToolKit SISMED"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef RepoRoot
  #define RepoRoot "..\.."
#endif
#define MyAppExeName "ToolkitOGM.exe"
#define MyAppMutex "ToolkitOGM_SingleInstanceMutex_v1"
#define MyBuildDir RepoRoot + "\dist\ToolkitOGM"
#define MyInstallerDir RepoRoot + "\dist\installer"
#define MyIconFile RepoRoot + "\packaging\windows\ToolkitOGM.ico"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Jordan Chacon Villacis
DefaultDirName={autopf}\ToolKit SISMED
DefaultGroupName={#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
OutputDir={#MyInstallerDir}
OutputBaseFilename=ToolkitOGM-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#MyIconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex={code:GetAppMutex}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany=Jordan Chacon Villacis
VersionInfoDescription={#MyAppName}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
FinishedHeadingLabel=Instalación o actualización completada
FinishedLabel={#MyAppName} se instaló o actualizó correctamente.%n%nPuedes iniciar la aplicación ahora.
FinishedLabelNoIcons={#MyAppName} se instaló o actualizó correctamente.

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

; No borrar archivos criticos antes de copiar la nueva version.
; Inno Setup sobrescribe en sitio; si una actualizacion se interrumpe,
; borrar primero el EXE/_internal puede dejar la app "desaparecida".

[Files]
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-success"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-success"; Flags: nowait; Check: IsAutoUpdateMode

[Code]
function IsAutoUpdateMode: Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if CompareText(ParamStr(Index), '/AUTOUPDATE') = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function GetAppMutex(Param: String): String;
begin
  if IsAutoUpdateMode then
    Result := ''
  else
    Result := '{#MyAppMutex}';
end;
