<#
.SYNOPSIS
    Verifies the contents of release\ before anything is published.
.DESCRIPTION
    Checks that every expected artifact exists, that SHA256SUMS.txt matches the files, that the
    portable ZIP contains a complete one-folder build, that executable and installer carry the
    source version, that the SBOM is valid CycloneDX for this version, and reports the
    code-signing state. It does not replace the manual installer checks in
    docs\release-verification.md.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1
#>
[CmdletBinding()]
param(
    [switch]$AllowMissingInstaller
)

. "$PSScriptRoot\_common.ps1"
Set-Location -LiteralPath $script:ProjectRoot

$python = Resolve-ProjectPython
$version = Get-AppVersion -Python $python
$release = Join-Path $script:ProjectRoot 'release'
$failures = New-Object System.Collections.Generic.List[string]
function Fail([string]$Message) { $failures.Add($Message); Write-Host "  FAIL $Message" -ForegroundColor Red }
function Pass([string]$Message) { Write-Host "  ok   $Message" -ForegroundColor Green }

Write-Step "Release folder for $version"
$expected = @(
    'SmartDrive-Guardian-AI-Windows-x64.zip',
    "SmartDrive-Guardian-AI-Setup-v$version.exe",
    'SHA256SUMS.txt',
    "SmartDrive-Guardian-AI-v$version-sbom.json",
    'RELEASE_NOTES.md',
    'THIRD_PARTY_NOTICES.md',
    'BUILD_INFORMATION.json'
)
foreach ($name in $expected) {
    $path = Join-Path $release $name
    if (Test-Path -LiteralPath $path) { Pass $name }
    elseif ($AllowMissingInstaller -and $name -like '*Setup*') { Write-Host "  skip $name (installer not built)" -ForegroundColor Yellow }
    else { Fail "$name is missing" }
}

Write-Step 'Checksums'
$sums = Join-Path $release 'SHA256SUMS.txt'
if (Test-Path -LiteralPath $sums) {
    $listed = @{}
    foreach ($line in Get-Content -LiteralPath $sums) {
        if (-not $line.Trim()) { continue }
        $hash, $name = $line -split '\s+', 2
        $listed[$name.Trim()] = $hash.ToLowerInvariant()
    }
    foreach ($file in Get-ChildItem -LiteralPath $release -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' }) {
        if (-not $listed.ContainsKey($file.Name)) { Fail "$($file.Name) is not listed in SHA256SUMS.txt"; continue }
        if ($listed[$file.Name] -eq (Get-FileSha256 -Path $file.FullName)) { Pass "$($file.Name) checksum matches" }
        else { Fail "$($file.Name) does not match its checksum (rebuilt after generate-checksums.ps1?)" }
    }
    foreach ($name in $listed.Keys) {
        if (-not (Test-Path -LiteralPath (Join-Path $release $name))) { Fail "SHA256SUMS.txt lists missing file $name" }
    }
}

Write-Step 'Portable ZIP'
$zip = Join-Path $release 'SmartDrive-Guardian-AI-Windows-x64.zip'
if (Test-Path -LiteralPath $zip) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $names = @($archive.Entries | ForEach-Object { $_.FullName })
    } finally {
        $archive.Dispose()
    }
    $backslashes = @($names | Where-Object { $_.Contains('\') })
    if ($backslashes.Count -gt 0) { Fail "ZIP has $($backslashes.Count) entry names with backslashes (not portable)" }
    foreach ($entry in @(
            "$script:DistName/$script:ExeName",
            "$script:DistName/LICENSE.txt",
            "$script:DistName/THIRD_PARTY_NOTICES.md",
            "$script:DistName/_internal/python312.dll",
            "$script:DistName/_internal/smartdrive/ai/artifacts/manifest.json")) {
        if ($names -contains $entry) { Pass "ZIP contains $entry" } else { Fail "ZIP is missing $entry" }
    }
    $unwanted = @($names | Where-Object { $_ -match '\.(db|db-wal|log)$' -or $_ -match '(^|/)(\.venv|__pycache__|\.git)/' })
    if ($unwanted.Count -gt 0) { Fail ("ZIP contains files that must not be shipped: " + ($unwanted -join ', ')) }
    else { Pass 'ZIP contains no databases, logs, caches or virtual environments' }
}

Write-Step 'Version resources and signatures'
$exe = Join-Path $script:ProjectRoot "dist\$script:DistName\$script:ExeName"
$installer = Join-Path $release "SmartDrive-Guardian-AI-Setup-v$version.exe"
foreach ($binary in @($exe, $installer)) {
    if (-not (Test-Path -LiteralPath $binary)) { continue }
    $info = (Get-Item -LiteralPath $binary).VersionInfo
    if ($info.ProductVersion -like "$version*") { Pass "$(Split-Path -Leaf $binary) product version $($info.ProductVersion)" }
    else { Fail "$(Split-Path -Leaf $binary) product version is '$($info.ProductVersion)', expected $version" }
    $signature = Get-AuthenticodeSignature -LiteralPath $binary
    Write-Host ("  info {0} signature: {1}" -f (Split-Path -Leaf $binary), $signature.Status) -ForegroundColor Yellow
}

Write-Step 'SBOM'
$sbom = Join-Path $release "SmartDrive-Guardian-AI-v$version-sbom.json"
if (Test-Path -LiteralPath $sbom) {
    & $python -c "import json, sys; from cyclonedx.schema import SchemaVersion; from cyclonedx.validation.json import JsonStrictValidator; text = open(sys.argv[1], encoding='utf-8').read(); error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(text); data = json.loads(text); sys.exit(1 if error or data['metadata']['component']['version'] != sys.argv[2] else 0)" $sbom $version
    if ($LASTEXITCODE -eq 0) { Pass 'SBOM is valid CycloneDX 1.6 for this version' } else { Fail 'SBOM is invalid or for another version' }
}

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "Release verification FAILED ($($failures.Count) problem(s))." -ForegroundColor Red
    exit 1
}
Write-Host 'Release folder verified. Manual installer verification is still required (docs\release-verification.md).' -ForegroundColor Green
exit 0
