"""Real loopback HTTP handoff, using synthetic data and never a model provider.

The child owns a pre-bound ephemeral socket (no free-port race), its private
runtime and SQLite files. Stdin requests graceful shutdown on every test path;
terminate/kill are bounded fallbacks, not platform-specific signal handlers.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest

from football_assistant_data.reader_client import ReaderClient


CAPABILITIES = ('player_info', 'transfer_analysis', 'tactical_analysis', 'schedule_analysis')


def _child(folder: Path, mode: str, seeded: bool):
    import importlib.abc
    import socket
    import threading
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    report = {'paths': [], 'model_calls': 0, 'budget_calls': 0, 'sdk_calls': 0}
    blocked_roots = {'football_assistant_agent', 'pydantic_ai', 'openai'}
    if mode == 'reader':
        class NoModelImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in blocked_roots:
                    raise AssertionError('reader imported agent/model SDK')
        sys.meta_path.insert(0, NoModelImports())
    else:
        from football_assistant_agent import service
        from football_assistant_agent.storage import CompanionStore

        async def forbidden_chat(*args, **kwargs):
            report['model_calls'] += 1
            raise AssertionError('blocked advice entered model path')

        def forbidden_budget(*args, **kwargs):
            report['budget_calls'] += 1
            raise AssertionError('blocked advice reserved model budget')

        def forbidden_sdk(*args, **kwargs):
            report['sdk_calls'] += 1
            raise AssertionError('blocked advice constructed provider client')

        service.AgentService._chat = forbidden_chat
        CompanionStore.reserve_model_request = forbidden_budget
        service.AsyncOpenAI = forbidden_sdk

    from football_assistant_data.config import Settings
    from football_assistant_data.app import create_app
    import uvicorn

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        # Explicit settings avoid loading .env or any real key/runtime directory.
        settings = Settings(data_dir=folder, runtime_file=folder / 'runtime.json',
                            port=listener.getsockname()[1],
                            base_url='http://127.0.0.1:1/v1', model='test-only',
                            api_key='not-a-real-key', model_request_limit=1)
        app = create_app(settings, enable_agent=mode == 'agent')
        lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def controlled_lifespan(application):
            async with lifespan(application):
                if seeded:
                    now = datetime.now(timezone.utc).isoformat()
                    store = application.state.business_snapshots
                    token = store.start_session('synthetic-live-session')
                    store.publish({'snapshot_id': 'synthetic-live-snapshot', 'source': {
                        'kind': 'test_fixture', 'adapter_id': 'loopback-test',
                        'adapter_version': 'test', 'session_id': 'synthetic-live-session',
                        'game_build': 'synthetic-build', 'mapper_version': 'test',
                        'game_assembly_sha256': 'a' * 64, 'metadata_sha256': 'b' * 64,
                        'evidence_ref': 'synthetic-test-only', 'identity_scope': 'test',
                        'captured_at': now, 'observed_at': now, 'synthetic': True},
                        'players': [{'id': 'test-player', 'name': '测试球员',
                                     'fitness_percent': 0.0, 'injured': False}]},
                        session_token=token)
                yield

        app.router.lifespan_context = controlled_lifespan

        @app.middleware('http')
        async def trace_paths(request, call_next):
            # Store paths only: never serialize request headers or runtime tokens.
            report['paths'].append(request.url.path)
            return await call_next(request)

        server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False,
                                log_level='critical', timeout_graceful_shutdown=2,
                                loop='asyncio', http='h11', lifespan='on'))

        def stop_on_stdin():
            sys.stdin.readline()
            server.should_exit = True

        threading.Thread(target=stop_on_stdin, daemon=True).start()
        try:
            server.run(sockets=[listener])
        finally:
            report['model_modules_loaded'] = sorted(blocked_roots.intersection(sys.modules))
            (folder / 'report.json').write_text(json.dumps(report), encoding='utf-8')


@contextmanager
def live_server(tmp_path, *, mode='reader', seeded=False):
    """Start an isolated interpreter so SDK-import checks aren't collection-order dependent."""
    folder = tmp_path / 'live'
    folder.mkdir()
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), '--server', str(folder), mode,
         'seeded' if seeded else 'empty'],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8',
    )
    runtime_file = folder / 'runtime.json'
    result = SimpleNamespace(folder=folder)
    try:
        with httpx.Client(trust_env=False, timeout=1) as http:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    pytest.fail('isolated loopback server exited during startup')
                try:
                    runtime = json.loads(runtime_file.read_text(encoding='utf-8'))
                    health = http.get(runtime['base_url'] + '/health')
                    if health.status_code == 200:
                        break
                except (OSError, ValueError, httpx.HTTPError):
                    pass
                if time.monotonic() >= deadline:
                    pytest.fail('isolated loopback server startup timed out')
                time.sleep(0.025)
            result.http = http
            result.base = runtime['base_url']
            result.auth = {'Authorization': 'Bearer ' + runtime['token']}
            result.reader = ReaderClient(runtime_file, timeout=2)
            yield result
    finally:
        if process.poll() is None:
            try:
                process.stdin.write('stop\n')
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        process.stdin.close()
    assert process.returncode == 0, 'isolated loopback server did not shut down cleanly'
    assert not runtime_file.exists(), 'graceful shutdown left a runtime credential file'
    result.report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))


def assert_envelope(payload, *, snapshot):
    assert payload['schema_version'] == 'business-readiness/0.1'
    assert payload['status'] == 'unavailable'
    assert payload['production_ready'] is False
    assert 'native_producer_not_verified' in payload['reasons']
    assert set(payload['capabilities']) == set(CAPABILITIES)
    assert all(cap['ready'] is False for cap in payload['capabilities'].values())
    assert ('snapshot' in payload) is snapshot
    assert 'facts' not in payload and 'reader_api' not in payload


@pytest.mark.parametrize('seeded', [False, True])
def test_reader_business_wire_and_no_sdk_or_ui_fallback(tmp_path, seeded):
    from test_reader import fixture as ui_fixture

    with live_server(tmp_path, seeded=seeded) as server:
        assert server.http.get(server.base + '/health').json()['agent_enabled'] is False
        for suffix in ('status', 'snapshot'):
            url = server.base + '/v1/reader/business/' + suffix
            for headers in ({}, {'Authorization': 'Bearer deliberately-wrong'}):
                response = server.http.get(url, headers=headers)
                assert response.status_code == 401
                assert response.json()['detail']['code'] == 'unauthorized'
            assert server.http.post(url, json={}, headers=server.auth).status_code == 405
        assert server.http.post(server.base + '/v1/observations', json=ui_fixture(),
                                headers=server.auth).status_code == 200
        # UI facts exist, but neither business method requests a UI/legacy endpoint.
        assert server.http.get(server.base + '/v1/reader/snapshot',
                               headers=server.auth).json()['facts_total'] == 3
        status = server.reader.business_status()
        snapshot = server.reader.business_snapshot()
        assert_envelope(status, snapshot=False)
        assert_envelope(snapshot, snapshot=True)
        assert status == {k: v for k, v in snapshot.items() if k != 'snapshot'}
        if seeded:
            data = snapshot['snapshot']
            assert data['snapshot_id'] == 'synthetic-live-snapshot'
            assert data['players'][0]['name'] == '测试球员'
            assert data['players'][0]['fitness_percent'] == 0.0
            assert data['players'][0]['injured'] is False
            assert isinstance(data['source']['captured_at'], str)
            assert snapshot['source'] == data['source']
            assert 'synthetic_data' in snapshot['reasons']
        else:
            assert snapshot['snapshot'] is None and snapshot['source'] is None
            assert 'no_business_snapshot' in snapshot['reasons']
        assert server.http.post(server.base + '/v1/agent/business-advice',
                                headers=server.auth, json={'message': 'No model',
                                'capability': 'player_info'}).status_code == 404
    assert server.report['model_modules_loaded'] == []
    assert not (server.folder / 'companion.sqlite').exists()
    assert server.report['paths'][-4:] == [
        '/health', '/v1/reader/business/status', '/v1/reader/business/snapshot',
        '/v1/agent/business-advice']


@pytest.mark.parametrize('seeded', [False, True])
def test_agent_business_handoff_stays_blocked_without_budget_or_model(tmp_path, seeded):
    import sqlite3

    with live_server(tmp_path, mode='agent', seeded=seeded) as server:
        snapshot = server.reader.business_snapshot()
        assert_envelope(snapshot, snapshot=True)
        url = server.base + '/v1/agent/business-advice'
        body = {'message': 'Recommend a player', 'capability': 'player_info',
                'conversation_id': 'loopback-test'}
        for headers in ({}, {'Authorization': 'Bearer deliberately-wrong'}):
            assert server.http.post(url, headers=headers, json=body).status_code == 401
        assert server.http.post(url, headers=server.auth,
                               json={**body, 'snapshot': snapshot['snapshot']}).status_code == 422
        for capability in CAPABILITIES:
            response = server.http.post(url, headers=server.auth,
                                        json={**body, 'capability': capability})
            assert response.status_code == 200
            advice = response.json()
            assert advice['status'] == 'blocked'
            assert advice['conversation_id'] == 'loopback-test'
            assert advice['facts'] == advice['inferences'] == []
            assert advice['readiness']['production_ready'] is False
            assert advice['readiness']['source'] == snapshot['source']
            assert 'native_producer_not_verified' in advice['readiness']['reasons']
            assert advice['missing_requirements']
    assert server.report['model_calls'] == server.report['budget_calls'] == server.report['sdk_calls'] == 0
    with sqlite3.connect(server.folder / 'companion.sqlite') as db:
        assert db.execute('SELECT COUNT(*) FROM model_request_counts').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0


if __name__ == '__main__':
    assert sys.argv[1] == '--server'
    _child(Path(sys.argv[2]), sys.argv[3], sys.argv[4] == 'seeded')
