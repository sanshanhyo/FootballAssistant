"""One explicitly selected, same-event goalkeeper row display; never a player fact."""
from __future__ import annotations
import re
from .current_page_attributes_projection import CATEGORIES
from .windows_discovery_projection import GAME_SHA256, _require, _uuid, _hash, normalize_display_text

PROJECTION_MODE = "goalkeeper_row0"
RULE_ID = "windows-discovery-goalkeeper-row0-display-v1"
CONTAINER = "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/0/0"
TITLE_PATH = CONTAINER + "/0"
ROW_ROOT = CONTAINER + "/2/0/0/0/0"
LABEL_PATH = ROW_ROOT + "/0/0/0/0/0/0/0/0/0"
VALUE_PATH = ROW_ROOT + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0"
GOALKEEPER_LABELS = frozenset(CATEGORIES["goalkeeper"]["labels"])


def normalize_row_text(value):
    # Reuse length/UTF16/control/markup checks, but do not inherit position trimming.
    result = normalize_display_text(value)
    _require(result == value.replace("\u200b", ""), "noncanonical_attribute_text")
    return result


def project_goalkeeper_row(capture, *, expected_source, operator_context=None):
    result = {
        "status": "unavailable", "reason": "invalid_capture", "rule_id": RULE_ID,
        "projection_mode": PROJECTION_MODE, "source_kind": "unverified_ui_diagnostic", "partial": True,
        "source_identity_unverified": True, "page_identity_verified": False,
        "business_identity_known": False, "entity_id": None, "snapshot_atomic": False,
        "source_freshness": "unknown", "captured_at": None, "fields": {},
        "field_provenance": {}, "source": None, "operator_context": None,
    }
    try:
        _require(isinstance(capture, dict) and isinstance(expected_source, dict), "invalid_source")
        for key in ("pid", "entry_tid"):
            _require(type(expected_source.get(key)) is int and expected_source[key] > 0, "invalid_source")
        _uuid(expected_source.get("session_id"))
        for key in ("bridge_sha256", "game_sha256"):
            _hash(expected_source.get(key))
        _require(expected_source["game_sha256"] == GAME_SHA256, "unsupported_build")
        for key in ("pid", "entry_tid", "session_id", "bridge_sha256", "game_sha256"):
            _require(type(capture.get(key)) is type(expected_source[key]) and capture[key] == expected_source[key], "source_mismatch")
        _require(type(capture.get("callback_tid")) is int and capture["callback_tid"] == expected_source["entry_tid"], "source_mismatch")
        nonce = _uuid(capture.get("nonce"))
        _require(capture.get("phase") == "single_shot_raw_discovery_result" and capture.get("terminal") is True and
                 capture.get("page_identity_verified") is False and capture.get("business_facts") is False, "unsupported_capture")
        raw = capture.get("result")
        _require(isinstance(raw, dict) and raw.get("Status") == "raw_diagnostics" and
                 raw.get("Reason") == "approved_row_targets_complete" and raw.get("PageIdentityVerified") is False and
                 type(raw.get("PanelIndex")) is int and raw["PanelIndex"] == 0 and raw.get("FocusPath") == CONTAINER, "unsupported_capture")
        request = raw.get("Request")
        _require(isinstance(request, dict) and type(request.get("SchemaVersion")) is int and
                 request["SchemaVersion"] == 3 and request.get("Nonce") == nonce, "event_mismatch")
        _hash(request.get("ApprovalSha256"))
        observations = raw.get("Observations")
        _require(isinstance(observations, list) and len(observations) == 3, "invalid_observations")
        paths = {}
        for observation in observations:
            _require(isinstance(observation, dict), "invalid_observations")
            path = observation.get("Path")
            _require(isinstance(path, str) and path in (TITLE_PATH, LABEL_PATH, VALUE_PATH), "invalid_path")
            _require(path not in paths, "duplicate_path")
            paths[path] = normalize_row_text(observation.get("Text"))
        _require(set(paths) == {TITLE_PATH, LABEL_PATH, VALUE_PATH}, "missing_row_component")
        _require(paths[TITLE_PATH] == "守门", "category_mismatch")
        _require(paths[LABEL_PATH] in GOALKEEPER_LABELS, "unsupported_attribute_label")
        value_display = paths[VALUE_PATH]
        _require(re.fullmatch(r"(?:[1-9]|1[0-9]|20)", value_display) is not None, "invalid_attribute_value")
        source = {key: expected_source[key] for key in ("pid", "entry_tid", "session_id", "bridge_sha256", "game_sha256")}
        source.update(nonce=nonce, approval_sha256=request["ApprovalSha256"], panel_index=0, focus_path=CONTAINER)
        if operator_context is not None:
            result["operator_context"] = {"kind": "operator_supplied_page_context", "text": normalize_display_text(operator_context),
                                          "bridge_verified": False, "used_for_identity": False}
        result.update(status="partial_display_state", reason="same_event_labelled_goalkeeper_row", source=source)
        result["fields"] = {"displayed_attribute": {"category_display": paths[TITLE_PATH], "label_display": paths[LABEL_PATH],
                           "value_display": value_display, "value": int(value_display), "row_index": 0}}
        result["field_provenance"] = {"displayed_attribute": {
            "category_title_path": TITLE_PATH, "label_path": LABEL_PATH, "value_path": VALUE_PATH,
            "row_root": ROW_ROOT, "container_path": CONTAINER, "association": "fixed_same_row_same_event",
            "semantic_identity_verified": False, "panel_index": 0, "nonce": nonce,
            "normalization": "remove_U+200B_only",
        }}
    except (ValueError, TypeError, KeyError) as error:
        result["reason"] = str(error) if isinstance(error, ValueError) else "invalid_capture"
        result["fields"] = {}; result["field_provenance"] = {}; result["source"] = None
        result["operator_context"] = None
    return result
