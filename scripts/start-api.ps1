Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment was not found. Run scripts/setup.ps1 first."
}

Set-Location $ProjectRoot
& $VenvPython -m uvicorn sandbox.main:app --reload
