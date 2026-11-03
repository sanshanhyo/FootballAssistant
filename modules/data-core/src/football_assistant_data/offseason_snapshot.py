"""One-shot, bounded local bridge for the experimental offseason reader."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from contextlib import suppress

_MAX_BYTES = 256 * 1024
_PRODUCER_GATE = threading.Lock()
_STAGES = frozenset("process module_hash native_profile manager date person team schedule manager_candidates tactic calendar revalidate complete".split())
PRODUCER = {"id": "footballassistant.offseason-reader", "version": "0.1.0", "protocol": "fa-offseason/0.1"}
EXPECTED_BINARY = "bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f"
STATES = {"fm_not_running", "multiple_process", "unsupported_binary", "process_access_denied", "no_session", "no_data", "fresh_partial", "read_failed"}
_LEGACY_REASONS = {"fm_process_not_unique", "process_unavailable", "no_current_data"}


def unavailable(reason: str) -> dict:
    return {"status": "unavailable", "reason": reason, "snapshot": None}


def consent_enabled() -> bool:
    return os.environ.get("FOOTBALL_ASSISTANT_OFFSEASON_CONSENT") == "1"


def valid_range(start: str | None, end: str | None, club_uid: int) -> bool:
    if start is None and end is None:
        return True
    if start is None or end is None or club_uid == 0:
        return False
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        return (first.isoformat() == start and last.isoformat() == end and
                1901 <= first.year <= 2100 and first.year == last.year and
                0 <= (last - first).days < 30)
    except ValueError:
        return False


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def validate_snapshot(data: dict, *, require_current_producer: bool = False, now=None) -> dict:
    """Legacy fixtures remain experimental, never onboarding-verified producers."""
    try:
        if not isinstance(data, dict) or data.get("schema") != "fa-offseason/0.1":
            return unavailable("producer_invalid_output")
        if data.get("synthetic") is True or data.get("status") in {"offline_self_test", "version"}:
            return unavailable("synthetic_producer_output")
        captured = _timestamp(data.get("capturedAt"))
        if not -5 <= ((now or datetime.now(timezone.utc)) - captured).total_seconds() <= 30:
            return unavailable("stale")
        current = data.get("producer") == PRODUCER
        if not current and (require_current_producer or "producer" in data):
            return unavailable("unsupported_producer")
        if current:
            state = data.get("state")
            if data.get("synthetic") is not False or state not in STATES or data.get("reason") != state:
                return unavailable("producer_invalid_output")
            if data.get("status") != ("partial" if state == "fresh_partial" else "unavailable"):
                return unavailable("producer_invalid_output")
            process = data.get("process")
            binary = data.get("binary")
            if process is not None:
                if not isinstance(process, dict) or set(process) != {"pid", "startedAt", "sessionId", "identityKind", "saveIdentity"}:
                    return unavailable("invalid_process_identity")
                pid = process.get("pid")
                started = _timestamp(process.get("startedAt"))
                if type(pid) is not int or not 0 < pid <= 0xffffffff or started > captured or started.year < 2000:
                    return unavailable("invalid_process_identity")
                expected_session = hashlib.sha256(f"{pid}:{process['startedAt']}".encode("utf-8")).hexdigest()
                if process.get("sessionId") != expected_session or process.get("identityKind") != "process_start" or process.get("saveIdentity") != "unknown":
                    return unavailable("invalid_process_identity")
            if binary is not None:
                if not isinstance(binary, dict) or set(binary) != {"module", "sha256", "matched"}:
                    return unavailable("invalid_binary_identity")
                if binary.get("module") != "game_plugin.dll" or not isinstance(binary.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", binary["sha256"]) or type(binary.get("matched")) is not bool:
                    return unavailable("invalid_binary_identity")
                if binary["matched"] != (binary["sha256"] == EXPECTED_BINARY):
                    return unavailable("invalid_binary_identity")
            if state in {"fresh_partial", "no_data"} and (process is None or binary is None or binary["matched"] is not True):
                return unavailable("invalid_producer_identity")
            if state == "unsupported_binary" and (process is None or binary is None or binary["matched"] is not False):
                return unavailable("invalid_producer_identity")
            if state in {"fm_not_running", "multiple_process"} and (process is not None or binary is not None):
                return unavailable("invalid_producer_identity")
            if state == "fresh_partial":
                statuses = {
                    "date": {"experimental"}, "manager": {"available"}, "team": {"experimental_candidates_incomplete"},
                    "schedule": {"experimental_records_unverified"}, "managerCandidates": {"experimental_candidates_incomplete"},
                    "tactic": {"experimental"}, "calendar": {"partial", "experimental_loaded_buckets_only"},
                }
                has_candidate = any(isinstance(data.get(key), dict) and data[key].get("status") in allowed for key, allowed in statuses.items())
                player = data.get("player")
                has_candidate = has_candidate or (isinstance(player, dict) and isinstance(player.get("value"), dict) and player["value"].get("status") == "experimental")
                if not has_candidate:
                    return unavailable("producer_invalid_output")
            diagnostics = {key: data.get(key) for key in ("producer", "process", "binary", "capturedAt", "state")}
            if data["status"] == "unavailable":
                return {**unavailable(state), "producerVerified": True, "diagnostics": diagnostics}
        else:
            if data.get("status") == "unavailable":
                reason = data.get("reason")
                return {**unavailable(reason if reason in STATES | _LEGACY_REASONS else "producer_unavailable"), "producerVerified": False}
            if data.get("status") != "partial":
                return unavailable("producer_invalid_output")
        return {"status": "partial", "reason": "experimental_candidates", "snapshot": data, "producerVerified": current}
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return unavailable("producer_invalid_output")


async def read_offseason(executable: Path, club_uid: int, person_uid: int, start: str | None = None, end: str | None = None, *, require_current_producer: bool = False) -> dict:
    """Run once under explicit consent; no shell, cache, timer or process polling."""
    if not consent_enabled():
        return unavailable("consent_required")
    if not valid_range(start, end, club_uid):
        return unavailable("invalid_range")
    if not executable.is_absolute() or executable.suffix.lower() != ".exe":
        return unavailable("producer_not_configured")
    if not executable.is_file() or executable.is_symlink():
        return unavailable("resource_missing")
    if not _PRODUCER_GATE.acquire(blocking=False):
        return unavailable("producer_busy")
    proc = None
    started = time.monotonic()
    stage = None
    stage_started = started
    stage_timings = {}
    def finish(result):
        now = time.monotonic()
        return {**result, "producer_diagnostics": {
            "schema": "fa-reader-diagnostics/1", "stage": stage,
            "elapsed_ms": round((now - started) * 1000),
            "stage_elapsed_ms": round((now - stage_started) * 1000) if stage else None,
            "stage_timings_ms": {**stage_timings, **({stage: stage_timings.get(stage, 0) + round((now - stage_started) * 1000)} if stage else {})},
            "timeout_seconds": 40 if start is not None else 20,
            "exit_code": proc.returncode if proc is not None else None,
        }}
    try:
        args = [str(executable), str(club_uid), str(person_uid)]
        if start is not None and end is not None:
            args.extend([start, end])
        flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **flags)
        async def collect_stages():
            nonlocal stage, stage_started
            stream = getattr(proc, "stderr", None)
            if stream is None:
                return
            total = 0
            pending = b""
            while True:
                chunk = await stream.read(512)
                if not chunk:
                    return
                total += len(chunk)
                if total > 4096:
                    raise ValueError("oversized diagnostics")
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    try:
                        entry = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if (isinstance(entry, dict) and set(entry) == {"schema", "stage"}
                            and entry["schema"] == "fa-reader-stage/1"
                            and isinstance(entry["stage"], str) and entry["stage"] in _STAGES):
                        tick = time.monotonic()
                        if stage is not None:
                            stage_timings[stage] = stage_timings.get(stage, 0) + round((tick - stage_started) * 1000)
                        stage, stage_started = entry["stage"], tick
        async def collect() -> bytes:
            assert proc.stdout is not None
            diagnostic_task = asyncio.create_task(collect_stages())
            try:
                result = b""
                while True:
                    chunk = await proc.stdout.read(_MAX_BYTES + 1 - len(result))
                    if not chunk:
                        break
                    result += chunk
                    if len(result) > _MAX_BYTES:
                        raise ValueError("oversized")
                await proc.wait()
                await diagnostic_task
                return result
            finally:
                if not diagnostic_task.done():
                    diagnostic_task.cancel()
                with suppress(asyncio.CancelledError):
                    await diagnostic_task
        raw = await asyncio.wait_for(collect(), timeout=40 if start is not None else 20)
        if proc.returncode != 0:
            return finish(unavailable("producer_failed"))
        return finish(validate_snapshot(json.loads(raw), require_current_producer=require_current_producer))
    except asyncio.TimeoutError:
        return finish(unavailable("producer_timeout"))
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        return finish(unavailable("producer_invalid_output"))
    except (OSError, NotImplementedError):
        return finish(unavailable("read_failed"))
    finally:
        try:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
        finally:
            _PRODUCER_GATE.release()


async def onboarding_status(*, verify: bool = False, read=None) -> dict:
    """Configuration inspection is passive. Only explicit verify runs the reader."""
    configured = os.environ.get("FOOTBALL_ASSISTANT_OFFSEASON_EXE")
    consent = consent_enabled()
    executable = Path(configured) if configured else None
    resource_present = bool(executable and executable.is_absolute() and executable.suffix.lower() == ".exe" and executable.is_file() and not executable.is_symlink())
    state = "consent_required" if not consent else "producer_not_configured" if not configured else "resource_missing" if not resource_present else "configured"
    result = {"schema": "fa-reader-onboarding/1", "backendHealthy": True, "configured": bool(configured), "consent": consent,
              "resourcePresent": resource_present, "state": state, "verified": False, "read": None}
    if not verify or state != "configured":
        return result
    envelope = await (read or read_offseason)(executable, 0, 0, require_current_producer=True)
    snapshot = envelope.get("snapshot") or envelope.get("diagnostics") or {}
    result["state"] = snapshot.get("state") or envelope["reason"]
    result["verified"] = envelope.get("producerVerified") is True
    result["read"] = {"status": envelope["status"], "reason": envelope["reason"], "producerVerified": envelope.get("producerVerified", False),
                      **({"producer_diagnostics": envelope["producer_diagnostics"]} if "producer_diagnostics" in envelope else {}),
                      **{key: snapshot.get(key) for key in ("producer", "process", "binary", "capturedAt")}}
    return result
