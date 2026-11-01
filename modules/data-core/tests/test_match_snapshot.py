import json
from datetime import datetime, timedelta, timezone

from football_assistant_data.match_snapshot import read_match_snapshot


def test_match_freshness_and_lifecycle(tmp_path):
    path = tmp_path / "match.json"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert read_match_snapshot(path, now=now)["status"] == "unavailable"
    data = {"schema_version": "fa-match-snapshot/0.1", "source": "native_match_hook",
            "synthetic": False, "status": "live", "captured_at": now.isoformat()}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_match_snapshot(path, now=now)["status"] == "experimental"
    assert read_match_snapshot(path, now=now + timedelta(seconds=16))["reason"] == "stale"
    data["status"] = "ended"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_match_snapshot(path, now=now)["reason"] == "no_live_match"
    data["status"] = "live"
    data["synthetic"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_match_snapshot(path, now=now)["status"] == "unavailable"
