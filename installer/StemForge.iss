; Instalador de StemForge para Windows (Inno Setup 6). Lo compila build_windows.ps1:
;   ISCC /DAppVersion=0.1.0 /DSourceDir=dist\StemForge /DOutputDir=dist installer\StemForge.iss
;
; Se instala por usuario (%LOCALAPPDATA%\Programs\StemForge, sin permisos de administrador).
; Los modelos y ajustes viven aparte, en %LOCALAPPDATA%\StemForge.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\StemForge"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{EE8FFFDF-278B-4E3A-863C-B64AF3391C38}
AppName=StemForge
AppVersion={#AppVersion}
AppVerName=StemForge {#AppVersion}
AppPublisher=vicvinue
AppPublisherURL=https://github.com/vicvinue/stemforge
AppSupportURL=https://github.com/vicvinue/stemforge/issues
AppCopyright=© 2026 vicvinue · Todos los derechos reservados
DefaultDirName={autopf}\StemForge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
#ifdef Cuda
OutputBaseFilename=StemForge-{#AppVersion}-CUDA-Setup
#else
OutputBaseFilename=StemForge-{#AppVersion}-Setup
#endif
SetupIconFile={#SourceDir}\StemForge.ico
UninstallDisplayIcon={app}\StemForge.ico
UninstallDisplayName=StemForge
LicenseFile={#SourceDir}\LICENSE.txt
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
CloseApplications=yes
#ifdef Cuda
; Con PyTorch CUDA el paquete supera los 2 GB: se divide en Setup.exe + archivos .bin
; (cada uno bajo el límite de 2 GiB por archivo de las releases de GitHub)
DiskSpanning=yes
DiskSliceSize=max
#endif

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Al actualizar, borrar el Python anterior para no mezclar paquetes de versiones distintas.
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\StemForge"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B -X utf8 -m stemforge.app"; \
  WorkingDir: "{app}"; IconFilename: "{app}\StemForge.ico"; AppUserModelID: "vicvinue.StemForge"; \
  Comment: "Separador de stems"
Name: "{autodesktop}\StemForge"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B -X utf8 -m stemforge.app"; \
  WorkingDir: "{app}"; IconFilename: "{app}\StemForge.ico"; AppUserModelID: "vicvinue.StemForge"; \
  Comment: "Separador de stems"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B -X utf8 -m stemforge.app"; WorkingDir: "{app}"; \
  Description: "{cm:LaunchProgram,StemForge}"; Flags: nowait postinstall skipifsilent
; Actualización automática (la app ejecuta el instalador con /SILENT /RELAUNCH=1): volver a abrirla.
Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B -X utf8 -m stemforge.app"; WorkingDir: "{app}"; \
  Flags: nowait; Check: ShouldRelaunch

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  DataDir := ExpandConstant('{localappdata}\StemForge');
  if not DirExists(DataDir) then
    Exit;
  if SuppressibleMsgBox('¿Borrar también los modelos descargados y los ajustes de StemForge?' + #13#10#13#10 +
                        DataDir + #13#10#13#10 + 'Las canciones separadas no se borran.',
                        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    DelTree(DataDir, True, True, True);
end;
