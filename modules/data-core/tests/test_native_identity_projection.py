"""Synthetic pinned native identity/position evidence; never reads a game process."""
import asyncio
from copy import deepcopy
import json

import pytest

from football_assistant_agent.offseason_advice import (
    EXPECTED_ASSEMBLY, EXPECTED_METADATA, prepare_offseason_advice,
)
from football_assistant_agent.service import AgentService
from football_assistant_data.offseason_snapshot import EXPECTED_BINARY
from test_offseason_advice_context import selected_envelope

# The order, names and masks are from the actual audited PositionFields.cs,
# not a football-position list or the production validator's own constants.
MAPPING = (
    ("GK", "Goalkeeper", 1), ("DL", "DefenderLeft", 8),
    ("DC", "DefenderCentre", 16), ("DR", "DefenderRight", 4),
    ("DM", "DefensiveMidfielderCentre", 128), ("ML", "MidfielderLeft", 512),
    ("MC", "MidfielderCentre", 1024), ("MR", "MidfielderRight", 256),
    ("AML", "AttackingMidfielderLeft", 4096), ("AMC", "AttackingMidfielderCentre", 8192),
    ("AMR", "AttackingMidfielderRight", 2048), ("ST", "AttackerCentre", 16384),
    ("WBL", "WingBackLeft", 64), ("WBR", "WingBackRight", 32),
)


def positions(gk=20, **values):
    values = {"GK": gk, **values}
    fields = [{"code": code, "nativeName": name, "maskBit": bit,
               "value": values.get(code, 0), "natural": values.get(code, 0) >= 18}
              for code, name, bit in MAPPING]
    return {"status": "available", "source": "native_position_familiarity",
            "proof": "exact_player_type_uid_double_read", "fields": fields,
            "naturalPositionMask": sum(row["maskBit"] for row in fields if row["natural"]),
            "naturalPositionCodes": [row["code"] for row in fields if row["natural"]],
            "goalkeeperFamiliarity": gk, "isGoalkeeper": gk >= 15,
            "naturalThreshold": 18, "goalkeeperThreshold": 15, "unusedSlot151Raw": 20}


def native_envelope():
    data = selected_envelope()
    snapshot = data["snapshot"]
    snapshot["nativeProfile"] = {"status": "available", "reason": None, "matched": True,
        "gamePluginSha256": EXPECTED_BINARY, "gameAssemblySha256": EXPECTED_ASSEMBLY,
        "metadataSha256": EXPECTED_METADATA}
    snapshot["manager"] = {"status": "available", "reason": None, "source": "native_gcUM_selection",
        "proof": "selected_human_owner", "selectionScope": "current_local_human_manager",
        "uid": 12, "teamUid": 56, "clubUid": 34, "contractKind": 0,
        "observedAt": snapshot["capturedAt"], "atomicSnapshot": False}
    for row in snapshot["team"]["players"]:
        row.update(teamUid=56, positions=positions())
    snapshot["player"]["value"]["positions"] = positions()
    return data


def projected(data=None, club_uid=34, person_uid=101):
    return prepare_offseason_advice(data or native_envelope(), club_uid=club_uid, person_uid=person_uid)["facts"]


def test_native_identity_is_independent_of_query_target_and_not_save_authority():
    facts = projected()
    assert facts["current_manager"] == {
        "uid": 12, "team_uid": 56, "club_uid": 34,
        "selection_scope": "current_local_human_manager", "source": "native_gcUM_selection", "atomic_snapshot": False}
    assert facts["selected_club_is_current"] is True
    other = projected(club_uid=35)
    assert other["current_manager"] == facts["current_manager"]
    assert other["selected_club_is_current"] is False
    assert other["team_candidates"] == [] and other["player_candidate"] is None
    discovery = projected(club_uid=0, person_uid=0)
    assert discovery["current_manager"] == facts["current_manager"]
    assert discovery["selected_club_is_current"] is None


@pytest.mark.parametrize("key,value", [
    ("status", "candidate"), ("source", "only_one_candidate"), ("proof", "collection_count"),
    ("selectionScope", "network_authority"), ("uid", True), ("uid", 0),
    ("teamUid", "56"), ("clubUid", 0xffffffff), ("uid", 0x80000000), ("contractKind", True), ("contractKind", 256),
    ("atomicSnapshot", True), ("observedAt", "2000-01-01T00:00:00Z"),
])
def test_malformed_manager_is_unknown_without_losing_independent_positions(key, value):
    data = native_envelope()
    data["snapshot"]["manager"][key] = value
    facts = projected(data)
    assert facts["current_manager"] is None and facts["selected_club_is_current"] is None
    assert facts["player_candidate"]["positions"]["is_goalkeeper"] is True
    assert facts["game_date"] == "2026-02-07"


@pytest.mark.parametrize("key", ["gamePluginSha256", "gameAssemblySha256", "metadataSha256"])
def test_all_three_actual_fingerprints_are_required_for_new_semantics(key):
    data = native_envelope()
    data["snapshot"]["nativeProfile"][key] = "0" * 64
    facts = projected(data)
    assert facts["current_manager"] is None
    assert facts["player_candidate"]["positions"] is None
    assert all(row["positions"] is None for row in facts["team_candidates"])
    assert facts["player_candidate"]["attributes_raw"]["reflexesRaw"] == 211


def test_legacy_and_missing_new_evidence_stay_unknown_not_zero():
    facts = projected(selected_envelope())
    assert facts["current_manager"] is None
    assert facts["player_candidate"]["positions"] is None
    assert facts["player_candidate"]["attributes_raw"] == {
        "reflexesRaw": 211, "handlingRaw": 0, "anticipationRaw": 255, "jumpingRaw": 54}
    assert all(row["position"] == "unknown" and row["positions"] is None for row in facts["team_candidates"])
    data = native_envelope()
    data["snapshot"]["nativeProfile"].pop("metadataSha256")
    assert projected(data)["current_manager"] is None


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_profile_match_flag_must_be_literal_true(value):
    data = native_envelope()
    data["snapshot"]["nativeProfile"]["matched"] = value
    facts = projected(data)
    assert facts["current_manager"] is None and facts["player_candidate"]["positions"] is None


def test_uppercase_producer_fingerprints_match_and_current_manager_can_be_only_evidence():
    data = native_envelope()
    snapshot = data["snapshot"]
    for key in ("gamePluginSha256", "gameAssemblySha256", "metadataSha256"):
        snapshot["nativeProfile"][key] = snapshot["nativeProfile"][key].upper()
    for key in ("date", "team", "player", "managerCandidates", "tactic"):
        snapshot.pop(key)
    result = prepare_offseason_advice(data)
    assert result["facts"]["current_manager"]["uid"] == 12
    snapshot["manager"]["proof"] = "one_candidate"
    assert prepare_offseason_advice(data) is None


@pytest.mark.parametrize("gk,expected_keeper,expected_mask", [(14, False, 8), (15, True, 8), (17, True, 8), (18, True, 9), (20, True, 9)])
def test_goalkeeper_and_natural_thresholds_are_distinct(gk, expected_keeper, expected_mask):
    data = native_envelope()
    data["snapshot"]["player"]["value"]["positions"] = positions(gk, DL=18, DC=17)
    result = projected(data)["player_candidate"]["positions"]
    assert result["is_goalkeeper"] is expected_keeper
    assert result["natural_position_mask"] == expected_mask
    assert result["natural_position_codes"] == (["GK", "DL"] if gk >= 18 else ["DL"])
    assert len(result["familiarities"]) == 14
    assert result["current_match_position"] == "unknown"
    assert "unusedSlot151Raw" not in result


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(status="unknown"), lambda p: p.update(source="raw_attributes"),
    lambda p: p.update(proof="type_only"), lambda p: p.update(fields=p["fields"][:-1]),
    lambda p: p["fields"][0].update(value=True), lambda p: p["fields"][0].update(value=21),
    lambda p: p["fields"][0].update(value=-1), lambda p: p["fields"][0].update(value="20"),
    lambda p: p["fields"][0].update(natural=1), lambda p: p["fields"][0].update(natural=False),
    lambda p: p["fields"][1].update(code="DR"), lambda p: p["fields"][1].update(nativeName="DefenderRight"),
    lambda p: p["fields"][1].update(maskBit=4), lambda p: p["fields"][0].update(maskBit=True),
    lambda p: p.update(naturalPositionMask=True), lambda p: p.update(naturalPositionMask=3),
    lambda p: p.update(naturalPositionCodes=["GK", "SW"]), lambda p: p.update(naturalPositionCodes="GK"),
    lambda p: p.update(goalkeeperFamiliarity=True), lambda p: p.update(goalkeeperFamiliarity=19),
    lambda p: p.update(isGoalkeeper=1), lambda p: p.update(isGoalkeeper=False),
    lambda p: p.update(naturalThreshold=15), lambda p: p.update(goalkeeperThreshold=18),
    lambda p: p.update(unusedSlot151Raw=21), lambda p: p.update(unusedSlot151Raw=True),
])
def test_malformed_positions_fail_closed_at_field_scope(mutate):
    data = native_envelope()
    mutate(data["snapshot"]["player"]["value"]["positions"])
    facts = projected(data)
    assert facts["player_candidate"]["positions"] is None
    assert facts["player_candidate"]["attributes_raw"]["reflexesRaw"] == 211
    assert facts["current_manager"] is not None
    assert facts["team_candidates"][0]["positions"] is not None


def test_all_mask_names_follow_audited_mapping_and_reserved_slot_never_counts():
    data = native_envelope()
    data["snapshot"]["player"]["value"]["positions"] = positions(0, **{code: 18 for code, _, _ in MAPPING if code != "GK"})
    result = projected(data)["player_candidate"]["positions"]
    assert result["natural_position_mask"] == sum(bit for code, _, bit in MAPPING if code != "GK")
    assert result["natural_position_codes"] == [code for code, _, _ in MAPPING if code != "GK"]
    assert result["is_goalkeeper"] is False
    assert [field["native_name"] for field in result["familiarities"]] == [name for _, name, _ in MAPPING]


def test_untrusted_extra_fields_and_native_addresses_never_reach_model_context():
    data = native_envelope()
    for value in [data["snapshot"]["manager"], data["snapshot"]["nativeProfile"],
                  data["snapshot"]["player"]["value"]["positions"],
                  *data["snapshot"]["player"]["value"]["positions"]["fields"]]:
        value["address"] = "NATIVE_ADDRESS_DO_NOT_SEND"
    agent = AgentService(None, None)
    captured = {}
    async def fake_chat(message, conversation_id, context, **kwargs):
        captured.update(context)
        return {"reply": "fixture", "conversation_id": conversation_id}
    agent._chat = fake_chat
    try:
        response = asyncio.run(agent.offseason_advice("位置是什么", None, data, club_uid=34, person_uid=101))
        encoded = json.dumps(captured)
        assert "NATIVE_ADDRESS_DO_NOT_SEND" not in encoded
        assert not any(token in encoded for token in ("sha256", "Sha256", EXPECTED_BINARY, EXPECTED_ASSEMBLY, "sessionId", "observedAt", "playerOffset"))
        assert response["context"]["native_profile"]["metadataSha256"] == EXPECTED_METADATA
    finally:
        agent.close()


def run_advice(data, message="我执教哪支球队", related_people=()):
    agent = AgentService(None, None)
    captured = {}
    async def fake_chat(message, conversation_id, context, **kwargs):
        captured.update(context)
        return {"reply": "fixture", "conversation_id": conversation_id}
    agent._chat = fake_chat
    try:
        response = asyncio.run(agent.offseason_advice(message, None, data, club_uid=34, related_people=related_people))
        return response, captured
    finally:
        agent.close()


def test_current_team_question_uses_only_valid_native_identity():
    response, context = run_advice(native_envelope())
    assert context["facts"]["current_manager"]["club_uid"] == 34
    assert "未确认当前执教身份" not in response["reply"]
    assert "不是网络权限" in response["reply"] or "不代表网络权限" in response["reply"]
    response, context = run_advice(selected_envelope())
    assert context == {}
    assert "fixture" not in response["reply"]


def test_related_read_can_inherit_valid_roster_positions_but_not_override_failure():
    data = native_envelope()
    related = deepcopy(data)
    del related["snapshot"]["player"]["value"]["positions"]
    response, _ = run_advice(data, "比较门将", [{"person_uid": 101, "envelope": related}])
    assert response["context"]["facts"]["player_candidates"][0]["positions"]["is_goalkeeper"] is True
    assert "位置仍未由读取确认" not in response["reply"]
    assert "不是 20 分评级" in response["reply"] and "熟练度为 0 到 20" in response["reply"]
    related["snapshot"]["player"]["value"]["positions"] = positions()
    related["snapshot"]["player"]["value"]["positions"]["isGoalkeeper"] = False
    response, _ = run_advice(data, "比较门将", [{"person_uid": 101, "envelope": related}])
    assert response["context"]["facts"]["player_candidates"][0]["positions"] is None


@pytest.mark.parametrize("change", [
    lambda s: s["manager"].update(uid=13), lambda s: s["manager"].update(clubUid=35),
    lambda s: s["manager"].update(teamUid=57), lambda s: s.pop("manager"),
    lambda s: s["player"]["value"].update(positions=positions(14)),
])
def test_related_reads_cannot_mix_native_manager_binding_or_position_evidence(change):
    data = native_envelope()
    related = deepcopy(data)
    change(related["snapshot"])
    response, context = run_advice(data, "比较门将", [{"person_uid": 101, "envelope": related}])
    assert response["context"]["facts"]["player_candidates"] == []
    assert context == {}
    assert "未全部通过校验" in response["reply"]


@pytest.mark.parametrize("target", ["manager", "positions", "raw"])
def test_changed_related_evidence_during_model_generation_suppresses_reply(target):
    data = native_envelope()
    related = deepcopy(data)
    agent = AgentService(None, None)
    async def change_during_chat(*args, **kwargs):
        if target == "manager":
            related["snapshot"]["manager"]["uid"] = 13
        elif target == "positions":
            related["snapshot"]["player"]["value"]["positions"] = positions(14)
        else:
            related["snapshot"]["player"]["value"]["details"]["reflexesRaw"] = 1
        return {"reply": "MUST NOT DISPLAY"}
    agent._chat = change_during_chat
    try:
        response = asyncio.run(agent.offseason_advice("比较门将", None, data, club_uid=34,
            related_people=[{"person_uid": 101, "envelope": related}]))
        assert "MUST NOT DISPLAY" not in response["reply"]
        assert response["context"]["freshness"] == "expired_during_generation"
    finally:
        agent.close()
