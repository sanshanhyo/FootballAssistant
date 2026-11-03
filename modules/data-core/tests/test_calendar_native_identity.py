"""Only independent native identity removes the legacy calendar uncertainty prefix."""
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


def envelope():
    data = native_envelope()
    data['snapshot']['calendar'] = calendar_envelope()['snapshot']['calendar']
    data['snapshot']['secret'] = 'DO_NOT_SEND_NATIVE_METADATA'
    return data


@pytest.mark.parametrize('kind', ['verified', 'legacy', 'candidate_only', 'wrong_club', 'stale_manager', 'unverified_producer'])
def test_calendar_prefix_and_identity_marker_require_independent_native_proof(kind):
    data = envelope()
    club = 34
    if kind == 'legacy': data = calendar_envelope()
    elif kind == 'candidate_only': data['snapshot'].pop('manager')
    elif kind == 'wrong_club': club = 35
    elif kind == 'stale_manager': data['snapshot']['manager']['observedAt'] = '2000-01-01T00:00:00Z'
    elif kind == 'unverified_producer': data['producerVerified'] = False
    agent = AgentService(None, None)
    captured = {}
    async def fake_chat(message, conversation_id, context, **kwargs):
        captured.update(deepcopy(context))
        return {'reply': 'fixture', 'conversation_id': conversation_id}
    agent._chat = fake_chat
    try:
        response = asyncio.run(agent.calendar_advice('我们下一场打谁？', 'c', data, club, '2026-02-01', '2026-02-10'))
        assert response['status'] == 'partial'
        assert '可能不完整' in response['reply']
        if kind == 'verified':
            assert '未确认它是当前执教球队' not in response['reply']
            identity = captured['managed_team_identity']
            assert identity['selected_club_is_current'] is True
            assert identity['current_manager']['club_uid'] == club
        else:
            assert '未确认它是当前执教球队' in response['reply']
            assert 'managed_team_identity' not in captured
        assert 'DO_NOT_SEND_NATIVE_METADATA' not in str(captured)
        assert 'nativeProfile' not in str(captured) and 'sha256' not in str(captured)
    finally:
        agent.close()


def test_calendar_prompt_accepts_only_explicit_identity_marker(tmp_path, captured_model):
    store = CompanionStore(None)
    agent = AgentService(settings(tmp_path, base_url='https://model.invalid/v1', model='fixture', api_key='FIXTURE'), store)
    try:
        result = asyncio.run(agent.calendar_advice('我们下一场打谁？', 'c', envelope(), 34, '2026-02-01', '2026-02-10'))
        payload = json.loads(captured_model['message'])
        identity = payload['untrusted_calendar_data']['managed_team_identity']
        assert identity['selected_club_is_current'] is True
        assert '只有独立的 managed_team_identity' in captured_model['prompt']
        assert '否则不得推断身份' in captured_model['prompt']
        assert '不得推断无比赛或完整赛程' in captured_model['prompt']
        assert '未确认它是当前执教球队' not in result['reply']
    finally:
        agent.close()
        store.close()
