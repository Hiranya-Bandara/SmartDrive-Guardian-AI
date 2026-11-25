<#
.SYNOPSIS
    Completes the release folder: SBOM, notices, release notes, build information, SHA256SUMS.txt.
.DESCRIPTION
    Run after build-windows.ps1 (and build-installer.ps1). Checksums are computed from the files
    that are actually in release\ at this moment; rebuild anything and run this script again.
    SHA256SUMS.txt uses the common "<hash>  <file name>" format, verifiable with PowerShell
    (Get-FileHash) or sha256sum -c.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\generate-checksums.ps1
#>
[CmdletBinding()]
param()

. "$PSScriptRoot\_common.ps1"
Set-Location -LiteralPath $script:ProjectRoot

$python = Resolve-ProjectPython
$version = Get-AppVersion -Python $python
$release = Join-Path $script:ProjectRoot 'release'
$zip = Join-Path $release 'SmartDrive-Guardian-AI-Windows-x64.zip'
if (-not (Test-Path -LiteralPath $zip)) { throw "Portable ZIP not found in '$release'. Run scripts\build-windows.ps1 first." }

$metadata = Join-Path $script:ProjectRoot 'scripts\release_metadata.py'
$sbom = Join-Path $release "SmartDrive-Guardian-AI-v$version-sbom.json"
Invoke-Checked 'Software bill of materials (CycloneDX 1.6, validated)' { & $python $metadata sbom --output $sbom }
Invoke-Checked 'Third-party notices' { & $python $metadata notices --output (Join-Path $release 'THIRD_PARTY_NOTICES.md') }
Copy-Item -LiteralPath (Join-Path $script:ProjectRoot 'RELEASE_NOTES.md') -Destination (Join-Path $release 'RELEASE_NOTES.md') -Force
Invoke-Checked 'Build information' { & $python $metadata build-info --release-dir $release --output (Join-Path $release 'BUILD_INFORMATION.json') }

Write-Step 'SHA-256 checksums'
$sums = Join-Path $release 'SHA256SUMS.txt'
$lines = Get-ChildItem -LiteralPath $release -File |
    Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
    Sort-Object Name |
    ForEach-Object { '{0}  {1}' -f (Get-FileSha256 -Path $_.FullName), $_.Name }
# UTF-8 without BOM and LF line endings, so sha256sum -c also accepts the file.
[System.IO.File]::WriteAllText($sums, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
$lines | ForEach-Object { Write-Host "  $_" }
Write-Host ''
Write-Host "Wrote $sums" -ForegroundColor Green
