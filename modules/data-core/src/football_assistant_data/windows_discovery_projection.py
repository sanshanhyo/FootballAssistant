"""Pure projection of one manually imported unverified Windows discovery event.

No transport, game calls, storage, prior-event cache, entity lookup or host registration.
Metadata checks reject accidental source mixing; they do not authenticate arbitrary JSON.
"""
from __future__ import annotations
import re
import unicodedata
from uuid import UUID

RULE_ID = "windows-discovery-position-display-v1"
GAME_SHA256 = "820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a"
CONTAINER = "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0"
LABEL_PATH = CONTAINER + "/0"
VALUE_PATH = CONTAINER + "/1/0/0"


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _uuid(value):
    _require(isinstance(value, str) and len(value) == 36, "invalid_source")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError("invalid_source") from None
    _require(parsed.int != 0 and str(parsed) == value, "invalid_source")
    return value


def _hash(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "invalid_source")
    return value


def normalize_display_text(value):
    """Remove ONLY observed U+200B, then trim; never general-format/NFKC folding."""
    _require(isinstance(value, str) and 0 < len(value) <= 128, "invalid_text")
    try:
        units = len(value.encode("utf-16-le", errors="strict")) // 2
    except UnicodeError:
        raise ValueError("invalid_text") from None
    _require(units <= 128, "invalid_text")
    result = value.replace("\u200b", "")
    _require(not any(unicodedata.category(c).startswith("C") for c in result), "invalid_text")
    _require("<" not in result and ">" not in result, "unsupported_markup")
    result = result.strip()
    _require(bool(result), "invalid_text")
    return result


def project_position_display(capture, *, expected_source, operator_context=None):
    """Return a partial display association, or no fields. Never a player fact.

    expected_source must come from the caller's independently retained approved session,
    not be copied from the event being checked. No time is invented: this host event
    has no capture timestamp, so freshness and current-page identity remain unknown.
    operator_context is separately labelled, never used to accept a field or identify it.
    """
    result = {
        "status": "unavailable", "reason": "invalid_capture", "rule_id": RULE_ID,
        "source_kind": "unverified_ui_diagnostic", "partial": True,
        "source_identity_unverified": True, "page_identity_verified": False,
        "business_identity_known": False, "entity_id": None,
        "snapshot_atomic": False, "source_freshness": "unknown", "captured_at": None,
        "fields": {}, "field_provenance": {}, "source": None, "operator_context": None,
    }
    try:
        _require(isinstance(capture, dict) and isinstance(expected_source, dict), "invalid_source")
        for key in ("pid", "entry_tid"):
            _require(type(expected_source.get(key)) is int and expected_source[key] > 0, "invalid_source")
        _uuid(expected_source.get("session_id"))
        for key in ("bridge_sha256", "game_sha256"):
            _hash(expected_source.get(key))
        _require(expected_source["game_sha256"] == GAME_SHA256, "unsupported_build")
        for key in ("pid", "session_id", "bridge_sha256", "game_sha256", "entry_tid"):
            _require(type(capture.get(key)) is type(expected_source[key]) and capture[key] == expected_source[key], "source_mismatch")
        _require(type(capture.get("callback_tid")) is int and capture["callback_tid"] == expected_source["entry_tid"], "source_mismatch")
        nonce = _uuid(capture.get("nonce"))
        _require(capture.get("phase") == "single_shot_raw_discovery_result" and
                 capture.get("page_identity_verified") is False and capture.get("business_facts") is False and
                 capture.get("terminal") is True, "unsupported_capture")
        raw = capture.get("result")
        _require(isinstance(raw, dict) and raw.get("Status") == "raw_diagnostics" and
                 raw.get("Reason") in ("bounded_raw_diagnostics", "approved_prefix_exhausted") and
                 raw.get("PageIdentityVerified") is False and type(raw.get("PanelIndex")) is int and
                 raw["PanelIndex"] == 0 and raw.get("FocusPath") == "0/6", "unsupported_capture")
        request = raw.get("Request")
        _require(isinstance(request, dict) and type(request.get("SchemaVersion")) is int and
                 request["SchemaVersion"] == 3 and request.get("Nonce") == nonce, "event_mismatch")
        _hash(request.get("ApprovalSha256"))
        observations = raw.get("Observations")
        _require(isinstance(observations, list) and 0 < len(observations) <= 8, "invalid_observations")
        paths = {}
        for observation in observations:
            _require(isinstance(observation, dict), "invalid_observations")
            path = observation.get("Path")
            _require(isinstance(path, str) and len(path) <= 127 and
                     re.fullmatch(r"(?:0|[1-9][0-9]{0,2})(?:/(?:0|[1-9][0-9]{0,2})){0,31}", path) and
                     all(int(index) <= 511 for index in path.split("/")) and
                     all(int(index) <= 7 for index in path.split("/")[2:]) and
                     (path == "0/6" or path.startswith("0/6/")), "invalid_path")
            _require(path not in paths, "duplicate_path")
            paths[path] = normalize_display_text(observation.get("Text"))
        _require(LABEL_PATH in paths and VALUE_PATH in paths, "missing_label_or_value")
        _require(paths[LABEL_PATH] == "位置", "label_mismatch")
        value = paths[VALUE_PATH]
        _require(value not in ("位置", "比较"), "invalid_position_display")
        # Never search adjacent nodes, join captures, reuse a prior value or infer identity.
        source = {key: expected_source[key] for key in ("pid", "session_id", "bridge_sha256", "game_sha256", "entry_tid")}
        source.update(nonce=nonce, approval_sha256=request["ApprovalSha256"], panel_index=0, focus_path="0/6")
        if operator_context is not None:
            context = normalize_display_text(operator_context)
            result["operator_context"] = {"kind": "operator_supplied_page_context", "text": context,
                                          "bridge_verified": False, "used_for_identity": False}
        result.update(status="partial_display_state", reason="same_event_labelled_position", source=source)
        result["fields"] = {"displayed_position": value}
        result["field_provenance"] = {"displayed_position": {
            "label": "位置", "panel_index": 0, "container_path": CONTAINER,
            "label_path": LABEL_PATH, "value_path": VALUE_PATH, "nonce": nonce,
            "normalization": "remove_U+200B_then_trim", "association": "fixed_same_container_same_event",
            "semantic_identity_verified": False,
        }}
    except (ValueError, TypeError, KeyError) as error:
        result["reason"] = str(error) if isinstance(error, ValueError) else "invalid_capture"
        result["fields"] = {}; result["field_provenance"] = {}; result["source"] = None
        result["operator_context"] = None
    return result
