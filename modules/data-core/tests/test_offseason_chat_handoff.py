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
        assert result.status_code == 503  # General chat still needs an actually configured model.
        assert result.json()['detail']['code'] == 'model_not_configured'
        assert len(calls) == 2


def test_reported_keeper_questions_return_scoped_confirmation_without_model(tmp_path, monkeypatch):
    from test_offseason_advice_context import envelope as fixture
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'reader.exe'))
    value = fixture()
    async def read(*args, **kwargs):
        return value
    monkeypatch.setattr(offseason_snapshot, 'read_offseason', read)
    scope = {'save_id': 'session:test', 'character_id': 'official.eckera', 'persona': 'Do not echo this private persona'}
    app = create_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        general_calls = []
        async def forbidden(message, conversation, context, **kwargs):
            assert context == {'source_status': 'general_knowledge'}
            general_calls.append(message)
            return {'reply': '先聊选门将的思路，我偏向接球稳、出击判断好的。', 'conversation_id': conversation}
        monkeypatch.setattr(app.state.agent, '_chat', forbidden)
        for message in ['你推荐谁给我们门将', '你推荐我们选择哪个门将呢']:
            result = client.post('/v1/chat', headers=AUTH, json={'message': message, 'conversation_id': 'reported', 'character_context': scope})
            assert result.status_code == 200
            data = result.json()
            assert data['reply'].strip()
            assert data['character_context'] == {k: scope[k] for k in ('save_id', 'character_id')}
            assert 'private persona' not in str(data)

        assert general_calls == ['你推荐我们选择哪个门将呢']  # Repeated confirmation no longer blocks the companion.
