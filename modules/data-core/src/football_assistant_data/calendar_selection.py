"""Select an explicit candidate or a freshly verified local manager's club."""
from datetime import date, datetime, timedelta, timezone
import re

from football_assistant_agent.offseason_advice import prepare_offseason_advice


def _candidate_context(snapshot, now):
    """Keep the older candidate-only route bounded and explicitly unconfirmed."""
    try:
        source = snapshot["managerCandidates"]
        if source.get("status") != "experimental_candidates_incomplete" or source.get("unknown") != 0:
            return None
        candidates = source["candidates"]
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 16:
            return None
        for value in (source.get("observedAt") or snapshot["capturedAt"], snapshot["date"]["observedAt"]):
            sampled = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if sampled.utcoffset() is None or not -5 <= (now - sampled).total_seconds() <= 30:
                return None
        world = snapshot["date"]
        if world.get("status") != "experimental":
            return None
        day = date.fromisoformat(world["date"])
        if day.isoformat() != world["date"] or not 1901 <= day.year <= 2100:
            return None
        for item in candidates:
            uid, name, manager_uid = item["clubUid"], item["clubName"], item["uid"]
            if (type(uid) is not int or not 0 < uid < 4294967295
                    or type(manager_uid) is not int or not 0 < manager_uid < 4294967295
                    or not isinstance(name, str) or not 2 <= len(name) <= 64 or not name.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)):
                return None
        return day, candidates
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return None


def _our_club(message):
    compact = re.sub(r"\s+", "", message)
    return (any(term in message for term in ("my team", "my club", "our team", "our club"))
            or any(term in compact for term in ("我的球队", "我的俱乐部", "我球队", "我们的球队", "我们的俱乐部"))
            or bool(re.search(r"(?:我们|咱们)(?:接下来|下一场|下场|下轮|下一轮)", compact))
            or bool(re.search(r"\bwho(?:m)?\s+(?:are|do|will)\s+we\s+(?:play|face)\b", message)))


def choose_calendar_scope(envelope: dict, message: str, *, now: datetime | None = None) -> dict | None:
    try:
        if not isinstance(message, str) or not isinstance(envelope, dict) or envelope.get("status") != "partial":
            return None
        snapshot = envelope["snapshot"]
        if snapshot.get("schema") != "fa-offseason/0.1" or snapshot.get("status") != "partial":
            return None
        now = now or datetime.now(timezone.utc)
        normalized = message.casefold()
        candidate_context = _candidate_context(snapshot, now)
        candidates = candidate_context[1] if candidate_context else []
        found = [item for item in candidates if item["clubName"].casefold() in normalized]
        # Explicitly named clubs always win over a first-person reference. Do not
        # silently substitute the current manager for another club or ambiguity.
        if len(found) > 1:
            return None
        if found:
            chosen, selection = found[0], "named_candidate"
            day = candidate_context[0]
            scope = {"club_uid": chosen["clubUid"], "manager_uid": chosen["uid"], "club_name": chosen["clubName"]}
        else:
            prepared = prepare_offseason_advice(envelope, now=now)
            facts = prepared["facts"] if prepared else {}
            manager = facts.get("current_manager")
            if manager is not None and facts.get("game_date") is not None and _our_club(normalized):
                day = date.fromisoformat(facts["game_date"])
                # Names are optional labels, not the source of the verified UID.
                names = {item["clubName"] for item in candidates
                         if item["uid"] == manager["uid"] and item["clubUid"] == manager["club_uid"]}
                scope = {"club_uid": manager["club_uid"], "manager_uid": manager["uid"],
                         "team_uid": manager["team_uid"], "club_name": next(iter(names)) if len(names) == 1 else None}
                selection = "native_current_manager"
            elif (candidate_context and len(candidates) == 1
                    and any(term in normalized for term in ("我的球队", "我的俱乐部", "我球队", "my team", "my club"))):
                chosen, selection = candidates[0], "unique_candidate_not_active_confirmed"
                day = candidate_context[0]
                scope = {"club_uid": chosen["clubUid"], "manager_uid": chosen["uid"], "club_name": chosen["clubName"]}
            else:
                return None
        finish = min(day + timedelta(days=29), date(day.year, 12, 31))
        return {**scope, "start": day.isoformat(), "end": finish.isoformat(), "selection": selection}
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return None
