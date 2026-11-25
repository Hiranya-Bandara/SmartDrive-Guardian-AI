<#
.SYNOPSIS
    Regenerates requirements.txt and requirements-dev.txt from pyproject.toml (the authoritative source).
.NOTES
    Requires uv (https://docs.astral.sh/uv/):  .\.venv\Scripts\python.exe -m pip install uv
    The --universal flag resolves one lock file that is valid on Windows, Linux and macOS.
#>
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$header = '# Generated from pyproject.toml - do not edit by hand. Regenerate with scripts/lock-dependencies.ps1'

$targets = @(
    @{ File = 'requirements.txt'; Extra = @() },
    @{ File = 'requirements-dev.txt'; Extra = @('--extra', 'dev') },
    # Release tools are locked against the dev pins so that one environment can hold both and the
    # runtime versions in the build are exactly those in requirements.txt.
    @{ File = 'requirements-release.txt'; Extra = @('--extra', 'release', '-c', 'requirements-dev.txt') }
)
foreach ($target in $targets) {
    uv pip compile pyproject.toml @($target.Extra) --universal --python-version 3.12 --no-header -q -o $target.File
    if ($LASTEXITCODE -ne 0) { throw "Locking $($target.File) failed" }
    $body = Get-Content $target.File
    Set-Content -Path $target.File -Value (@($header) + $body) -Encoding utf8
    Write-Host "Updated $($target.File)"
}
