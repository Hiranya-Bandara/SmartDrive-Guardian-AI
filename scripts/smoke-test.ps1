<#
.SYNOPSIS
    Smoke-tests the packaged Windows executable (not the Python sources).
.DESCRIPTION
    1. Runs "SmartDrive-Guardian-AI.exe self-test" in a temporary data folder. The self-test
       migrates a fresh database, loads the bundled models, runs a simulated drive through the
       diagnostic engine, records a trip and a maintenance entry, writes a PDF and a CSV, lists
       serial ports (without opening any), starts the offline voice backend and the Qt platform
       plugin, and checks the log file.
    2. Starts the desktop application for a few seconds (all pages are built at start-up) and
       requires a clean exit.
    The developer's virtual environment is not used: the executable runs with PATH reduced to
    the Windows system folders and without PYTHONHOME/PYTHONPATH.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1 -Executable "C:\Program Files\SmartDrive Guardian AI\SmartDrive-Guardian-AI.exe"
#>
[CmdletBinding()]
param(
    [string]$Executable,
    [int]$GuiSeconds = 8,
    [string]$ReportPath
)

. "$PSScriptRoot\_common.ps1"

if (-not $Executable) {
    $Executable = Join-Path $script:ProjectRoot "dist\$script:DistName\$script:ExeName"
}
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "Executable not found: '$Executable'. Build it with scripts\build-windows.ps1."
}
$Executable = (Resolve-Path -LiteralPath $Executable).Path
if (-not $ReportPath) {
    $ReportPath = Join-Path $script:ProjectRoot 'build\smoke-test\self-test.json'
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("SmartDrive smoke " + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $work | Out-Null

# Run without the developer's Python on PATH, so missing DLLs in the build cannot be masked.
$savedPath = $env:PATH
$savedPythonPath = $env:PYTHONPATH
$savedPythonHome = $env:PYTHONHOME
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue

$failures = New-Object System.Collections.Generic.List[string]
try {
    Write-Step "Self-test of $Executable"
    $selfTestHome = Join-Path $work 'self-test data'
    $arguments = @('--home', "`"$selfTestHome`"", 'self-test', '--report', "`"$ReportPath`"")
    $process = Start-Process -FilePath $Executable -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if (-not (Test-Path -LiteralPath $ReportPath)) {
        $failures.Add("Self-test wrote no report (exit code $($process.ExitCode)).")
    } else {
        $report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
        foreach ($check in $report.checks) {
            $mark = if ($check.ok) { 'PASS' } else { 'FAIL' }
            $colour = if ($check.ok) { 'Green' } else { 'Red' }
            Write-Host ("  [{0}] {1}: {2}" -f $mark, $check.name, $check.detail) -ForegroundColor $colour
        }
        if (-not $report.frozen) { $failures.Add('The self-test did not run from a frozen executable.') }
        if (-not $report.passed -or $process.ExitCode -ne 0) {
            $failures.Add("Self-test failed (exit code $($process.ExitCode)).")
        }
    }

    Write-Step "Desktop application start-up ($GuiSeconds s)"
    $guiHome = Join-Path $work 'gui data'
    $arguments = @('--home', "`"$guiHome`"", 'gui', '--quit-after-ms', ($GuiSeconds * 1000))
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $Executable -ArgumentList $arguments -PassThru
    if (-not $process.WaitForExit(($GuiSeconds + 60) * 1000)) {
        $process.Kill()
        $failures.Add('The desktop application did not exit after its quit timer.')
    } elseif ($process.ExitCode -ne 0) {
        $failures.Add("The desktop application exited with code $($process.ExitCode).")
    }
    $watch.Stop()
    $log = Join-Path $guiHome 'logs\smartdrive.log'
    if (-not (Test-Path -LiteralPath $log)) {
        $failures.Add("No log file was written at '$log'.")
    } else {
        $errors = @(Select-String -LiteralPath $log -Pattern '"level": "(ERROR|CRITICAL)"')
        if ($errors.Count -gt 0) {
            $failures.Add("The log contains $($errors.Count) error entr(y/ies); see '$log'.")
        }
        Write-Host ("  Desktop application ran {0:N1} s and exited with code {1}." -f $watch.Elapsed.TotalSeconds, $process.ExitCode)
    }
} finally {
    $env:PATH = $savedPath
    if ($savedPythonPath) { $env:PYTHONPATH = $savedPythonPath }
    if ($savedPythonHome) { $env:PYTHONHOME = $savedPythonHome }
}

if ($failures.Count -gt 0) {
    Write-Host ''
    $failures | ForEach-Object { Write-Host "FAILED: $_" -ForegroundColor Red }
    Write-Host "Temporary data kept for inspection: $work"
    exit 1
}
Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ''
Write-Host 'Packaged application smoke test PASSED.' -ForegroundColor Green
Write-Host "Report: $ReportPath"
exit 0
