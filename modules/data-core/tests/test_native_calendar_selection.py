"""Native local-manager calendar routing uses existing strict projection only."""
from datetime import datetime, timedelta

import pytest

from football_assistant_data.calendar_selection import choose_calendar_scope
from test_native_identity_projection import native_envelope


def calendar_envelope():
    data = native_envelope()
    candidates = data["snapshot"]["managerCandidates"]
    candidates.update(unknown=0, observedAt=data["snapshot"]["capturedAt"])
    candidates["candidates"][0]["clubName"] = "示例球队"
    return data


@pytest.mark.parametrize("message", [
    "我们下一场打谁？", "我们 下一场 打谁？", "我们下场比赛什么时候？",
    "我的球队接下来有哪些比赛", "我们的俱乐部下一场是谁", "咱们下轮打谁",
    "Who do we play next?", "Our team next fixtures", "My club next match",
])
def test_first_person_question_uses_verified_native_manager(message):
    result = choose_calendar_scope(calendar_envelope(), message)
    assert result == {"club_uid": 34, "manager_uid": 12, "team_uid": 56, "club_name": "示例球队",
                      "start": "2026-02-07", "end": "2026-03-08", "selection": "native_current_manager"}
    assert "fixtures" not in result


def test_native_identity_does_not_need_a_candidate_name_or_complete_candidate_list():
    data = calendar_envelope()
    del data["snapshot"]["managerCandidates"]
    scope = choose_calendar_scope(data, "我们下一场打谁？")
    assert scope["selection"] == "native_current_manager" and scope["club_name"] is None
    data = calendar_envelope()
    data["snapshot"]["managerCandidates"]["unknown"] = 1
    scope = choose_calendar_scope(data, "我们下一场打谁？")
    assert scope["club_uid"] == 34 and scope["club_name"] is None


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[0].update(uid=13),
    lambda rows: rows[0].update(clubUid=35),
    lambda rows: rows[0].update(clubName="\n不可信名字"),
    lambda rows: rows.append({**rows[0], "clubName": "冲突的名字"}),
])
def test_club_name_is_optional_and_must_match_both_verified_uids(mutation):
    data = calendar_envelope()
    mutation(data["snapshot"]["managerCandidates"]["candidates"])
    scope = choose_calendar_scope(data, "我们下一场打谁？")
    assert scope["club_uid"] == 34 and scope["manager_uid"] == 12
    assert scope["club_name"] is None


def test_explicit_other_club_wins_without_claiming_it_is_current():
    data = calendar_envelope()
    data["snapshot"]["managerCandidates"]["candidates"].append({
        "uid": 13, "clubUid": 35, "clubName": "另一支队", "name": "Other manager"})
    scope = choose_calendar_scope(data, "我们想看另一支队下一场打谁")
    assert scope["selection"] == "named_candidate"
    assert scope["club_uid"] == 35 and scope["manager_uid"] == 13
    assert "team_uid" not in scope
    assert choose_calendar_scope(data, "我的球队和另一支队还有示例球队接下来有哪些比赛") is None


def test_duplicate_names_remain_ambiguous_even_with_native_manager():
    data = calendar_envelope()
    rows = data["snapshot"]["managerCandidates"]["candidates"]
    rows.append({**rows[0], "uid": 13, "clubUid": 35})
    assert choose_calendar_scope(data, "我们想看示例球队下一场打谁") is None


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(producerVerified=False),
    lambda data: data["snapshot"]["manager"].update(proof="one_candidate"),
    lambda data: data["snapshot"]["manager"].update(uid=True),
    lambda data: data["snapshot"]["manager"].update(observedAt="2000-01-01T00:00:00Z"),
    lambda data: data["snapshot"]["nativeProfile"].update(matched=False),
    lambda data: data["snapshot"]["nativeProfile"].update(metadataSha256="0" * 64),
    lambda data: data["snapshot"]["process"].update(sessionId="0" * 64),
    lambda data: data["snapshot"].pop("manager"),
    lambda data: data["snapshot"]["date"].update(date="2026-02-30"),
    lambda data: data["snapshot"]["date"].update(observedAt="2000-01-01T00:00:00Z"),
])
def test_missing_or_invalid_native_evidence_cannot_enable_we_routing(mutation):
    data = calendar_envelope()
    mutation(data)
    assert choose_calendar_scope(data, "我们下一场打谁？") is None


def test_invalid_native_evidence_does_not_promote_legacy_candidate_fallback():
    data = calendar_envelope()
    data["snapshot"]["manager"]["proof"] = "one_candidate"
    scope = choose_calendar_scope(data, "我的球队接下来有哪些比赛")
    assert scope["selection"] == "unique_candidate_not_active_confirmed"
    assert "team_uid" not in scope


def test_unknown_third_person_and_bare_next_match_are_not_implicit_current_club():
    data = calendar_envelope()
    assert choose_calendar_scope(data, "他们下一场打谁？") is None
    assert choose_calendar_scope(data, "下一场打谁？") is None
    assert choose_calendar_scope(data, "未知球队接下来有哪些比赛") is None


def test_native_range_stays_within_supported_year_and_freshness_window():
    data = calendar_envelope()
    data["snapshot"]["date"]["date"] = "2026-12-29"
    scope = choose_calendar_scope(data, "我们下一场打谁？")
    assert scope["start"] == "2026-12-29" and scope["end"] == "2026-12-31"
    now = datetime.fromisoformat(data["snapshot"]["capturedAt"]) + timedelta(seconds=31)
    assert choose_calendar_scope(data, "我们下一场打谁？", now=now) is None


def test_native_reselection_exposes_manager_club_and_team_changes_for_caller_guard():
    data = calendar_envelope()
    before = choose_calendar_scope(data, "我们下一场打谁？")
    for key, output, value in (("uid", "manager_uid", 13), ("clubUid", "club_uid", 35), ("teamUid", "team_uid", 57)):
        data = calendar_envelope()
        data["snapshot"]["manager"][key] = value
        after = choose_calendar_scope(data, "我们下一场打谁？")
        assert after[output] != before[output]
        assert after["selection"] == "native_current_manager"
