from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_powershell() -> str:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell"


def run_script(script_name: str) -> int:
    project_root = resolve_project_root()
    script_path = project_root / "scripts" / script_name

    if not script_path.exists():
        print(f"Script was not found: {script_path}", file=sys.stderr)
        return 1

    command = [
        resolve_powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *sys.argv[1:],
    ]
    return subprocess.call(command, cwd=project_root)
