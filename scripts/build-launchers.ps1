Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"
$BuildRoot = Join-Path $ProjectRoot "build\\pyinstaller"
$WorkPath = Join-Path $BuildRoot "work"
$SpecPath = Join-Path $BuildRoot "spec"

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment was not found. Run scripts/setup.ps1 first."
}

& $VenvPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $VenvPython -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install PyInstaller."
    }
}

if (Test-Path $BuildRoot) {
    Remove-Item $BuildRoot -Recurse -Force
}

$Launchers = @(
    @{ Name = "sandbox-setup"; Entry = "launcher_sources\\setup_launcher.py" },
    @{ Name = "sandbox-run-tests"; Entry = "launcher_sources\\run_tests_launcher.py" },
    @{ Name = "sandbox-start-api"; Entry = "launcher_sources\\start_api_launcher.py" },
    @{ Name = "sandbox-demo-request"; Entry = "launcher_sources\\demo_request_launcher.py" },
    @{ Name = "sandbox-start-desktop"; Entry = "launcher_sources\\start_desktop_launcher.py" },
    @{ Name = "sandbox-run-desktop-smoke"; Entry = "launcher_sources\\run_desktop_smoke_launcher.py" }
)

foreach ($Launcher in $Launchers) {
    & $VenvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name $Launcher.Name `
        --distpath $ProjectRoot `
        --workpath $WorkPath `
        --specpath $SpecPath `
        (Join-Path $ProjectRoot $Launcher.Entry)

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to build launcher: $($Launcher.Name)"
    }
}

Write-Host "Launcher exes published to root directory."
