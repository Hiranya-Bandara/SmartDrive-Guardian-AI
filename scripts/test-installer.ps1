<#
.SYNOPSIS
    Installs, smoke-tests, upgrades and uninstalls the Windows installer silently.
.DESCRIPTION
    Uses a per-user installation into a folder whose path contains spaces, and a separate user
    data folder (--home) so the computer's own SmartDrive data is never touched:
      1. Fresh install (/CURRENTUSER, no elevation) into "<temp>\Install Test\SmartDrive Guardian AI".
      2. Smoke test of the installed executable (scripts\smoke-test.ps1).
      3. A data folder is created with the installed app (database, settings).
      4. Reinstall over the existing installation (upgrade path); the data must be unchanged.
      5. Uninstall; program files and shortcuts must be gone, the data folder must remain.
    Interactive checks (Start Menu and desktop shortcuts, the wizard pages, running as a standard
    user account, files in use) remain manual: see docs\release-verification.md.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\test-installer.ps1
#>
[CmdletBinding()]
param(
    [string]$Installer
)

. "$PSScriptRoot\_common.ps1"
Set-Location -LiteralPath $script:ProjectRoot

$python = Resolve-ProjectPython
$version = Get-AppVersion -Python $python
if (-not $Installer) { $Installer = Join-Path $script:ProjectRoot "release\SmartDrive-Guardian-AI-Setup-v$version.exe" }
if (-not (Test-Path -LiteralPath $Installer)) { throw "Installer not found: '$Installer'. Run scripts\build-installer.ps1." }
$Installer = (Resolve-Path -LiteralPath $Installer).Path

$root = Join-Path ([System.IO.Path]::GetTempPath()) ('SmartDrive installer test ' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$installDir = Join-Path $root 'Install Test\SmartDrive Guardian AI'
$dataDir = Join-Path $root 'User Data'
$logDir = Join-Path $script:ProjectRoot 'build\installer-test'
New-Item -ItemType Directory -Force -Path $root, $logDir | Out-Null
$exe = Join-Path $installDir $script:ExeName
$failures = New-Object System.Collections.Generic.List[string]

function Invoke-Setup([string]$LogName) {
    $log = Join-Path $logDir $LogName
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/NOICONS', "/DIR=`"$installDir`"", "/LOG=`"$log`"")
    $process = Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Setup exited with code $($process.ExitCode); see $log" }
}

function Get-DataFingerprint {
    $files = Get-ChildItem -LiteralPath $dataDir -Recurse -File | Where-Object { $_.Extension -in @('.db', '.json') }
    return ($files | Sort-Object FullName | ForEach-Object { '{0}={1}' -f $_.Name, (Get-FileSha256 -Path $_.FullName) }) -join ';'
}

try {
    Write-Step "Fresh per-user install into '$installDir'"
    Invoke-Setup 'install.log'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'The executable was not installed.' }
    $installed = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
    if ($installed -ne $version) { $failures.Add("Installed version $installed, expected $version.") }

    & (Join-Path $PSScriptRoot 'smoke-test.ps1') -Executable $exe -ReportPath (Join-Path $logDir 'installed-self-test.json')
    if ($LASTEXITCODE -ne 0) { $failures.Add('Smoke test of the installed application failed.') }

    Write-Step 'Creating user data with the installed application'
    $process = Start-Process -FilePath $exe -ArgumentList @('--home', "`"$dataDir`"", 'db', 'check') -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { $failures.Add('Could not create user data with the installed application.') }
    $before = Get-DataFingerprint
    if (-not $before) { $failures.Add('No user data files were created.') }

    Write-Step 'Reinstalling over the existing installation (upgrade path)'
    Invoke-Setup 'upgrade.log'
    if ((Get-DataFingerprint) -ne $before) { $failures.Add('User data changed during the reinstall.') }
    $process = Start-Process -FilePath $exe -ArgumentList @('--home', "`"$dataDir`"", 'db', 'check') -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { $failures.Add('The application failed to open existing data after the reinstall.') }
    # Opening the database may legitimately rewrite it; compare the uninstall against this state.
    $before = Get-DataFingerprint

    Write-Step 'Uninstalling'
    $uninstaller = Get-ChildItem -LiteralPath $installDir -Filter 'unins*.exe' | Select-Object -First 1
    if (-not $uninstaller) { throw 'No uninstaller was installed.' }
    $process = Start-Process -FilePath $uninstaller.FullName -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$(Join-Path $logDir 'uninstall.log')`"") -Wait -PassThru
    if ($process.ExitCode -ne 0) { $failures.Add("Uninstaller exited with code $($process.ExitCode).") }
    Start-Sleep -Seconds 3  # the uninstaller removes itself from a temporary copy
    if (Test-Path -LiteralPath $exe) { $failures.Add('The executable is still present after uninstalling.') }
    if (Test-Path -LiteralPath (Join-Path $installDir '_internal')) { $failures.Add('Application files remain after uninstalling.') }
    if ((Get-DataFingerprint) -ne $before) { $failures.Add('User data was changed or removed by the uninstaller.') }
} finally {
    Write-Host "Logs: $logDir"
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAILED: $_" -ForegroundColor Red }
    Write-Host "Test folder kept: $root"
    exit 1
}
Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'Automated installer test PASSED (install, smoke test, reinstall with data preserved, uninstall).' -ForegroundColor Green
exit 0
