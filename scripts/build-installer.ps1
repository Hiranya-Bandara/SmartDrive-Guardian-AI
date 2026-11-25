<#
.SYNOPSIS
    Compiles the Inno Setup installer from the verified PyInstaller distribution.
.DESCRIPTION
    Requires Inno Setup 6 (free: https://jrsoftware.org/isinfo.php). ISCC.exe is looked up in
    -Iscc, then $env:ISCC, then PATH, then the default installation folders.
    The version is read from smartdrive.__version__ and passed to the script, so the installer,
    executable and application always agree.
    Output: release\SmartDrive-Guardian-AI-Setup-v<version>.exe (unsigned).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
#>
[CmdletBinding()]
param(
    [string]$Iscc
)

. "$PSScriptRoot\_common.ps1"
Set-Location -LiteralPath $script:ProjectRoot

function Find-Iscc {
    param([string]$Explicit)
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Explicit) { $candidates.Add($Explicit) }
    if ($env:ISCC) { $candidates.Add($env:ISCC) }
    $onPath = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($onPath) { $candidates.Add($onPath.Source) }
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
        if ($base) { $candidates.Add((Join-Path $base 'Inno Setup 6\ISCC.exe')) }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw 'Inno Setup 6 (ISCC.exe) was not found. Install it from https://jrsoftware.org/isinfo.php or pass -Iscc <path>.'
}

$python = Resolve-ProjectPython
$version = Get-AppVersion -Python $python
$iscc = Find-Iscc -Explicit $Iscc
$dist = Join-Path $script:ProjectRoot "dist\$script:DistName"
$exe = Join-Path $dist $script:ExeName
if (-not (Test-Path -LiteralPath $exe)) {
    throw "No distribution at '$dist'. Run scripts\build-windows.ps1 first."
}
$built = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
if ($built -ne $version) {
    throw "The distribution is version '$built' but the sources are $version. Rebuild it first."
}

$release = Join-Path $script:ProjectRoot 'release'
New-Item -ItemType Directory -Force -Path $release | Out-Null
$output = Join-Path $release "SmartDrive-Guardian-AI-Setup-v$version.exe"
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }

Write-Host "  ISCC: $iscc"
Invoke-Checked "Compiling installer for $version" {
    & $iscc "/DAppVersion=$version" "/DDistDir=$dist" "/DOutputDir=$release" (Join-Path $script:ProjectRoot 'packaging\installer.iss')
}
if (-not (Test-Path -LiteralPath $output)) { throw "ISCC reported success but '$output' does not exist." }

$info = (Get-Item -LiteralPath $output).VersionInfo
Write-Host ''
Write-Host ("Installer built: {0} ({1:N0} MB, product version {2})" -f $output, ((Get-Item -LiteralPath $output).Length / 1MB), $info.ProductVersion) -ForegroundColor Green
Write-Host 'The installer is not code-signed. Compilation alone does not verify it; follow docs\release-verification.md.'
