<#
.SYNOPSIS
    Creates the development virtual environment, installs pinned dependencies and verifies the setup.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Checked {
    param([string]$Description, [scriptblock]$Command)
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed with exit code $LASTEXITCODE" }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'The Python launcher (py) was not found. Install Python 3.12 from python.org first.'
}
Invoke-Checked 'Checking Python 3.12' { py -3.12 --version }

if (-not (Test-Path '.venv')) {
    Invoke-Checked 'Creating virtual environment' { py -3.12 -m venv .venv }
}
$python = Join-Path $root '.venv\Scripts\python.exe'

Invoke-Checked 'Upgrading pip' { & $python -m pip install --upgrade pip }
Invoke-Checked 'Installing pinned dependencies' { & $python -m pip install -r requirements-dev.txt }
Invoke-Checked 'Installing SmartDrive (editable)' { & $python -m pip install --no-deps -e . }
Invoke-Checked 'Checking dependency consistency' { & $python -m pip check }

if (-not $SkipTests) {
    Invoke-Checked 'Ruff lint' { & $python -m ruff check . }
    Invoke-Checked 'Ruff format check' { & $python -m ruff format --check . }
    Invoke-Checked 'Mypy' { & $python -m mypy }
    Invoke-Checked 'Pytest' { & $python -m pytest --cov }
}

Write-Host ''
Write-Host 'Setup complete. Activate with:  .\.venv\Scripts\Activate.ps1' -ForegroundColor Green
