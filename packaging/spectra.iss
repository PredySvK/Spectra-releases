; Compile through build_exe.ps1: product identity comes from core/app_metadata.py.
#ifndef AppVersion
  #error AppVersion must be supplied by build_exe.ps1
#endif
#ifndef AppName
  #error AppName must be supplied by build_exe.ps1
#endif
#ifndef AppUserModelID
  #error AppUserModelID must be supplied by build_exe.ps1
#endif

[Setup]
; Stable across releases and independent of the chosen installation folder.
AppId={{6AE13C46-9799-4B3F-A9A5-FA287E472FEB}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableDirPage=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
ChangesAssociations=yes
UninstallDisplayIcon={app}\_internal\resources\icons\app_icon.ico
SetupIconFile=..\resources\icons\app_icon.ico
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
; [Run] owns restart, including apps without RegisterApplicationRestart.
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Spectra\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Spectra.exe"; WorkingDir: "{app}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Spectra.exe"; WorkingDir: "{app}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; OpenWithProgids leaves other applications' associations intact.
Root: HKCU; Subkey: "Software\Classes\.nvhproject\OpenWithProgids"; ValueType: string; ValueName: "Spectra.Project"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.nvhproject"; ValueType: string; ValueData: "Spectra.Project"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Spectra.Project"; ValueType: string; ValueData: "Spectra project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Spectra.Project\DefaultIcon"; ValueType: string; ValueData: """{app}\_internal\resources\icons\app_icon.ico"",0"
Root: HKCU; Subkey: "Software\Classes\Spectra.Project\shell\open\command"; ValueType: string; ValueData: """{app}\Spectra.exe"" ""%1"""

[Run]
Filename: "{app}\Spectra.exe"; Description: "Launch {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Updater opts in with /RESTARTAPP=1 after asking about unsaved work and jobs.
Filename: "{app}\Spectra.exe"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent runasoriginaluser; Check: RestartAfterSilentInstall

[Code]
function RestartAfterSilentInstall: Boolean;
begin
  Result := ExpandConstant('{param:RESTARTAPP|0}') = '1';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ProjectType: String;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Software\Classes\.nvhproject', '', ProjectType) then
      if ProjectType = 'Spectra.Project' then
        RegDeleteValue(HKCU, 'Software\Classes\.nvhproject', '');
end;
