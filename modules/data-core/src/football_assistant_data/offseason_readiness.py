"""Passive, process-local readiness for existing one-shot native reads.

Only bounded status metadata survives a read. No football values are cached,
no observations are persisted, and status access never launches a producer.
This deliberately does not publish or promote the full business snapshot.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import time

from .offseason_snapshot import EXPECTED_BINARY, STATES, consent_enabled, validate_snapshot, valid_range

# Same pinned native interpretation required by the limited advice projection.
_ASSEMBLY = "820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a"
_METADATA = "a380792f33ba4eb048fa2ffebc6c504b001f85c76e4128e4d41ca24d7b017c4c"
_CAPABILITIES = ("player_info", "transfer_analysis", "tactical_analysis", "schedule_analysis")
_REASONS = STATES | {
    "not_read", "read_in_progress", "stale", "consent_required", "producer_not_configured",
    "resource_missing", "producer_busy", "producer_failed", "producer_timeout",
    "producer_invalid_output", "unsupported_producer", "synthetic_producer_output",
    "invalid_process_identity", "invalid_binary_identity", "invalid_producer_identity",
    "session_changed", "configuration_changed", "backend_shutdown", "invalid_range",
}


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _fresh(value, now):
    parsed = _timestamp(value)
    return parsed is not None and -5 <= (now - parsed).total_seconds() <= 30


def _name(value):
    return (isinstance(value, str) and 0 < len(value) <= 128 and bool(value.strip())
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _uid(value, maximum=0xfffffffe):
    return type(value) is int and 0 < value <= maximum


def _date(value):
    try:
        parsed = date.fromisoformat(value)
        return parsed.isoformat() == value and 1901 <= parsed.year <= 2100
    except (ValueError, TypeError):
        return False


def _fields(snapshot, club_uid, person_uid, start, end, now):
    """Return labels and their expiry only, never names, identifiers or values.

    Capability checks intentionally require the same bounded usable subsets as
    native advice. A date or ambiguous manager candidate is not player_info.
    """
    observed = {}
    captured = _timestamp(snapshot["capturedAt"])
    def add(label, value):
        observed[label] = min(captured, _timestamp(value) or captured) + timedelta(seconds=30)

    world = snapshot.get("date")
    if isinstance(world, dict) and world.get("status") == "experimental" and _fresh(world.get("observedAt"), now) and _date(world.get("date")):
        add("game_date", world["observedAt"])
    profile = snapshot.get("nativeProfile")
    matched = (isinstance(profile, dict) and profile.get("status") == "available" and profile.get("matched") is True
               and all(isinstance(profile.get(key), str) and profile[key].lower() == expected
                       for key, expected in (("gamePluginSha256", EXPECTED_BINARY), ("gameAssemblySha256", _ASSEMBLY), ("metadataSha256", _METADATA))))
    manager = snapshot.get("manager")
    if (matched and isinstance(manager, dict) and manager.get("status") == "available"
            and manager.get("source") == "native_gcUM_selection" and manager.get("proof") == "selected_human_owner"
            and manager.get("selectionScope") == "current_local_human_manager" and manager.get("atomicSnapshot") is False
            and all(_uid(manager.get(key), 0x7fffffff) for key in ("uid", "teamUid", "clubUid"))
            and type(manager.get("contractKind")) is int and 0 <= manager["contractKind"] <= 255
            and _fresh(manager.get("observedAt"), now)):
        add("current_manager", manager["observedAt"])
    managers = snapshot.get("managerCandidates")
    if isinstance(managers, dict) and managers.get("status") == "experimental_candidates_incomplete":
        rows = managers.get("candidates")
        sampled = managers.get("observedAt", snapshot["capturedAt"])
        if (isinstance(rows, list) and len(rows) <= 4 and _fresh(sampled, now)
                and any(isinstance(row, dict) and _uid(row.get("uid")) and _uid(row.get("clubUid"))
                        and _name(row.get("name")) and _name(row.get("clubName")) for row in rows)):
            add("manager_club_candidates", sampled)
    team = snapshot.get("team")
    if (club_uid and isinstance(team, dict) and team.get("status") == "experimental_candidates_incomplete"
            and _fresh(team.get("observedAt"), now)):
        rows = team.get("players")
        if (isinstance(rows, list) and len(rows) <= 256
                and any(isinstance(row, dict) and _uid(row.get("uid")) and type(row.get("clubUid")) is int
                        and row["clubUid"] == club_uid and row.get("linkStatus") == "exact_types" and _name(row.get("name")) for row in rows)):
            add("team_candidates", team["observedAt"])
    wrapper = snapshot.get("player")
    if person_uid and isinstance(wrapper, dict) and _fresh(wrapper.get("observedAt"), now):
        player = wrapper.get("value")
        if isinstance(player, dict) and player.get("status") == "experimental" and type(player.get("uid")) is int and player["uid"] == person_uid:
            affiliation = player.get("affiliation")
            if not club_uid or isinstance(affiliation, dict) and type(affiliation.get("clubUid")) is int and affiliation["clubUid"] == club_uid:
                details = player.get("details")
                usable = _name(player.get("displayName"))
                if isinstance(details, dict):
                    usable = usable or any(type(details.get(key)) is int and 0 <= details[key] <= 255 for key in ("reflexesRaw", "handlingRaw", "anticipationRaw", "jumpingRaw"))
                    usable = usable or type(details.get("heightCm")) is int and 100 <= details["heightCm"] <= 250 or _date(details.get("dateOfBirth"))
                if usable:
                    add("player_candidate", wrapper["observedAt"])
    tactic = snapshot.get("tactic")
    if club_uid and isinstance(tactic, dict) and tactic.get("status") == "experimental" and _fresh(tactic.get("observedAt"), now):
        if (_name(tactic.get("phase")) or any(isinstance(tactic.get(key), list) and 0 < len(tactic[key]) <= 64
                and all(_name(value) for value in tactic[key]) for key in ("positionMasks", "rolesDuties"))):
            add("tactic_candidate", tactic["observedAt"])
    calendar = snapshot.get("calendar")
    if (start is not None and end is not None and valid_range(start, end, club_uid) and isinstance(calendar, dict)
            and calendar.get("status") in {"partial", "experimental_loaded_buckets_only"}
            and _fresh(calendar.get("observedAt"), now)):
        rows = calendar.get("fixtures")
        if (isinstance(rows, list) and 0 < len(rows) <= 128
                and all(type(calendar.get(key)) is int and 0 <= calendar[key] <= maximum for key, maximum in (("unloaded", 128), ("unknown", 4096)))
                and all(isinstance(row, dict) and _date(row.get("date")) and start <= row["date"] <= end
                        and _name(row.get("opponentName")) and (row.get("venue") or "unknown") in {"home", "away", "unknown"} for row in rows)):
            add("calendar_candidates", calendar["observedAt"])
    return observed


def _empty(reason, *, verified=False):
    return {"schema": "fa-offseason-readiness/1", "status": "unavailable", "state": reason if reason in _REASONS else "read_failed",
            "source": "native_offseason_reader", "scope": "partial_native_query", "synthetic": False,
            "production_ready": False, "producer_verified": verified, "freshness": "unavailable",
            "observed_at": None, "expires_at": None, "session_id": None, "observed_fields": [],
            "capabilities": {name: {"ready": False, "partial": True} for name in _CAPABILITIES}}


class OffseasonReadiness:
    def __init__(self, *, clock=None, monotonic=None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._generation = 0
        self._configured = None
        self._deadline = None
        self._value = _empty("not_read")

    def invalidate(self, reason="read_failed"):
        self._generation += 1
        self._configured = self._deadline = None
        self._value = _empty(reason)

    def begin(self):
        self.invalidate("read_in_progress")
        return self._generation

    def complete(self, ticket, envelope, executable, club_uid=0, person_uid=0, start=None, end=None):
        if ticket != self._generation:
            return  # A later failed/unavailable attempt must not revive old data.
        now = self._clock()
        if not isinstance(envelope, dict) or envelope.get("producerVerified") is not True:
            self._value = _empty(envelope.get("reason", "producer_invalid_output") if isinstance(envelope, dict) else "producer_invalid_output")
            return
        if envelope.get("status") != "partial":
            diagnostics = envelope.get("diagnostics")
            checked = validate_snapshot({"schema": "fa-offseason/0.1", "status": "unavailable", "synthetic": False,
                "reason": envelope.get("reason"), **(diagnostics if isinstance(diagnostics, dict) else {})}, require_current_producer=True, now=now)
            self._value = _empty(envelope.get("reason", "read_failed"), verified=checked.get("producerVerified") is True)
            return
        checked = validate_snapshot(envelope.get("snapshot"), require_current_producer=True, now=now)
        if checked.get("status") != "partial" or checked.get("producerVerified") is not True:
            self._value = _empty(checked.get("reason", "producer_invalid_output"))
            return
        snapshot = checked["snapshot"]
        observed = _fields(snapshot, club_uid, person_uid, start, end, now)
        expires = min([_timestamp(snapshot["capturedAt"]) + timedelta(seconds=30), *observed.values()])
        self._configured = str(executable)
        self._deadline = self._monotonic() + max(0, (expires - now).total_seconds())
        self._value = {**_empty("fresh_partial", verified=True), "status": "partial", "freshness": "fresh",
                       "observed_at": snapshot["capturedAt"], "expires_at": expires.isoformat(),
                       "session_id": snapshot["process"]["sessionId"], "observed_fields": list(observed)}
        for name, ready in (("player_info", any(field in observed for field in ("current_manager", "team_candidates", "player_candidate"))),
                            ("tactical_analysis", "tactic_candidate" in observed), ("schedule_analysis", "calendar_candidates" in observed)):
            self._value["capabilities"][name]["ready"] = ready

    def status(self):
        configured = os.environ.get("FOOTBALL_ASSISTANT_OFFSEASON_EXE")
        if not consent_enabled():
            self.invalidate("consent_required")
        elif not configured:
            self.invalidate("producer_not_configured")
        elif self._configured is not None and configured != self._configured:
            self.invalidate("configuration_changed")
        elif self._configured is not None and (not Path(configured).is_file() or Path(configured).is_symlink()):
            self.invalidate("resource_missing")
        elif self._deadline is not None and (self._monotonic() > self._deadline or self._clock() > _timestamp(self._value["expires_at"])):
            self.invalidate("stale")
        return deepcopy(self._value)


def partial_source_status(legacy, readiness):
    if readiness["status"] != "partial" or legacy.get("availability") == "available":
        return legacy
    return {"availability": "partial", "source": "native_offseason_reader", "last_captured_at": readiness["observed_at"],
            "observed_at": readiness["observed_at"], "synthetic": False, "game": None, "facts_count": 0,
            "event_id": None, "connection_state": "connected", "last_seen_at": readiness["observed_at"],
            "selection_reason": "fresh_partial", "data_freshness": "fresh", "partial": True, "production_ready": False}
