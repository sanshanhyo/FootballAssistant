"""Synthetic consumer-boundary tests; not evidence of game extraction."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from football_assistant_data.business_store import BusinessSessionConflict, BusinessSnapshotConflict, BusinessSnapshotStore
from football_assistant_data.reader import create_reader_app
from football_assistant_data.reader_cli import arguments, execute
from football_assistant_data.reader_client import ReaderError
from test_reader import AUTH, fixture as ui_fixture, server_fixture, settings


def snapshot(now=None, session='synthetic-business-session'):
    now = now or datetime.now(timezone.utc)
    return {'snapshot_id': 'synthetic-snapshot', 'source': {
        'kind': 'test_fixture', 'adapter_id': 'synthetic', 'adapter_version': 'test',
        'session_id': session, 'game_build': 'synthetic-build',
        'game_assembly_sha256': 'a' * 64, 'metadata_sha256': 'b' * 64,
        'mapper_version': 'test', 'evidence_ref': 'synthetic-test-only',
        'identity_scope': 'test', 'captured_at': now.isoformat(),
        'observed_at': now.isoformat(), 'synthetic': True},
        'players': [{'id': 'test-player', 'name': 'Synthetic player'}]}


@pytest.mark.parametrize('route', ['status', 'snapshot'])
def test_auth_default_unavailable_and_no_public_ingestion(tmp_path, route):
    with TestClient(create_reader_app(settings(tmp_path)), base_url='http://127.0.0.1') as client:
        path = '/v1/reader/business/' + route
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'Authorization': 'Bearer wrong'}).status_code == 401
        result = client.get(path, headers=AUTH).json()
        assert result['status'] == 'unavailable' and result['production_ready'] is False
        assert {'no_business_snapshot', 'native_producer_not_verified'} <= set(result['reasons'])
        assert all(not cap['ready'] for cap in result['capabilities'].values())
        if route == 'snapshot': assert result['snapshot'] is None
        assert client.post(path, json=snapshot(), headers=AUTH).status_code == 405
        assert client.get(path, headers={**AUTH, 'host': 'evil.example'}).status_code == 400


def test_business_channel_does_not_promote_ui_and_legacy_is_unchanged(tmp_path):
    with TestClient(create_reader_app(settings(tmp_path)), base_url='http://127.0.0.1') as client:
        assert client.post('/v1/observations', json=ui_fixture(), headers=AUTH).status_code == 200
        assert client.get('/v1/reader/snapshot', headers=AUTH).json()['facts_total'] == 3
        business = client.get('/v1/reader/business/snapshot', headers=AUTH).json()
        assert business['snapshot'] is None
        assert business['source'] is None
        assert client.get('/v1/reader/status', headers=AUTH).json()['reader_api'] == 1


def test_internal_publication_revalidation_freshness_and_session_aba(tmp_path):
    app = create_reader_app(settings(tmp_path))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        store = app.state.business_snapshots
        now = datetime.now(timezone.utc)
        token = store.start_session('synthetic-business-session')
        bad = snapshot(now); bad['players'][0]['age'] = '20'
        with pytest.raises(ValidationError): store.publish(bad, session_token=token)
        assert store.read()['snapshot'] is None
        data = snapshot(now)
        store.publish(data, session_token=token)
        data['players'][0]['name'] = 'mutated outside store'
        result = client.get('/v1/reader/business/snapshot', headers=AUTH).json()
        assert result['snapshot']['players'][0]['name'] == 'Synthetic player'
        assert result['production_ready'] is False and 'synthetic_data' in result['reasons']
        stale = store.read(now=now + timedelta(seconds=16))
        assert stale['snapshot'] is None and 'capture_not_fresh' in stale['reasons']
        replacement = store.start_session('synthetic-business-session')
        with pytest.raises(BusinessSessionConflict): store.publish(snapshot(), session_token=token)
        assert store.read()['snapshot'] is None
        with pytest.raises(BusinessSessionConflict): store.publish(snapshot(session='other'), session_token=replacement)
        store.publish(snapshot(), session_token=replacement)
        store.invalidate()
        assert store.read()['snapshot'] is None
        with pytest.raises(BusinessSessionConflict): store.publish(snapshot(), session_token=replacement)
    assert store.read()['snapshot'] is None


def test_fixed_business_client_commands_do_not_fallback(tmp_path):
    def handler(path, headers):
        if path == '/health': return 200, {'service': 'football-assistant', 'status': 'ok'}, {}
        return 404, {}, {}
    with server_fixture(tmp_path, handler) as (client, seen, _):
        for method in (client.business_status, client.business_snapshot):
            with pytest.raises(ReaderError) as error: method()
            assert error.value.code == 'http_404'
        assert [p for p, _ in seen] == ['/health', '/v1/reader/business/status', '/v1/reader/business/snapshot']
    class Client:
        def business_status(self): return {'status': 'unavailable'}
        def business_snapshot(self): return {'snapshot': None}
    output = []
    execute(Client(), ['business-status'], output=output.append)
    execute(Client(), ['business-snapshot'], output=output.append)
    assert output == [{'status': 'unavailable'}, {'snapshot': None}]
    with pytest.raises(ReaderError): arguments('business-snapshot', ['--raw-ui'])


def test_business_advice_route_is_agent_only_and_forbids_client_data(tmp_path, monkeypatch):
    path = '/v1/agent/business-advice'
    body = {'message': 'Recommend a player', 'capability': 'transfer_analysis'}
    with TestClient(create_reader_app(settings(tmp_path / 'reader')), base_url='http://127.0.0.1') as client:
        assert client.post(path, json=body, headers=AUTH).status_code == 404
    from football_assistant_data.app import create_app
    app = create_app(settings(tmp_path / 'agent'))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        async def forbidden_model(*args, **kwargs):
            raise AssertionError('blocked business advice must not call model')
        def forbidden_budget(*args, **kwargs):
            raise AssertionError('blocked business advice must not reserve budget')
        monkeypatch.setattr(app.state.agent, '_chat', forbidden_model)
        monkeypatch.setattr(app.state.companion, 'reserve_model_request', forbidden_budget)
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json={**body, 'snapshot': snapshot()}, headers=AUTH).status_code == 422
        assert client.post(path, json={**body, 'capability': 'arbitrary'}, headers=AUTH).status_code == 422
        response = client.post(path, json=body, headers=AUTH)
        assert response.status_code == 200
        result = response.json()
        assert result['status'] == 'blocked'
        assert result['facts'] == result['inferences'] == []
        assert result['readiness']['production_ready'] is False


def test_publication_rejects_older_capture_and_identity_collisions_without_refresh():
    store = BusinessSnapshotStore()
    token = store.start_session('synthetic-business-session')
    now = datetime.now(timezone.utc)
    original = snapshot(now)
    store.publish(original, session_token=token)
    store.publish(original, session_token=token)  # Exact retry is a no-op.
    assert store.read(now=now + timedelta(seconds=16))['snapshot'] is None
    collision = snapshot(now + timedelta(seconds=1))
    with pytest.raises(BusinessSnapshotConflict): store.publish(collision, session_token=token)
    changed = snapshot(now); changed['players'][0]['name'] = 'different'
    with pytest.raises(BusinessSnapshotConflict): store.publish(changed, session_token=token)
    for captured, observed in [(-1, 1), (1, -1), (0, 0), (1, None)]:
        older = snapshot(now + timedelta(seconds=captured))
        older['snapshot_id'] = 'different-snapshot'
        older['source']['observed_at'] = (now + timedelta(seconds=observed)).isoformat() if observed is not None else None
        with pytest.raises(BusinessSnapshotConflict): store.publish(older, session_token=token)
    assert store.read(now=now)['snapshot']['snapshot_id'] == original['snapshot_id']
    newer = snapshot(now + timedelta(seconds=1)); newer['snapshot_id'] = 'newer'
    store.publish(newer, session_token=token)
    with pytest.raises(BusinessSnapshotConflict): store.publish(original, session_token=token)
    assert store.read(now=now + timedelta(seconds=1))['snapshot']['snapshot_id'] == 'newer'
    replacement = store.start_session('synthetic-business-session')
    store.publish(original, session_token=replacement)  # Session reset clears ordering state.
    assert store.read(now=now)['snapshot']['snapshot_id'] == original['snapshot_id']
