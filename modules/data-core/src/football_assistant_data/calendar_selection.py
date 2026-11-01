"""Select only an explicitly named or uniquely evidenced manager-club candidate."""
from datetime import date, datetime, timedelta, timezone


def choose_calendar_scope(envelope: dict, message: str, *, now: datetime | None = None) -> dict | None:
    try:
        if not isinstance(message, str) or envelope.get("status") != "partial":
            return None
        snapshot = envelope["snapshot"]
        if snapshot.get("schema") != "fa-offseason/0.1" or snapshot.get("status") != "partial":
            return None
        source = snapshot["managerCandidates"]
        if source.get("status") != "experimental_candidates_incomplete" or source.get("unknown") != 0:
            return None
        candidates = source["candidates"]
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 16:
            return None
        now = now or datetime.now(timezone.utc)
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
        normalized = message.casefold()
        found = []
        for item in candidates:
            uid, name, manager_uid = item["clubUid"], item["clubName"], item["uid"]
            if type(uid) is not int or not 0 < uid < 4294967295 or type(manager_uid) is not int or not 0 < manager_uid < 4294967295 or not isinstance(name, str) or not 2 <= len(name) <= 64 or not name.strip():
                return None
            if name.casefold() in normalized:
                found.append(item)
        if len(found) == 1:
            chosen, selection = found[0], "named_candidate"
        elif not found and len(candidates) == 1 and any(term in normalized for term in ("我的球队", "我的俱乐部", "我球队", "my team", "my club")):
            chosen, selection = candidates[0], "unique_candidate_not_active_confirmed"
        else:
            return None
        finish = min(day + timedelta(days=29), date(day.year, 12, 31))
        return {"club_uid": chosen["clubUid"], "manager_uid": chosen["uid"], "club_name": chosen["clubName"],
                "start": day.isoformat(), "end": finish.isoformat(), "selection": selection}
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return None
