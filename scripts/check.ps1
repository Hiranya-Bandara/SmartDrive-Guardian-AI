<#
.SYNOPSIS
    Runs the same quality gates as CI: lint, format check, strict typing and tests with coverage.
#>
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = '.\.venv\Scripts\python.exe'

$steps = @(
    @('ruff', 'check', '.'),
    @('ruff', 'format', '--check', '.'),
    @('mypy'),
    @('pytest', '--cov')
)
foreach ($step in $steps) {
    Write-Host "==> $($step -join ' ')" -ForegroundColor Cyan
    & $python -m @step
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host 'All checks passed.' -ForegroundColor Green
