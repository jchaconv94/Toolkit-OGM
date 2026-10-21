#ifndef MyAppId
  #define MyAppId "{{E2C6BAA5-3F07-43F5-9B83-9A0F912C3B24}"
#endif
#ifndef MyAppName
  #define MyAppName "ToolKit SISMED"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef RepoRoot
  #define RepoRoot "..\.."
#endif
#define MyAppExeName "ToolkitOGM.exe"
#define MyAppMutex "ToolkitOGM_SingleInstanceMutex_v1"
#define MyBuildDir RepoRoot + "\dist\ToolkitOGM"
#ifndef MyInstallerDir
  #define MyInstallerDir RepoRoot + "\dist\installer"
#endif
#ifndef MyDefaultDirName
  #define MyDefaultDirName "{autopf}\ToolKit SISMED"
#endif
#define MyIconFile RepoRoot + "\packaging\windows\ToolkitOGM.ico"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Jordan Chacon Villacis
DefaultDirName={#MyDefaultDirName}
DefaultGroupName={#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
; Una actualizacion debe conservar la carpeta registrada por la instalacion anterior.
; El auxiliar tambien envia /DIR con la ruta exacta como segunda proteccion.
UsePreviousAppDir=yes
OutputDir={#MyInstallerDir}
OutputBaseFilename=ToolkitOGM-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#MyIconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
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
; Abrir al encender Windows: lo pone el instalador, no el Toolkit. Cuando el Toolkit se registraba
; solo en el arranque (tarea programada o clave Run), Windows Defender lo borraba como
; "Behavior:Win32/Persistence.A!ml". La casilla del Toolkit solo decide si se queda abierto.
Name: "{autostartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--autorun"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-success"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent
; Las versiones anteriores del auxiliar solo enviaban /AUTOUPDATE y necesitan este arranque.
; El auxiliar seguro envia tambien /SAFEUPDATE y abre la app despues de verificarla.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-success"; Flags: nowait; Check: IsLegacyAutoUpdateMode

[UninstallDelete]
; Actualizaciones de codigo descargadas por el Toolkit (toolskit/app_loader.py).
Type: filesandordirs; Name: "{localappdata}\ToolkitOGM\app"

[UninstallRun]
; Tarea de arranque que creaban las versiones anteriores a la 2.3.19.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ToolkitOGM_Autorun /F"; Flags: runhidden; RunOnceId: "BorrarArranqueAnterior"

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

function IsSafeUpdateMode: Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if CompareText(ParamStr(Index), '/SAFEUPDATE') = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsLegacyAutoUpdateMode: Boolean;
begin
  Result := IsAutoUpdateMode and (not IsSafeUpdateMode);
end;

function GetAppMutex(Param: String): String;
begin
  if IsAutoUpdateMode then
    Result := ''
  else
    Result := '{#MyAppMutex}';
end;
