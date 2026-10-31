"""Advice gates with synthetic DTOs and in-process stubs only; no provider calls."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from football_assistant_agent import business_advice as gate
from football_assistant_agent import service

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def snapshot():
    return {'snapshot_id': 'test-only', 'source': {
        'kind': 'native_read', 'adapter_id': 'test', 'adapter_version': 'test',
        'session_id': 'test', 'game_build': 'TEST', 'game_assembly_sha256': 'a'*64,
        'metadata_sha256': 'b'*64, 'mapper_version': 'test', 'evidence_ref': 'TEST ONLY',
        'captured_at': NOW, 'observed_at': NOW, 'synthetic': False, 'identity_scope': 'test'},
        'players': [{'id': 'test-player', 'name': 'TEST player', 'injured': False,
                     'fitness_percent': 0.0}]}


@pytest.mark.parametrize('capability', gate.CAPABILITIES)
def test_missing_data_deterministic_and_free(capability):
    class NeverAccess:
        def __getattr__(self, name):
            pytest.fail('blocked advice touched configuration/store: ' + name)
    agent = service.AgentService(NeverAccess(), NeverAccess())
    first = asyncio.run(agent.business_advice('Recommend a player', None, capability))
    assert first == asyncio.run(agent.business_advice('Other message', None, capability))
    assert first['status'] == 'blocked'
    assert first['missing_requirements'] == ['business_snapshot']
    assert first['facts'] == first['inferences'] == []
    assert set(first['readiness']['capabilities']) == set(gate.CAPABILITIES)


@pytest.mark.parametrize('payload', [{'source_status': {'availability': 'connected'}, 'facts': [1]},
                                    {'registry': [1], 'production_ready': True}, [], 'bad'])
def test_diagnostic_or_user_ready_claim_not_business_input(payload):
    result = gate.prepare_business_advice('player_info', payload, now=NOW)
    assert result['status'] == 'blocked'
    assert 'invalid_business_snapshot' in result['readiness']['reasons']
    assert not result['facts']


def test_native_claim_and_synthetic_never_self_certify():
    data = snapshot()
    for kind, synthetic in [('native_read', False), ('test_fixture', True), ('unverified', False)]:
        data['source'].update(kind=kind, synthetic=synthetic)
        result = gate.prepare_business_advice('player_info', data, now=NOW)
        assert result['status'] == 'blocked'
        assert 'native_producer_not_verified' in result['readiness']['reasons']
        assert result['facts'] == []


def test_stale_snapshot_reports_missing_and_no_facts():
    result = gate.prepare_business_advice('schedule_analysis', snapshot(), now=NOW+timedelta(seconds=16))
    assert result['status'] == 'blocked'
    assert 'observation_not_fresh' in result['readiness']['reasons']
    assert 'fixtures' in result['missing_requirements']
    assert result['facts'] == []


def test_invalid_capability_never_runs_model():
    with pytest.raises(ValueError, match='unsupported business capability'):
        gate.prepare_business_advice('invent', None)


def test_future_context_provenance_and_defense_in_depth(monkeypatch):
    # Test-only simulated reviewed producer. No production API accepts this override.
    monkeypatch.setattr(gate, 'assess_business_snapshot', lambda *a, **k: {
        'production_ready': True, 'reasons': [],
        'capabilities': {c: {'ready': True, 'missing_requirements': []} for c in gate.CAPABILITIES}})
    data = snapshot()
    result = gate.prepare_business_advice('player_info', data, now=NOW)
    assert result['status'] == 'ready'
    facts = {f['field_ref']: f for f in result['facts']}
    assert facts['/players/0/fitness_percent']['value'] == 0
    assert facts['/players/0/injured']['value'] is False
    assert facts['/players/0/name']['snapshot_id'] == 'test-only'
    assert facts['/players/0/name']['source']['evidence_ref'] == 'TEST ONLY'
    assert '/players/0/age' not in facts
    assert result['inferences'] == []
    data['source']['synthetic'] = True
    assert gate.prepare_business_advice('player_info', data, now=NOW)['status'] == 'blocked'
    data['source']['synthetic'] = False
    assert gate.prepare_business_advice('player_info', data, now=NOW+timedelta(seconds=16))['facts'] == []


def test_business_model_path_omits_history_and_memories_using_only_stubs(monkeypatch):
    captured = {}
    class Store:
        def memories(self): pytest.fail('memories used as football facts')
        def recent_messages(self, *args): pytest.fail('history used as football facts')
        def reserve_model_request(self, *args): return True  # In-memory stub, not billing.
        def append_turn(self, *args): captured['saved'] = args
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Agent:
        def __init__(self, model, system_prompt, **kwargs): captured['prompt'] = system_prompt
        async def run(self, message, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output='TEST stub output, not football advice')
    monkeypatch.setattr(service, 'AsyncOpenAI', Client)
    monkeypatch.setattr(service, 'OpenAICompatibleProvider', lambda *a, **k: object())
    monkeypatch.setattr(service, 'OpenAIChatModel', lambda *a, **k: object())
    monkeypatch.setattr(service, 'Agent', Agent)
    settings = SimpleNamespace(model_configured=True, model_budget_id='test', model_request_limit=1,
        api_key='TEST-NOT-A-KEY', base_url='http://invalid.test', model_timeout=1,
        model='TEST', max_output_tokens=10, model_extra_body={})
    agent = service.AgentService(settings, Store())
    asyncio.run(agent._chat('test', 'test-conversation', {'source_status': 'TEST'}, business=True))
    assert captured['message_history'] == []
    assert '你是埃克拉（Eckera）' in captured['prompt']
    assert '小北' not in captured['prompt']
    assert '已读取事实' in captured['prompt'] and '建议/推断' in captured['prompt']
    assert '"explicit_memories": []' in captured['prompt']


def test_future_context_preserves_time_scope_and_money_units(monkeypatch):
    # Test-only trust stub; production remains blocked and no model is invoked.
    monkeypatch.setattr(gate, 'assess_business_snapshot', lambda *a, **k: {
        'production_ready': True, 'reasons': [],
        'capabilities': {c: {'ready': True, 'missing_requirements': []} for c in gate.CAPABILITIES}})
    data = snapshot()
    data.update(world_date='2026-10-30', world_local_time='14:25:00', world_time_basis='game_local',
                managed_team_id='test-team', fixture_window_start='2026-10-30',
                fixture_window_end='2026-11-06', fixtures_complete=True, fixtures=[],
                candidate_scope='observed shortlist only', candidate_ids=['test-player'],
                candidates_complete=True, finances=[{'team_id': 'test-team', 'wage_room': {
                    'period': 'week', 'money': {'amount_minor': -1500, 'currency': 'GBP',
                                               'minor_unit_exponent': 2}}}])
    def facts(capability):
        result = gate.prepare_business_advice(capability, data, now=NOW)
        assert result['status'] == 'ready'
        return {f['field_ref']: f['value'] for f in result['facts']}
    schedule = facts('schedule_analysis')
    assert schedule['/world_local_time'] == '14:25:00'
    assert schedule['/world_time_basis'] == 'game_local'
    assert schedule['/fixture_window_start'] == '2026-10-30'
    assert schedule['/fixture_window_end'] == '2026-11-06'
    assert schedule['/fixtures'] == []  # Observed empty within window, not all future fixtures.
    assert '/candidate_scope' not in schedule
    transfer = facts('transfer_analysis')
    assert transfer['/candidate_scope'] == 'observed shortlist only'
    assert transfer['/finances/0/wage_room/period'] == 'week'
    assert transfer['/finances/0/wage_room/money/amount_minor'] == -1500
    assert transfer['/finances/0/wage_room/money/currency'] == 'GBP'
    assert transfer['/finances/0/wage_room/money/minor_unit_exponent'] == 2
    assert '/fixture_window_start' not in transfer
