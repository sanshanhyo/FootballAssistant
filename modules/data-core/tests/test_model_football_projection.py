"""Human-readable outbound football facts retain strict local identity validation."""
import asyncio
from copy import deepcopy
import json

import pytest

from football_assistant_agent.service import AgentService
from football_assistant_agent.storage import CompanionStore
from test_backend import settings
from test_calendar_advice import envelope as calendar_envelope
from test_companionship_isolation import captured_model
from test_native_identity_projection import native_envelope


def keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item)


def assert_no_internal_fields(value):
    for key in keys(value):
        assert 'uid' not in key.lower()
        assert 'raw' not in key.lower()
        assert key not in {'source', 'source_status', 'proof', 'status', 'atomic_snapshot', 'selection_scope',
                           'native_name', 'mask_bit', 'natural_position_mask', 'observed_at', 'session_id'}


@pytest.fixture
def agent(tmp_path):
    store = CompanionStore(None)
    value = AgentService(settings(tmp_path, base_url='https://model.invalid/v1', model='fixture', api_key='FIXTURE'), store)
    yield value
    value.close()
    store.close()


def test_model_gets_named_bindings_and_football_values_not_internal_identifiers(agent, captured_model):
    data = native_envelope()
    result = asyncio.run(agent.offseason_advice('我执教哪支球队？', 'c', data, club_uid=34, person_uid=101))
    model = json.loads(captured_model['message'])['untrusted_native_partial_data']
    assert_no_internal_fields(model)
    manager = model['facts']['current_manager']
    assert manager == {'name': 'Synthetic manager', 'club_name': 'Synthetic club', 'identity_confirmed': True}
    player = model['facts']['player_candidate']
    assert player['name'] == 'Player 101'
    assert player['attributes'] == {'反应': 211, '手控球': 0, '预判': 255, '弹跳': 54}
    assert player['positions']['is_goalkeeper'] is True
    assert player['positions']['familiarities']['GK'] == 20
    assert '不是常用的20分评分' in str(model['limitations'])
    assert '普通足球对话用姓名、球队名和自然说法' in captured_model['prompt']
    # The model projection does not weaken local checks, response metadata, or source attribution.
    assert result['context']['facts']['current_manager']['club_uid'] == 34
    assert result['context']['facts']['player_candidate']['uid'] == 101
    assert result['context']['facts']['player_candidate']['attributes_raw']['reflexesRaw'] == 211
    assert result['source_status'] == 'partial_native_candidates'


@pytest.mark.parametrize('mutation', ['wrong_manager', 'wrong_club', 'missing', 'ambiguous'])
def test_current_names_are_never_guessed_from_nonmatching_or_ambiguous_candidates(agent, captured_model, mutation):
    data = native_envelope()
    rows = data['snapshot']['managerCandidates']['candidates']
    if mutation == 'wrong_manager': rows[0]['uid'] = 99
    elif mutation == 'wrong_club': rows[0]['clubUid'] = 35
    elif mutation == 'missing': rows.clear()
    else:
        other = deepcopy(rows[0])
        other.update(name='Different manager', clubName='Different club')
        rows.append(other)
    asyncio.run(agent.offseason_advice('我执教哪支球队？', 'c', data, club_uid=34))
    manager = json.loads(captured_model['message'])['untrusted_native_partial_data']['facts']['current_manager']
    assert manager == {'name': None, 'club_name': None, 'identity_confirmed': True}


def test_unknown_identity_never_turns_named_candidates_into_current_manager(agent, captured_model):
    data = native_envelope()
    data['snapshot'].pop('manager')
    asyncio.run(agent.offseason_advice('我执教哪支球队？', 'c', data, club_uid=34))
    facts = json.loads(captured_model['message'])['untrusted_native_partial_data']['facts']
    assert facts['current_manager'] is None and facts['selected_club_is_current'] is None
    assert facts['manager_club_candidates'] == [{'name': 'Synthetic manager', 'clubName': 'Synthetic club'}]


def test_calendar_projection_removes_identifiers_and_binds_only_matched_names(agent, captured_model):
    data = native_envelope()
    data['snapshot']['calendar'] = calendar_envelope()['snapshot']['calendar']
    result = asyncio.run(agent.calendar_advice('下一场打谁？', 'c', data, 34, '2026-02-01', '2026-02-10'))
    model = json.loads(captured_model['message'])['untrusted_calendar_data']
    assert_no_internal_fields(model)
    assert model['managed_team_identity']['current_manager']['club_name'] == 'Synthetic club'
    assert model['calendar']['fixtures'] == [{'date': '2026-02-07', 'opponent': 'Synthetic opponent', 'venue': 'unknown'}]
    assert result['context']['selected_club_uid'] == 34


def test_comparison_coverage_does_not_print_raw_or_native_validation_labels(agent, captured_model):
    data = native_envelope()
    response = asyncio.run(agent.offseason_advice('比较门将', 'c', data, club_uid=34,
        related_people=[{'person_uid': 101, 'envelope': deepcopy(data)}]))
    assert '不是 20 分评级' in response['reply']
    for word in ('raw', 'UID', '原生校验', '实验性'):
        assert word not in response['reply']
