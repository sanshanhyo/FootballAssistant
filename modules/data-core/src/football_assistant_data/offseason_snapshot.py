"""One-shot, bounded local bridge for the experimental offseason reader."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

_MAX_BYTES = 256 * 1024


def unavailable(reason: str) -> dict:
    return {"status": "unavailable", "reason": reason, "snapshot": None}


async def read_offseason(executable: Path, club_uid: int, person_uid: int) -> dict:
    """Run a configured local producer once; never use a shell or cache its output."""
    if not executable.is_absolute() or not executable.is_file() or executable.suffix.lower() != ".exe":
        return unavailable("producer_not_configured")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            str(executable), str(club_uid), str(person_uid),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        async def collect() -> bytes:
            assert proc.stdout is not None
            result = await proc.stdout.read(_MAX_BYTES + 1)
            if len(result) > _MAX_BYTES:
                raise ValueError("oversized")
            # A single read may return before EOF; consume remaining bounded data.
            while True:
                chunk = await proc.stdout.read(_MAX_BYTES + 1 - len(result))
                if not chunk:
                    break
                result += chunk
                if len(result) > _MAX_BYTES:
                    raise ValueError("oversized")
            await proc.wait()
            return result
        raw = await asyncio.wait_for(collect(), timeout=20)
        if proc.returncode != 0:
            return unavailable("producer_failed")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") != "fa-offseason/0.1":
            raise ValueError("invalid schema")
        if data.get("status") == "unavailable":
            return unavailable("producer_unavailable")
        if data.get("status") != "partial":
            raise ValueError("invalid status")
        captured = datetime.fromisoformat(data["capturedAt"].replace("Z", "+00:00"))
        if captured.utcoffset() is None or not -5 <= (datetime.now(timezone.utc) - captured).total_seconds() <= 30:
            return unavailable("stale")
        return {"status": "partial", "reason": "experimental_candidates", "snapshot": data}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, AttributeError, NotImplementedError, asyncio.TimeoutError):
        return unavailable("producer_invalid_or_unavailable")
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
