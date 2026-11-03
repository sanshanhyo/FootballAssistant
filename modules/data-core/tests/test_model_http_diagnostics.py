"""Full HTTP -> real SDK -> sanitized error contract, with in-memory model transport."""
from copy import deepcopy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from football_assistant_agent import service
from football_assistant_data import offseason_snapshot
from football_assistant_data.app import create_app
from test_backend import settings, AUTH
from test_calendar_advice import envelope as calendar_envelope
from test_native_identity_projection import native_envelope

PRIVATE = 'PRIVATE_PROVIDER_REASONING_AND_RESPONSE_ID'


@pytest.mark.parametrize('route,body', [
    ('/v1/chat', {'message': '你好'}),
    ('/v1/agent/business-advice', {'message': '今天游戏日期是什么？', 'capability': 'player_info'}),
    ('/v1/agent/calendar-advice', {'message': '我们下一场打谁？', 'club_uid': 34,
                                 'start': '2026-02-01', 'end': '2026-02-10'}),
])
@pytest.mark.parametrize('response_kind,subtype', [('length', 'token_limit'), ('stop', 'reasoning_only'), ('tool', 'tool')])
def test_http_keeps_safe_sdk_subtype_and_explicit_limits(tmp_path, monkeypatch, route, body, response_kind, subtype):
    original_client = service.AsyncOpenAI
    requests = []
    def model_transport(request):
        requests.append(json.loads(request.content))
        message = {'role': 'assistant', 'content': None, 'reasoning_content': PRIVATE}
        finish = response_kind
        if response_kind == 'tool':
            finish = 'tool_calls'
            message.pop('reasoning_content')
            message['tool_calls'] = [{'id': PRIVATE, 'type': 'function',
                                      'function': {'name': PRIVATE, 'arguments': '{}'}}]
        return httpx.Response(200, json={'id': PRIVATE, 'created': 0, 'object': 'chat.completion',
            'model': 'fixture-model', 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 180, 'total_tokens': 181}})
    def client(**kwargs):
        assert kwargs['max_retries'] == 0
        kwargs['http_client'] = httpx.AsyncClient(transport=httpx.MockTransport(model_transport), trust_env=False)
        return original_client(**kwargs)
    monkeypatch.setattr(service, 'AsyncOpenAI', client)
    data = native_envelope()
    data['snapshot']['calendar'] = calendar_envelope()['snapshot']['calendar']
    async def read(*args, **kwargs): return deepcopy(data)
    monkeypatch.setattr(offseason_snapshot, 'read_offseason', read)
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_CONSENT', '1')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_OFFSEASON_EXE', str(tmp_path / 'not-executed-reader.exe'))
    config = settings(tmp_path, base_url='https://model.invalid/v1', model='fixture-model', api_key='FIXTURE-KEY',
                      max_output_tokens=180, model_request_limit=1, model_budget_id='fixture-one-request')
    app = create_app(config)
    with TestClient(app, base_url='http://127.0.0.1') as http:
        assert http.post(route, json=body).status_code == 401
        assert requests == []
        result = http.post(route, headers=AUTH, json=body)
        assert result.status_code == 502
        detail = result.json()['detail']
        assert detail['code'] == 'model_unavailable'
        assert detail['reason'] == 'invalid_response'
        assert detail['stage'] == 'provider'
        assert detail['status_code'] is None
        assert detail['subtype'] == subtype
        assert PRIVATE not in result.text and 'FIXTURE-KEY' not in result.text and 'model.invalid' not in result.text
        assert len(requests) == 1
        assert requests[0].get('max_completion_tokens', requests[0].get('max_tokens')) == 180
        assert app.state.agent.counts()['messages'] == 0
        assert app.state.agent.last_error
        second = http.post(route, headers=AUTH, json=body)
        assert second.status_code == 429
        assert second.json()['detail']['code'] == 'model_request_limit'
        assert len(requests) == 1  # No automatic or budget-bypassing retry.
