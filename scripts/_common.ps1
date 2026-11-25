<#
.SYNOPSIS
    Helpers shared by the build and release scripts. Dot-source it:  . "$PSScriptRoot\_common.ps1"
.NOTES
    Written for Windows PowerShell 5.1 and PowerShell 7. Paths are built from the script location,
    never from a developer's machine, and are always quoted so folders with spaces work.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:DistName = 'SmartDrive-Guardian-AI'
$script:ExeName = 'SmartDrive-Guardian-AI.exe'

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    <# Runs a native command and stops the script if it fails (no silent skips). #>
    param(
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][scriptblock]$Command
    )
    Write-Step $Description
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Resolve-ProjectPython {
    <#
    Returns the Python interpreter to use: $env:SMARTDRIVE_PYTHON if set, otherwise the project's
    .venv. Verifies that it is 64-bit CPython 3.12.
    #>
    $candidate = $env:SMARTDRIVE_PYTHON
    if (-not $candidate) {
        $candidate = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Python not found at '$candidate'. Run scripts\setup-dev.ps1 first, or set SMARTDRIVE_PYTHON."
    }
    # No double quotes inside the -c code: Windows PowerShell 5.1 mangles them for native commands.
    $probe = & $candidate -c "import platform, struct, sys; print('%d.%d %d %s' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P') * 8, platform.python_implementation()))"
    if ($LASTEXITCODE -ne 0) { throw "Could not run '$candidate'." }
    $parts = "$probe".Trim().Split(' ')
    if ($parts[0] -ne '3.12' -or $parts[1] -ne '64' -or $parts[2] -ne 'CPython') {
        throw "64-bit CPython 3.12 is required; '$candidate' is $probe."
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Get-AppVersion {
    param([Parameter(Mandatory)][string]$Python)
    $src = Join-Path $script:ProjectRoot 'src'
    $version = & $Python -c "import sys; sys.path.insert(0, sys.argv[1]); import smartdrive; print(smartdrive.__version__)" $src
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'Could not read smartdrive.__version__.' }
    return "$version".Trim()
}

function Assert-PythonModule {
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$Module,
        [Parameter(Mandatory)][string]$Hint
    )
    & $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$Module') else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python module '$Module' is missing. $Hint" }
}

function Remove-GeneratedDirectory {
    <# Deletes a generated folder, but only one inside the project's build, dist or release folders. #>
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $full = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    $allowed = @('build', 'dist', 'release') | ForEach-Object { Join-Path $script:ProjectRoot $_ }
    $inside = $false
    foreach ($root in $allowed) {
        if ($full -eq $root -or $full.StartsWith($root + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            $inside = $true
        }
    }
    if (-not $inside) { throw "Refusing to delete '$full': not a generated build folder." }
    Remove-Item -LiteralPath $full -Recurse -Force
}

function Get-FileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
