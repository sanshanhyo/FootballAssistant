"""Build on the target OS/architecture; build tooling is never a user dependency."""
from pathlib import Path
import subprocess
import os
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "build" / "backend-sources"
STAGING.mkdir(parents=True, exist_ok=True)
for package, source in {
    "football_assistant_data": ROOT / "modules/data-core/src/football_assistant_data",
    "football_assistant_agent": ROOT / "modules/agent-core/src/football_assistant_agent",
    "football_assistant_contracts": ROOT / "contracts",
}.items():
    destination = STAGING / package
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir()
    # Explicit code/schema allowlist; never sweep a working tree or user data.
    for file in source.rglob("*"):
        if file.is_file() and (file.suffix in {".py", ".json"} or (package == "football_assistant_agent" and file.parent.name == "resources" and file.suffix == ".md")) and "__pycache__" not in file.parts:
            target = destination / file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
    "--name", "football-assistant-backend", "--paths", str(STAGING), "--distpath", str(ROOT / "build" / "desktop-backend"),
    "--workpath", str(ROOT / "build" / "pyinstaller"), "--specpath", str(ROOT / "build"),
    "--add-data", str(STAGING / "football_assistant_contracts/schemas") + ":football_assistant_contracts/schemas",
    "--collect-all", "football_assistant_contracts", "--collect-all", "pydantic_ai",
    "--recursive-copy-metadata", "pydantic-ai-slim", "--collect-all", "genai_prices",
    "--exclude-module", "edge_tts",
    "--hidden-import", "typing_extensions", "--hidden-import", "xml.sax.saxutils",
    "--collect-all", "aiohttp", "--collect-all", "certifi", "--collect-all", "tabulate",
    "--collect-all", "uvicorn", "--collect-all", "jsonschema_specifications",
    # format-nongpl loads this grammar at import time (not a Python module).
    "--collect-data", "rfc3987_syntax",
    "--add-data", str(ROOT / "modules/game-bridge/scripts/wire_decoder.py") + ":game-bridge-scripts",
    "--add-data", str(ROOT / "modules/game-bridge/scripts/prepare_isolated.py") + ":game-bridge-scripts",
    "--add-data", str(ROOT / "modules/game-bridge/scripts/launch_isolated.py") + ":game-bridge-scripts",
    "--add-data", str(ROOT / "modules/game-bridge/scripts/decode_native_packet.py") + ":game-bridge-scripts",
    "--copy-metadata", "football-assistant", str(ROOT / "scripts" / "desktop_backend.py")]
persona_resources = STAGING / "football_assistant_agent/resources"
if persona_resources.is_dir():
    command.extend(["--add-data", str(persona_resources) + ":football_assistant_agent/resources"])
subprocess.run(command, cwd=ROOT, check=True, env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / "build/pyinstaller-cache")})
# Collect from the build's actual module/binary inventory, not only direct deps.
subprocess.run([sys.executable, str(ROOT / "scripts/collect_backend_licenses.py"),
    "--analysis", str(ROOT / "build/pyinstaller/football-assistant-backend/Analysis-00.toc"),
    "--destination", str(ROOT / "build/desktop-backend/football-assistant-backend/third-party-licenses")],
    cwd=ROOT, check=True)

# Keep LGPL adapter source replaceable, outside the frozen executable.
subprocess.run([sys.executable, str(ROOT / "scripts/package_edge_tts.py"),
    str(ROOT / "build/desktop-backend/football-assistant-backend")], cwd=ROOT, check=True)
