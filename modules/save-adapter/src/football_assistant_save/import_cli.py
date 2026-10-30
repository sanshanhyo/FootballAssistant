"""Explicit user command: stable read-only copy -> narrow adapter -> local ingestion.

No watcher, game write, process attachment, or model call is involved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from dotenv import load_dotenv
from football_assistant_contracts.validation import validate_observation
from .summary import read_summary_snapshot

ROOT = Path(__file__).resolve().parents[4]


class ImportSaveError(ValueError):
    pass


def _signature(path: Path) -> tuple:
    info = path.stat()
    return info.st_ino, info.st_size, info.st_mtime_ns


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_stable_save(source: Path, destination_dir: Path, *, settle_seconds: float = 1.0) -> tuple[Path,str]:
    source = Path(source).expanduser()
    if source.is_symlink() or not source.is_file():
        raise ImportSaveError("Source must be a regular save file, not a symbolic link.")
    before = _signature(source)
    time.sleep(settle_seconds)
    if before != _signature(source):
        raise ImportSaveError("Save is still changing; wait until the game finishes saving.")
    destination_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name != "nt":destination_dir.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = destination_dir/f"{stamp}-{uuid4().hex[:8]}-save-copy.fm"
    created = False
    try:
        with source.open("rb") as incoming,destination.open("xb") as outgoing:
            created = True
            if os.name != "nt":destination.chmod(0o600)
            while chunk := incoming.read(1024*1024):
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        copied_sha = _sha256(destination)
        source_sha = _sha256(source)
        if before != _signature(source) or copied_sha != source_sha:
            raise ImportSaveError("Save changed while copying; this attempt was discarded.")
        return destination,copied_sha
    except BaseException:
        if created:destination.unlink(missing_ok=True)
        raise


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def publish_observation(observation: dict, runtime_file: Path, port: int) -> dict:
    validate_observation(observation)
    if runtime_file.stat().st_size > 16_384:
        raise ImportSaveError("Local runtime configuration is invalid.")
    runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
    base_url = f"http://127.0.0.1:{port}"
    if runtime.get("base_url") != base_url or not isinstance(runtime.get("token"),str):
        raise ImportSaveError("Local runtime address or access token is invalid.")
    request = Request(base_url+"/v1/observations",data=json.dumps(observation,ensure_ascii=False,allow_nan=False).encode(),headers={"Authorization":"Bearer "+runtime["token"],"Content-Type":"application/json"},method="POST")
    # A local token must not be sent through HTTP_PROXY or followed to another host.
    opener = build_opener(ProxyHandler({}),_NoRedirect())
    with opener.open(request,timeout=10) as response:
        return json.loads(response.read(32_768))


def import_save(source: Path, data_dir: Path, runtime_file: Path, port: int, *, settle_seconds: float = 1.0) -> dict:
    destination,digest = copy_stable_save(source,data_dir/"save-snapshots",settle_seconds=settle_seconds)
    parsed = read_summary_snapshot(destination,confirmed_copy=True)
    if parsed["observation"] is None:
        return {"imported":False,"status":parsed["status"],"snapshot_ref":destination.name,"sha256":digest,"warning":parsed["warning"]}
    observation = parsed["observation"]
    imported = publish_observation(observation,runtime_file,port)
    report = {"imported":True,"status":parsed["status"],"snapshot_ref":destination.name,"sha256":digest,"event_id":observation["event_id"],"source_status":imported["source_status"],"fields":[{"field":fact["field"],"value":fact["value"],"validation_method":fact["provenance"]["validation_method"]} for fact in observation["payload"]["facts"]]}
    report_path = destination.with_suffix(".import.json")
    with report_path.open("x",encoding="utf-8") as stream:
        json.dump({"report":report,"observation":observation},stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    if os.name!="nt":report_path.chmod(0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description="Copy a stable save read-only, parse two experimental metadata fields, and import locally")
    parser.add_argument("source",type=Path,help="A saved .fm file; the source is never modified")
    args = parser.parse_args()
    load_dotenv(ROOT/".env",override=False)
    data_dir = Path(os.environ.get("FOOTBALL_ASSISTANT_DATA_DIR",ROOT/"local-data")).expanduser().resolve()
    runtime_file = Path(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_FILE",data_dir/"runtime.json")).expanduser().resolve()
    try:
        port = int(os.environ.get("FOOTBALL_ASSISTANT_PORT","17827"))
        if not 1<=port<=65535:raise ImportSaveError("Configured port is invalid.")
        report = import_save(args.source,data_dir,runtime_file,port)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        raise SystemExit(0 if report["imported"] else 2)
    except (OSError,ValueError,KeyError,HTTPError,URLError):
        print("Save import failed. Check that saving has finished, the file format is supported, and the local backend is running.")
        raise SystemExit(1) from None
