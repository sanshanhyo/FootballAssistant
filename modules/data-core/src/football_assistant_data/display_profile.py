"""Fail-closed, version-pinned projection of observed UI text, not entity facts.

No disk, network, model, identity lookup, or previous-player cache is involved.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import unicodedata

ADAPTER_ID = "footballassistant.runtime-ui-tree"
ADAPTER_VERSION = "0.4.0"
GAME_BUILD = "27.0.0+2486695"
MAX_FACTS = 80
MAX_AGE_SECONDS = 15
RULE_ID = "fm27-27.0.0+2486695-ui-tree-0.4.0-zh-overview-v2"
SELECTORS = {
    "name": "panel0/0/3/0/0/0/0/2/0/1/0/0/0/2/0",
    "overview_tab": "panel0/0/3/0/0/0/0/2/0/1/1/0/0/1/0/0/0/0/0/0/0/0/0",
    "contract_tab": "panel0/0/3/0/0/0/0/2/0/1/1/0/0/1/0/0/0/2/0/0/0/0/0/1/0/0",
    "transfer_tab": "panel0/0/3/0/0/0/0/2/0/1/1/0/0/1/0/0/0/3/0/0/0/0/0/1/0/0",
    "growth_tab": "panel0/0/3/0/0/0/0/2/0/1/1/0/0/1/0/0/0/4/0/0/0/0/0/1/0/0",
    "position_label": "panel0/0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0",
    "position": "panel0/0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/1/0/0",
    "position_repeat": "panel0/0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/0/0/0/2/0/0",
    "info_label": "panel0/0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/4/0/0",
    "height_label": "panel0/0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/4/2/0/0",
    "height": "panel0/0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/4/2/0/1",
}
CONTRACT_SLOT_PREFIX = "panel0/0/3/0/0/0/0/2/0/1/1/0/0/1/0/0/0/2/"
ANCHORS = {"overview_tab":"概览", "contract_tab":"合同", "transfer_tab":"转会", "growth_tab":"成长",
           "position_label":"位置", "info_label":"资料", "height_label":"身高"}
LIMITATIONS = [
    "Experimental display text only; UI paths are not native player IDs and business identity is unknown.",
    "Pinned to one FM27 build, adapter version and Chinese overview layout; other layouts fail closed.",
    "The runtime traversal is bounded (80 text values, 15 ms plus node/depth limits); a complete response is not a complete UI tree.",
    "Hidden or cached elements may exist. Visibility, occlusion and active page are not independently verified at runtime; no screenshot verification is performed.",
    "No current-club inference, technical attributes, native records or cross-player identity mapping are provided.",
]


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _time(value):
    _require(isinstance(value, str) and len(value) <= 64, "invalid_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid_timestamp") from None
    _require(result.tzinfo is not None and result.utcoffset() is not None, "invalid_timestamp")
    return result


def _identifier(value):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:+-]{1,128}", value), "invalid_metadata")
    return value


def _plain(value):
    _require(isinstance(value, str) and 0 < len(value) <= 1024, "invalid_text")
    stack, pieces = [], []
    for part in re.split(r"(<[^<>]*>)", value):
        if part.startswith("<"):
            close = re.fullmatch(r"</(link|style|color)>", part)
            if close:
                _require(bool(stack) and stack.pop() == close[1], "unsupported_markup")
            else:
                tag = re.fullmatch(r'<(link)="[0-9]{1,8}">|<(style)="Norml">|<(color)=(?:"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?"|#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?)>', part)
                _require(tag is not None and len(stack) < 8, "unsupported_markup")
                stack.append(next(group for group in tag.groups() if group))
        else:
            _require("<" not in part and ">" not in part, "unsupported_markup")
            pieces.append(part)
    _require(not stack, "unsupported_markup")
    result = "".join(pieces).replace("\u200b", "").strip()
    _require(0 < len(result) <= 128 and not any(unicodedata.category(c).startswith("C") for c in result), "invalid_text")
    return result


def project_display_profile(snapshot, *, now=None, max_age_seconds=MAX_AGE_SECONDS):
    """Project a complete bounded reader snapshot; any failed check clears all fields.

    ``now`` is an aware datetime for deterministic tests. Freshness may be tightened,
    but never extended beyond 15 seconds. Legacy per-fact metadata is mandatory.
    """
    result = {"status":"unavailable", "reason":"invalid_snapshot", "source_kind":"ui", "partial":True,
              "entity_id":None, "business_identity_known":False, "rule_id":RULE_ID,
              "fields":{}, "field_provenance":{}, "evidence":[], "limitations":list(LIMITATIONS)}
    try:
        _require(isinstance(snapshot, dict), "invalid_snapshot")
        now = datetime.now(timezone.utc) if now is None else now
        _require(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None, "invalid_timestamp")
        _require(isinstance(max_age_seconds, (int, float)) and not isinstance(max_age_seconds, bool)
                 and math.isfinite(max_age_seconds) and 0 < max_age_seconds <= MAX_AGE_SECONDS, "invalid_freshness_bound")
        status = snapshot.get("source_status")
        _require(isinstance(status, dict), "invalid_metadata")
        _require(all(status.get(k) == v for k, v in {
            "availability":"available", "source":"runtime", "connection_state":"connected",
            "data_freshness":"fresh", "source_freshness":"live", "adapter_id":ADAPTER_ID}.items())
                 and status.get("synthetic") is False, "source_unavailable")
        event = _identifier(status.get("event_id"))
        _require(snapshot.get("snapshot_event_id") == event, "event_mismatch")
        later = snapshot.get("later_source_status")
        if later is not None:
            _require(isinstance(later, dict) and all(later.get(k) == status.get(k) for k in
                     ("event_id", "source", "adapter_id", "game", "last_captured_at", "observed_at",
                      "availability", "connection_state", "data_freshness", "synthetic", "source_freshness")), "event_mismatch")
        game = status.get("game")
        _require(isinstance(game, dict) and game.get("product") == "FM27" and game.get("build") == GAME_BUILD, "unsupported_build")
        session = _identifier(game.get("session_id"))
        capture = _time(status.get("last_captured_at"))
        observed = _time(status.get("observed_at"))
        for timestamp in (capture, observed, _time(status.get("last_seen_at"))):
            _require(0 <= (now - timestamp).total_seconds() <= max_age_seconds, "stale_observation")
        _require(observed <= capture, "invalid_timestamp")
        facts = snapshot.get("facts")
        _require(isinstance(facts, list) and 0 < len(facts) <= MAX_FACTS
                 and snapshot.get("facts_total") == len(facts) and snapshot.get("has_more") is False,
                 "incomplete_snapshot")
        _require(status.get("facts_count") == len(facts), "incomplete_snapshot")
        envelope = snapshot.get("observation")
        if envelope is not None:
            _require(isinstance(envelope, dict) and envelope.get("status") in ("available", "partial")
                     and envelope.get("synthetic") is False, "source_unavailable")
            _require(envelope.get("event_id") == event and _time(envelope.get("captured_at")) == capture
                     and _time(envelope.get("observed_at")) == observed, "event_mismatch")
        else:
            _require(snapshot.get("reader_api") == "legacy", "invalid_metadata")
        paths = {}
        for fact in facts:
            _require(isinstance(fact, dict), "invalid_fact")
            path = fact.get("entity_id")
            _require(isinstance(path, str) and len(path) <= 512, "invalid_path")
            _require(path not in paths, "duplicate_path")
            paths[path] = fact
        resolved = dict(SELECTORS)
        # A conditional tab wrapper changes the contract leaf, not its header slot.
        # Resolve only one normalized anchor within that fixed, bounded slot.
        contract_paths = []
        for path, fact in paths.items():
            if path.startswith(CONTRACT_SLOT_PREFIX):
                suffix = path[len(CONTRACT_SLOT_PREFIX):].split("/")
                _require(1 <= len(suffix) <= 8 and all(re.fullmatch(r"[0-9]{1,3}", part) for part in suffix), "unsupported_layout")
                if _plain(fact.get("value")) == ANCHORS["contract_tab"]:
                    contract_paths.append(path)
        _require(len(contract_paths) == 1, "ambiguous_contract_anchor" if contract_paths else "missing_selector")
        resolved["contract_tab"] = contract_paths[0]
        selected = {}
        for key, path in resolved.items():
            _require(path in paths, "missing_selector")
            fact = paths[path]
            _require(fact.get("entity_kind") == "ui_element" and fact.get("field") == "ui_tree_text", "invalid_fact")
            _require("readability" not in fact or fact["readability"] == "value_observed", "invalid_fact")
            if envelope is None:
                _require(fact.get("readability") == "value_observed", "invalid_fact")
                _require(fact.get("source_event_id") == event and _time(fact.get("captured_at")) == capture, "event_mismatch")
            metadata = envelope if envelope is not None else fact
            source, fact_game = metadata.get("source"), metadata.get("game")
            _require(isinstance(source, dict) and all(source.get(k) == v for k, v in {
                "kind":"runtime", "freshness":"live", "adapter_id":ADAPTER_ID, "adapter_version":ADAPTER_VERSION, "platform":"macos-arm64"}.items()), "unsupported_adapter")
            _require(isinstance(fact_game, dict) and all(fact_game.get(k) == game.get(k)
                     for k in ("product", "build", "session_id")), "session_mismatch")
            # If enriched facts accompany a modern envelope, they must not disagree.
            if envelope is not None:
                for k, expected in (("source", source), ("game", fact_game), ("source_event_id", event)):
                    _require(k not in fact or fact[k] == expected, "event_mismatch")
                _require("captured_at" not in fact or _time(fact["captured_at"]) == capture, "event_mismatch")
            selected[key] = _plain(fact.get("value"))
        _require(all(selected[k] == v for k, v in ANCHORS.items()), "unsupported_layout")
        # The secondary role can legitimately differ from the labelled full position.
        # It is a structural marker only, never corroboration or another output field.
        height = re.fullmatch(r"([0-9]{3})厘米", selected["height"])
        _require(height is not None and 100 <= int(height[1]) <= 250, "invalid_height")
        fields = {"name_display":selected["name"], "position_display":selected["position"], "height_cm_display":int(height[1])}
        provenance = {"source_kind":"ui", "source_event_id":event, "session_id":session,
                      "captured_at":capture.isoformat(), "observed_at":observed.isoformat(),
                      "adapter_id":ADAPTER_ID, "adapter_version":ADAPTER_VERSION, "game_build":GAME_BUILD}
        dependencies = {"name_display":["name"], "position_display":["position", "position_label"],
                        "height_cm_display":["height", "height_label", "info_label"]}
        result.update(status="experimental_observed_display_profile", reason="matched_pinned_layout", fields=fields,
                      field_provenance={key:{**provenance, "ui_paths":[resolved[name] for name in names]} for key,names in dependencies.items()},
                      evidence=[{"selector":key, "ui_path":resolved[key], "text":value} for key,value in selected.items()])
    except (ValueError, TypeError, OverflowError) as error:
        # Only our fixed reason codes are exposed, never arbitrary input/exception text.
        reason = str(error)
        result["reason"] = reason if re.fullmatch(r"[a-z_]{1,40}", reason) else "invalid_snapshot"
    return result
