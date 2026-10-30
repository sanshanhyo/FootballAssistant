"""Run native own-process toy coverage on the existing Windows pytest runner."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native reader toy")
def test_windows_native_reader(tmp_path: Path) -> None:
    program_files = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        pytest.fail(f"Native reader tests require installed VS C++ tools: {vswhere}")
    discovery = subprocess.run(
        [str(vswhere), "-latest", "-products", "*", "-requires",
         "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert discovery.returncode == 0, discovery.stdout + discovery.stderr
    installations = discovery.stdout.strip().splitlines()
    assert installations, "No installed Visual Studio x64 C++ toolchain found"
    vcvars = Path(installations[0]) / "VC/Auxiliary/Build/vcvars64.bat"
    assert vcvars.is_file(), f"Missing x64 compiler environment: {vcvars}"
    repo = Path(__file__).resolve().parents[3]
    build = repo / "modules/game-bridge/windows-reader/scripts/build.py"
    assert build.is_file(), f"Missing native reader build script: {build}"
    command = tmp_path / "native-reader-test.cmd"
    command.write_text(
        f'@echo off\ncall "{vcvars}"\nif errorlevel 1 exit /b 1\n'
        f'"{sys.executable}" "{build}"\nexit /b %errorlevel%\n', encoding="utf-8",
    )
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(command)],
        cwd=repo, capture_output=True, text=True, errors="replace", timeout=180, check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "portable + Windows native toy tests passed" in output, output
    assert "Built DLL ctypes ABI/self-inspection passed" in output, output
