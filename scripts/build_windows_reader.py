"""Build the existing read-only CLI for clean Windows installs; no game inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = "OffseasonReaderCli.exe"

def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()

def inventory(root):
    result = {}
    for file in sorted(root.rglob("*")):
        if file.is_symlink():
            raise ValueError("Reader payload must not contain symlinks")
        if file.is_file() and file != root / "manifest.json":
            result[file.relative_to(root).as_posix()] = digest(file)
    return result

def finalize(output, runtime_package, commit):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Exact source commit required")
    for name in [ENTRYPOINT, "OffseasonReaderCli.dll", "FootballAssistant.OffseasonReader.dll", "coreclr.dll", "hostfxr.dll", "hostpolicy.dll"]:
        file = output / name
        if not file.is_file() or file.read_bytes()[:2] != b"MZ":
            raise ValueError(f"Missing compiled Windows reader/runtime: {name}")
    licenses = output / "licenses"
    licenses.mkdir()
    for name in ["LICENSE.TXT", "THIRD-PARTY-NOTICES.TXT"]:
        candidates = [p for p in runtime_package.iterdir() if p.name.lower().replace("-", "") == name.lower().replace("-", "")]
        if len(candidates) != 1 or not candidates[0].is_file() or candidates[0].stat().st_size < 100:
            raise ValueError(f"Missing full .NET runtime notice: {name}")
        shutil.copyfile(candidates[0], licenses / name)
    shutil.copyfile(ROOT / "LICENSE", licenses / "FootballAssistant-LICENSE.txt")
    manifest = {"schema": 1, "target": "win32-x64", "entrypoint": ENTRYPOINT,
        "buildCommit": commit, "runtimeVersion": runtime_package.name,
        "producerId": "footballassistant.offseason-reader", "protocol": "fa-offseason/0.1",
        "gamePluginSha256": "bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f",
        "mode": "external-read-only", "gameFilesIncluded": False,
        "realGameAcceptance": "pending", "files": inventory(output)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest

def verify(output):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("target") != "win32-x64" or manifest.get("entrypoint") != ENTRYPOINT or manifest.get("files") != inventory(output):
        raise ValueError("Reader payload manifest mismatch")
    for name in [ENTRYPOINT, "OffseasonReaderCli.dll", "FootballAssistant.OffseasonReader.dll", "coreclr.dll", "hostfxr.dll", "hostpolicy.dll", "licenses/LICENSE.TXT", "licenses/THIRD-PARTY-NOTICES.TXT", "licenses/FootballAssistant-LICENSE.txt"]:
        if name not in manifest["files"]:
            raise ValueError(f"Reader payload incomplete: {name}")
    return manifest

def build(output):
    if output.exists():
        raise ValueError("Use a fresh reader output directory")
    subprocess.run(["dotnet", "publish", str(ROOT / "modules/game-bridge/offseason-reader-cli/OffseasonReaderCli.csproj"),
        "--configuration", "Release", "--runtime", "win-x64", "--self-contained", "true",
        "-p:PublishSingleFile=false", "-p:PublishTrimmed=false", "--output", str(output)], check=True, cwd=ROOT)
    deps = json.loads((output / "OffseasonReaderCli.deps.json").read_text(encoding="utf-8-sig"))
    versions = [key.split("/", 1)[1] for key in deps["libraries"] if key.lower().removeprefix("runtimepack.").startswith("microsoft.netcore.app.runtime.win-x64/")]
    if len(versions) != 1:
        raise ValueError("Cannot identify exact bundled .NET runtime")
    packages = Path(os.environ.get("NUGET_PACKAGES", str(Path.home() / ".nuget/packages")))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    finalize(output, packages / "microsoft.netcore.app.runtime.win-x64" / versions[0], commit)
    verify(output)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/reader-windows-x64")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.output), indent=2))
    else:
        build(args.output)
