"""Offline mutation check: reversed assignability must fail the derived-text assertion.

Run after the normal UiDraftTests passes. Only a temporary source copy is mutated;
only fake-export/owned-buffer tests execute. No candidate entrypoint or game is loaded.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

module = Path(__file__).resolve().parent.parent
if shutil.which("dotnet") is None:
    raise SystemExit("BLOCKED: .NET SDK required; mutation check did not run")
with tempfile.TemporaryDirectory(prefix="fa-ui-assignability-mutation-") as directory:
    target = Path(directory) / "game-bridge"
    for name in ("src", "windows-smoke-draft", "windows-ui-smoke-draft"):
        shutil.copytree(module / name, target / name,
                        ignore=shutil.ignore_patterns("bin", "obj", "__pycache__"))
    adapter = target / "windows-ui-smoke-draft/WindowsLoadedModuleLease.Ui.cs"
    source = adapter.read_text(encoding="utf-8")
    original = "assignable(textElement, type)"
    if source.count(original) != 1:
        raise SystemExit("FAIL: expected exactly one production assignability call")
    adapter.write_text(source.replace(original, "assignable(type, textElement)"), encoding="utf-8")
    result = subprocess.run(
        ["dotnet", "run", "--project", str(target / "windows-ui-smoke-draft/UiDraftTests.csproj")],
        cwd=target, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
    )
    expected = "base-first IsAssignableFrom accepts derived label"
    if result.returncode == 0 or expected not in result.stdout:
        print(result.stdout)
        raise SystemExit("FAIL: reversed arguments did not fail the specific derived-text assertion")
print("PASS: reversed assignability arguments fail the derived-text assertion (fake exports only)")
