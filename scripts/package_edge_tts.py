"""Package LGPL adapter as replaceable Python source, not frozen application code."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = "7.3.1"


def package(destination):
    distribution = metadata.distribution("edge-tts")
    if distribution.version != VERSION:
        raise RuntimeError(f"Expected edge-tts {VERSION}; install the speech extra")
    target = Path(destination) / "edge-tts-source"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for record in distribution.files or []:
        if record.parts[0] == "edge_tts" and record.suffix == ".py":
            output = target / str(record)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(distribution.locate_file(record), output)
    if not (target / "edge_tts/util.py").is_file():
        raise RuntimeError("Edge TTS source missing")
    for name in ["LICENSE", "gpl-3.0.txt"]:
        shutil.copy2(ROOT / "apps/companion/packaging/edge-tts-notices" / name, target / name)
    (target / "REPLACEMENT.txt").write_text(
        "edge-tts 7.3.1, LGPLv3 (srt_composer.py: MIT).\n"
        "Source: https://github.com/rany2/edge-tts/tree/360fa8e1de354e1dda74c09bd695887d6a44df74\n"
        "The edge_tts directory is the unmodified Python source used at runtime.\n"
        "You may replace it with an API-compatible modified version; no application rebuild is needed.\n"
        "Keep dependencies compatible with the bundled runtime. On macOS changing app contents\n"
        "invalidates signing: use a development copy and re-sign it using the supplied build scripts.\n"
        "No service uptime, free-use or continuing compatibility guarantee is provided.\n", encoding="utf-8")
    files = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob("*")) if p.is_file()}
    (target / "manifest.json").write_text(json.dumps({"version": VERSION, "files": files}, indent=2), encoding="utf-8")
    return target


if __name__ == "__main__":
    package(sys.argv[1])
