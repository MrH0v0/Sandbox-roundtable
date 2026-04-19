param(
    [string]$PythonExe,
    [switch]$Desktop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ResolvedPythonExe = $null

if ($PythonExe) {
    if (-not (Test-Path $PythonExe)) {
        throw "Specified Python was not found: $PythonExe"
    }
    $ResolvedPythonExe = $PythonExe
}

if (-not $ResolvedPythonExe -and $env:SANDBOX_PYTHON_EXE) {
    if (-not (Test-Path $env:SANDBOX_PYTHON_EXE)) {
        throw "SANDBOX_PYTHON_EXE points to a missing file: $env:SANDBOX_PYTHON_EXE"
    }
    $ResolvedPythonExe = $env:SANDBOX_PYTHON_EXE
}

if (-not $ResolvedPythonExe) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        try {
            & py -3.11 -V | Out-Null
            $ResolvedPythonExe = "py -3.11"
        } catch {
            $ResolvedPythonExe = $null
        }
    }
}

if (-not $ResolvedPythonExe) {
    throw "Python 3.11 was not found. Pass -PythonExe or set SANDBOX_PYTHON_EXE."
}

$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\\python.exe"

if (-not (Test-Path $VenvPython)) {
    if ($ResolvedPythonExe -eq "py -3.11") {
        & py -3.11 -m venv $VenvPath
    } else {
        & $ResolvedPythonExe -m venv $VenvPath
    }
}

& $VenvPython -m pip install --upgrade pip
if ($Desktop) {
    & $VenvPython -m pip install -e ".[desktop,dev]"
} else {
    & $VenvPython -m pip install -e ".[dev]"
}

Write-Host "Environment setup completed."
Write-Host "Virtual environment: $VenvPath"
if ($Desktop) {
    Write-Host "Desktop dependencies installed."
}
