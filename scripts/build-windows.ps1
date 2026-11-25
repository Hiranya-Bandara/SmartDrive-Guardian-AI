[CmdletBinding()]
param(
    [switch]$SkipChecks,
    [switch]$SkipSmokeTest
)

. "$PSScriptRoot\_common.ps1"
Set-Location -LiteralPath $script:ProjectRoot

if ($env:OS -ne 'Windows_NT') {
    throw 'The Windows distribution must be built on Windows.'
}

Write-Step 'Checking prerequisites'

$python = Resolve-ProjectPython
$version = Get-AppVersion -Python $python

Assert-PythonModule -Python $python -Module 'PyInstaller' -Hint 'Install the release tools: .\.venv\Scripts\python.exe -m pip install -r requirements-release.txt'

Assert-PythonModule -Python $python -Module 'smartdrive' -Hint 'Install the project: .\.venv\Scripts\python.exe -m pip install --no-deps -e .'

Invoke-Checked 'Dependency consistency (pip check)' {
    & $python -m pip check
}

Write-Host "  Python: $python"
Write-Host "  Version: $version"

if (-not $SkipChecks) {
    Invoke-Checked 'Ruff lint' {
        & $python -m ruff check .
    }

    Invoke-Checked 'Ruff format check' {
        & $python -m ruff format --check .
    }

    Invoke-Checked 'Mypy' {
        & $python -m mypy
    }

    Invoke-Checked 'Pytest' {
        & $python -m pytest -q
    }
}

$dist = Join-Path $script:ProjectRoot "dist\$script:DistName"
$work = Join-Path $script:ProjectRoot 'build\pyinstaller'

Write-Step 'Removing previous build output'

Remove-GeneratedDirectory -Path $dist
Remove-GeneratedDirectory -Path $work

Invoke-Checked 'PyInstaller' {
    & $python -m PyInstaller `
        (Join-Path $script:ProjectRoot 'packaging\smartdrive.spec') `
        --noconfirm `
        --clean `
        --distpath (Join-Path $script:ProjectRoot 'dist') `
        --workpath $work
}

Write-Step 'Validating the distribution'

$internal = Join-Path $dist '_internal'

$required = @(
    (Join-Path $dist $script:ExeName),
    (Join-Path $internal 'python312.dll'),
    (Join-Path $internal 'smartdrive\branding\smartdrive-icon.ico'),
    (Join-Path $internal 'smartdrive\ui\themes\stylesheet.qss'),
    (Join-Path $internal 'smartdrive\ai\artifacts\manifest.json'),
    (Join-Path $internal 'smartdrive\database\migrations\env.py')
)

$missing = @(
    $required | Where-Object {
        -not (Test-Path -LiteralPath $_)
    }
)

if ($missing.Count -gt 0) {
    throw (
        "Build output is incomplete. Missing:`n  " +
        ($missing -join "`n  ")
    )
}

foreach ($plugin in @('qwindows.dll', 'qsvg.dll', 'qsvgicon.dll')) {
    $found = @(
        Get-ChildItem `
            -LiteralPath (Join-Path $internal 'PySide6') `
            -Recurse `
            -Filter $plugin `
            -ErrorAction SilentlyContinue
    )

    if ($found.Count -eq 0) {
        throw "Qt plugin $plugin is missing from the build."
    }
}

$models = @(
    Get-ChildItem `
        -LiteralPath (Join-Path $internal 'smartdrive\ai\artifacts') `
        -Filter '*.joblib'
)

$migrations = @(
    Get-ChildItem `
        -LiteralPath (Join-Path $internal 'smartdrive\database\migrations\versions') `
        -Filter '*.py'
)

if ($models.Count -lt 2) {
    throw 'Model artifacts are missing from the build.'
}

if ($migrations.Count -lt 3) {
    throw 'Database migration scripts are missing from the build.'
}

$macOnly = @(
    Get-ChildItem `
        -LiteralPath $internal `
        -Directory `
        -Filter 'objc*' `
        -ErrorAction SilentlyContinue
)

if ($macOnly.Count -gt 0) {
    throw 'macOS-only packages were bundled into the Windows build.'
}

$exePath = Join-Path $dist $script:ExeName
$exeInfo = (Get-Item -LiteralPath $exePath).VersionInfo

if ($exeInfo.ProductVersion -ne $version) {
    throw "Executable product version '$($exeInfo.ProductVersion)' does not match $version."
}

Write-Host "  Executable version resource: $($exeInfo.ProductName) $($exeInfo.ProductVersion)"
Write-Host "  Models: $($models.Count); migrations: $($migrations.Count)"

Write-Step 'Adding licence and usage notes'

Copy-Item `
    -LiteralPath (Join-Path $script:ProjectRoot 'LICENSE') `
    -Destination (Join-Path $dist 'LICENSE.txt') `
    -Force

Copy-Item `
    -LiteralPath (Join-Path $script:ProjectRoot 'THIRD_PARTY_NOTICES.md') `
    -Destination (Join-Path $dist 'THIRD_PARTY_NOTICES.md') `
    -Force

Copy-Item `
    -LiteralPath (Join-Path $script:ProjectRoot 'packaging\release-assets\README-portable.txt') `
    -Destination (Join-Path $dist 'README.txt') `
    -Force

if (-not $SkipSmokeTest) {
    & (Join-Path $PSScriptRoot 'smoke-test.ps1') -Executable $exePath

    if ($LASTEXITCODE -ne 0) {
        throw 'The packaged application smoke test failed.'
    }
}

Write-Step 'Creating the portable ZIP'

$release = Join-Path $script:ProjectRoot 'release'

New-Item `
    -ItemType Directory `
    -Force `
    -Path $release | Out-Null

$zip = Join-Path $release 'SmartDrive-Guardian-AI-Windows-x64.zip'

if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}

Invoke-Checked 'Creating portable ZIP archive' {
    & $python -m zipfile -c $zip $dist
}

if (-not (Test-Path -LiteralPath $zip)) {
    throw 'Portable ZIP archive was not created.'
}

Invoke-Checked 'Testing portable ZIP integrity' {
    & $python -m zipfile -t $zip
}

Write-Step 'Validating portable ZIP structure'

$zipValidation = @'
import sys
from zipfile import ZipFile

required = {
    "SmartDrive-Guardian-AI/SmartDrive-Guardian-AI.exe",
    "SmartDrive-Guardian-AI/LICENSE.txt",
    "SmartDrive-Guardian-AI/THIRD_PARTY_NOTICES.md",
    "SmartDrive-Guardian-AI/README.txt",
    "SmartDrive-Guardian-AI/_internal/python312.dll",
    "SmartDrive-Guardian-AI/_internal/smartdrive/ai/artifacts/manifest.json",
}

with ZipFile(sys.argv[1], "r") as archive:
    names = set(archive.namelist())

    invalid = sorted(name for name in names if "\\" in name)

    if invalid:
        raise SystemExit(
            f"ZIP contains {len(invalid)} invalid backslash entry names."
        )

    missing = sorted(required - names)

    if missing:
        raise SystemExit(
            "Required ZIP entries are missing:\n" + "\n".join(missing)
        )

    print(f"  ZIP entries verified: {len(names)}")

    for name in sorted(required):
        print(f"  ok   {name}")

print("  Portable ZIP structure verified successfully.")
'@

Invoke-Checked 'Portable ZIP structure validation' {
    & $python -c $zipValidation $zip
}

$size = (Get-Item -LiteralPath $zip).Length / 1MB

$folderSize = (
    Get-ChildItem -LiteralPath $dist -Recurse -File |
    Measure-Object -Property Length -Sum
).Sum / 1MB

Write-Host ''

Write-Host (
    "Build complete: SmartDrive Guardian AI {0}" -f $version
) -ForegroundColor Green

Write-Host (
    "  Distribution folder: {0} ({1:N0} MB)" -f $dist, $folderSize
)

Write-Host (
    "  Portable ZIP:        {0} ({1:N0} MB)" -f $zip, $size
)

Write-Host '  Next: scripts\build-installer.ps1, then scripts\generate-checksums.ps1'