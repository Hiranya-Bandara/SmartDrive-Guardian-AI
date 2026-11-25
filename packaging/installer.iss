; Inno Setup 6 script for SmartDrive Guardian AI.
;
; Input: the verified PyInstaller one-folder build in dist\SmartDrive-Guardian-AI.
; Build with scripts\build-installer.ps1, which passes the version from smartdrive.__version__:
; ISCC.exe /DAppVersion=<version> /DDistDir=..\dist\SmartDrive-Guardian-AI packaging\installer.iss
;
; Design:
; * Per-user installation by default (no administrator rights); the user may choose an
;   all-users installation in the privileges dialog, which then asks for elevation.
; * Only application files are installed. User data lives in
;   %LOCALAPPDATA%\SmartDriveGuardianAI and is never installed, changed or deleted by this
;   installer or its uninstaller.
; * No services, drivers, startup entries, browser extensions or third-party software.
; * Unsigned unless scripts\build-installer.ps1 is given a signing command (see docs).

#ifndef AppVersion
  #error AppVersion must be defined, e.g. /DAppVersion=<version> (scripts\build-installer.ps1 does this)
#endif
#ifndef DistDir
  #define DistDir "..\dist\SmartDrive-Guardian-AI"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif

#define AppName "SmartDrive Guardian AI"
#define AppExeName "SmartDrive-Guardian-AI.exe"
#define AppPublisher "Hiranya Bandara"
#define AppURL "https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI"

[Setup]
; AppId identifies the product for upgrades and uninstallation. Never change it.
AppId={{51BC4F81-DD29-4FD6-AF2B-AD4B87C5FCED}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=Copyright (c) 2026 Hiranya Bandara. MIT License.
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
InfoBeforeFile=installer\before-install.txt
OutputDir={#OutputDir}
OutputBaseFilename=SmartDrive-Guardian-AI-Setup-v{#AppVersion}
SetupIconFile=..\src\smartdrive\branding\smartdrive-icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
WizardImageFile=installer\wizard-image.bmp,installer\wizard-image-200.bmp
WizardSmallImageFile=installer\wizard-small.bmp,installer\wizard-small-200.bmp
Compression=lzma2/max
SolidCompression=yes
; Use the Windows Restart Manager to close a running copy before files are replaced.
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesAssociations=no
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove the previous version's bundled libraries before an upgrade so that old and new files
; never mix. This folder contains only application files, never user data.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "Offline vehicle diagnostics assistant"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    MsgBox('SmartDrive Guardian AI has been removed.' + #13#10 + #13#10 +
      'Your vehicles, trips, maintenance records, settings, logs and backups were kept in:' + #13#10 +
      ExpandConstant('{localappdata}') + '\SmartDriveGuardianAI' + #13#10 + #13#10 +
      'Delete that folder yourself if you no longer need the data. Reports you exported are ' +
      'wherever you saved them.', mbInformation, MB_OK);
end;
