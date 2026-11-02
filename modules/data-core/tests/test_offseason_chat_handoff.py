"""Synthetic routing checks only: no game, model, or subprocess execution."""
from fastapi.testclient import TestClient
from football_assistant_data.app import create_app
from football_assistant_data import offseason_snapshot
from test_reader import AUTH, settings


def test_partial_readback_reaches_chat_and_blocked_advice_without_business_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'reader.exe'))
    calls = []
    from test_offseason_advice_context import envelope as fixture
    envelope = fixture()
    async def read(executable, club, person, **kwargs):
        calls.append((club, person, kwargs)); return envelope
    monkeypatch.setattr(offseason_snapshot, 'read_offseason', read)
    app = create_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        async def partial(message, conversation, value, **kwargs):
            assert value is envelope
            return {'status': 'partial', 'source_status': 'partial_native_candidates', 'reply': 'Partial observations only', 'conversation_id': conversation}
        monkeypatch.setattr(app.state.agent, 'offseason_advice', partial)
        for route, extra in [('/v1/chat', {}), ('/v1/agent/business-advice', {'capability': 'tactical_analysis'})]:
            result = client.post(route, headers=AUTH, json={'message': 'Which keeper fits?', **extra})
            assert result.status_code == 200
            assert result.json()['source_status'] == 'partial_native_candidates'
        assert calls == [(0, 0, {'require_current_producer': True})] * 2
        assert app.state.business_snapshots.read()['snapshot'] is None
        monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '0')
        result = client.post('/v1/agent/business-advice', headers=AUTH, json={'message': 'Which keeper?', 'capability': 'tactical_analysis'})
        assert result.json()['status'] == 'blocked'
        assert len(calls) == 2
