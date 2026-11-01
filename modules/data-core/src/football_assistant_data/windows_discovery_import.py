"""Manual single-event display import; never writes observation/business stores."""
from __future__ import annotations
import json
from .windows_discovery_projection import project_position_display

MAX_IMPORT_BYTES = 32768
IMPORT_ROUTE = "/v1/reader/windows-discovery/import"


def empty_snapshot():
    return {"status": "unavailable", "import_mode": "manual_single_event", "imported_at": None,
            "projection": None}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def parse_import(raw: bytes, imported_at: str):
    if not 0 < len(raw) <= MAX_IMPORT_BYTES:
        raise ValueError("invalid_import_size")
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json_number")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("invalid_json") from None
    if not isinstance(payload, dict) or set(payload) not in (
            {"capture", "expected_source"}, {"capture", "expected_source", "operator_context"}):
        raise ValueError("invalid_import_fields")
    source = payload["expected_source"]
    if not isinstance(source, dict) or set(source) != {"pid", "entry_tid", "session_id", "bridge_sha256", "game_sha256"}:
        raise ValueError("invalid_source")
    if "operator_context" in payload and not isinstance(payload["operator_context"], str):
        raise ValueError("invalid_operator_context")
    projection = project_position_display(payload["capture"], expected_source=source,
                                         operator_context=payload.get("operator_context"))
    if projection["status"] != "partial_display_state":
        raise ValueError(projection["reason"])
    return {"status": "manual_import_snapshot", "import_mode": "manual_single_event",
            "imported_at": imported_at, "projection": projection}
