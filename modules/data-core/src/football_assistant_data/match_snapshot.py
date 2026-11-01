"""Read the FA match-reader's local file; this is not a verified producer yet."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


def read_match_snapshot(path: Path, *, now: datetime | None = None, max_age: float = 15) -> dict:
    """Return unavailable for missing, malformed, stale, or non-live data."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("oversized")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema_version") != "fa-match-snapshot/0.1":
            raise ValueError("invalid schema")
        if data.get("source") != "native_match_hook" or data.get("synthetic") is not False:
            raise ValueError("invalid source")
        if data.get("status") != "live":
            return {"status": "unavailable", "reason": "no_live_match", "snapshot": None}
        timestamp = datetime.fromisoformat(data["captured_at"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError("missing timezone")
        age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
        if age < -5 or age > max_age:
            return {"status": "unavailable", "reason": "stale", "snapshot": None}
        return {"status": "experimental", "reason": "native_producer_not_verified", "snapshot": data}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        return {"status": "unavailable", "reason": "invalid_or_missing_snapshot", "snapshot": None}
