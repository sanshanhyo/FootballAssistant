"""Experimental FM27 summary31 metadata reader, with explicit initial-sample UI evidence.

Uses the MIT fmsave 0.7.0 container reader, not its FM26 Save/layout readers.
No absolute string offsets, player records, club objects, or time-slot semantics.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import struct
from uuid import uuid4

EXPECTED_SCHEMA = 31
VALIDATED_BUILDS = frozenset({"27.0.0+2486695"})
VALIDATED_SAMPLES = {
    "dd9a389b354ec91c3d4b25dc512ef236fbd3158ac41b717f72c6a758f3fdccc7": "fm27-ui-crosscheck-2026-10-30",
}
MAX_SUMMARY_BYTES = 1_048_576
MAX_SUMMARY_COMPRESSED_BYTES = 2_097_152


class UnsupportedSummary(ValueError):
    pass


def parse_summary31(data: bytes) -> dict:
    """Walk the narrowly verified grammar; never scan for expected labels/dates."""
    if not 8 <= len(data) <= MAX_SUMMARY_BYTES:
        raise UnsupportedSummary("Summary size is outside supported bounds")
    if data[:6] != b"\x03\x01tad.":
        raise UnsupportedSummary("Unsupported summary section signature")
    schema = struct.unpack_from("<H",data,6)[0]
    if schema != EXPECTED_SCHEMA:
        raise UnsupportedSummary("Unsupported summary schema")
    cursor = 8

    def take(count: int) -> bytes:
        nonlocal cursor
        if count < 0 or count > len(data)-cursor:
            raise UnsupportedSummary("Truncated summary grammar node")
        result = data[cursor:cursor+count]
        cursor += count
        return result

    def uint32() -> int:
        return struct.unpack("<I",take(4))[0]

    def utf8(maximum: int, *, nonempty: bool = False) -> str:
        size = uint32()
        if size > maximum or (nonempty and size == 0):
            raise UnsupportedSummary("Summary string length outside supported bounds")
        try:
            value = take(size).decode("utf-8",errors="strict")
        except UnicodeError:
            raise UnsupportedSummary("Summary string is not strict UTF-8") from None
        if any(ord(character)<32 or ord(character)==127 for character in value):
            raise UnsupportedSummary("Summary string contains control characters")
        return value

    utf8(65_536)  # Opaque setup string; not interpreted or exposed.
    build = utf8(128,nonempty=True)
    if not re.fullmatch(r"27\.\d+\.\d+\+\d+",build) or build not in VALIDATED_BUILDS:
        raise UnsupportedSummary("FM27 build has no verified summary profile")
    divisions = uint32()
    if divisions > 4096 or divisions > (len(data)-cursor)//4:
        raise UnsupportedSummary("Division-string count outside supported bounds")
    for _ in range(divisions):
        utf8(1024)
    take(8)  # Opaque manager prefix: fixed-width grammar node, no inferred identity.
    utf8(1024)  # Private manager label, never emitted.
    club_label = utf8(1024,nonempty=True)
    take(4)  # Opaque reference: deliberately not emitted as a club ID.
    packed, year = struct.unpack("<HH",take(4))
    day = packed & 0x1FF
    if not 1901 <= year <= 2200 or not 1 <= day <= (366 if calendar.isleap(year) else 365):
        raise UnsupportedSummary("Summary date outside valid calendar bounds")
    game_date = (date(year,1,1)+timedelta(days=day-1)).isoformat()
    # packed >> 9 is intentionally not mapped to a time of day.
    return {"build":build,"summary_schema":schema,"club_label":club_label,"game_date":game_date,"unparsed_tail_bytes":len(data)-cursor}


def read_summary_snapshot(snapshot_path: Path, *, confirmed_copy: bool = False) -> dict:
    """Read the checked build/grammar; distinguish new copies from the UI sample."""
    snapshot_path = Path(snapshot_path)
    if not confirmed_copy:
        return {"status":"error","observation":None,"warning":"An explicitly confirmed stable copy is required."}
    if not snapshot_path.is_file():
        return {"status":"missing","observation":None,"warning":"Save copy does not exist."}
    if snapshot_path.is_symlink():
        return {"status":"error","observation":None,"warning":"A regular copy is required."}
    try:
        if importlib.metadata.version("fmsave") != "0.7.0":
            raise UnsupportedSummary("This profile requires audited fmsave 0.7.0 container APIs")
        from fmsave._container import read_index, read_section
        before = snapshot_path.stat()
        digest = hashlib.sha256()
        with snapshot_path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        index = read_index(snapshot_path)
        entry = index.sections.get("save_game_summary")
        if entry is None or entry.extension != ".dat" or not 8 <= entry.decompressed_size <= MAX_SUMMARY_BYTES:
            raise UnsupportedSummary("Unsupported or missing bounded summary section")
        if not 1 <= entry.compressed_size <= MAX_SUMMARY_COMPRESSED_BYTES:
            raise UnsupportedSummary("Compressed summary size is outside supported bounds")
        data = read_section(index,"save_game_summary")
        if len(data) != entry.decompressed_size:
            raise UnsupportedSummary("Summary length differs from the container directory")
        summary = parse_summary31(data)
        after = snapshot_path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise UnsupportedSummary("Snapshot changed during parsing")
        now = datetime.now(timezone.utc).isoformat()
        adapter_id = "fm27-summary-metadata-experimental"
        initial_sample_sha, evidence = next(iter(VALIDATED_SAMPLES.items()))
        exact_ui_sample = sha256 in VALIDATED_SAMPLES
        verification = "ui_crosscheck_exact_snapshot" if exact_ui_sample else "format_checked_initial_sample_ui_crosschecked"
        common = {"source":"save","adapter_id":adapter_id,"experimental":True,"validation_method":verification,"evidence_ref":evidence,"snapshot_sha256":sha256,"ui_evidence_sample_sha256":initial_sample_sha}
        facts = [
            {"entity_kind":"save_summary","entity_id":None,"field":"club_label","value":summary["club_label"],"provenance":{**common,"scope":"raw_summary_label"}},
            {"entity_kind":"save_summary","entity_id":None,"field":"game_date","value":summary["game_date"],"provenance":{**common,"scope":"summary_calendar_date"}},
        ]
        host = (platform.system(),platform.machine().lower())
        platform_tag = {("Darwin","arm64"):"macos-arm64",("Darwin","x86_64"):"macos-x64",("Windows","amd64"):"windows-x64",("Windows","x86_64"):"windows-x64"}.get(host,"unknown")
        observation = {
            "schema_version":"0.3.0","event_id":str(uuid4()),"captured_at":now,"observed_at":now,"synthetic":False,
            "source":{"kind":"save","adapter_id":adapter_id,"adapter_version":"0.1.0","platform":platform_tag,"freshness":"snapshot","save_metadata":{"snapshot_ref":snapshot_path.name,"sha256":sha256,"file_modified_at":datetime.fromtimestamp(after.st_mtime,timezone.utc).isoformat(),"parse_profile":"fm27-summary31-build27.0.0+2486695-experimental"}},
            "game":{"product":"FM27","build":summary["build"],"session_id":None,"game_time":summary["game_date"]},
            "status":"partial","payload":{"kind":"fact_snapshot","facts":facts},
        }
        return {"status":"experimental_partial","observation":observation,"warning":"Only two experimental summary metadata fields. UI cross-check applies to the recorded initial sample; a new snapshot is format-checked only. No club entity, player roster or real-time source support."}
    except (UnsupportedSummary,importlib.metadata.PackageNotFoundError) as error:
        return {"status":"unsupported","observation":None,"warning":str(error)}
    except Exception:
        return {"status":"error","observation":None,"warning":"Save container could not be read safely; no facts emitted."}


def main():
    parser = argparse.ArgumentParser(description="Experimental two-field FM27 summary metadata from a confirmed stable copy")
    parser.add_argument("snapshot",type=Path)
    parser.add_argument("--confirmed-copy",action="store_true",required=True)
    parser.add_argument("--output",type=Path,help="Write a validated observation envelope for explicit Data Core import")
    args = parser.parse_args()
    result = read_summary_snapshot(args.snapshot,confirmed_copy=args.confirmed_copy)
    if args.output and result["observation"] is not None:
        from football_assistant_contracts.validation import validate_observation
        validate_observation(result["observation"])
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x",encoding="utf-8") as stream:
            json.dump(result["observation"],stream,ensure_ascii=False,indent=2)
            stream.write("\n")
        if __import__("os").name!="nt":args.output.chmod(0o600)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["observation"] is not None else 2)
