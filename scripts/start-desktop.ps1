Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment was not found. Run scripts/setup.ps1 first."
}

Set-Location $ProjectRoot
& $VenvPython -c "import PySide6" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 is not installed in .venv. Run scripts/setup.ps1 -Desktop first."
}
& $VenvPython -m sandbox.desktop.main
