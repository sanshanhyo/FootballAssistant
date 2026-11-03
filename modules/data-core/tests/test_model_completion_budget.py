"""Reasoning headroom is independent of bubble length and explicit user budgets."""
import asyncio
import json

import httpx
import pytest

from football_assistant_agent import service
from football_assistant_agent.storage import CompanionStore
from football_assistant_data.config import DEFAULT_MAX_OUTPUT_TOKENS, Settings
from test_backend import settings


def test_constructor_defaults_leave_room_for_reasoning_without_changing_other_limits(tmp_path):
    config = settings(tmp_path)
    assert DEFAULT_MAX_OUTPUT_TOKENS == config.max_output_tokens == 4096
    assert config.model_timeout == 45
    assert config.model_request_limit == 0
    assert config.model_extra_body == {}


@pytest.mark.parametrize('explicit', [None, 160, 180, 512, 8192])
def test_environment_default_and_explicit_completion_limits(tmp_path, monkeypatch, explicit):
    # Desktop mode avoids reading any real project dotenv file.
    monkeypatch.setenv('FOOTBALL_ASSISTANT_DESKTOP', '1')
    monkeypatch.delenv('FOOTBALL_ASSISTANT_ENV_FILE', raising=False)
    monkeypatch.setenv('FOOTBALL_ASSISTANT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('FOOTBALL_ASSISTANT_MODEL_TIMEOUT', '17')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT', '2')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_MODEL_EXTRA_BODY', '{"fixture_option":true}')
    if explicit is None:
        monkeypatch.delenv('FOOTBALL_ASSISTANT_MAX_OUTPUT_TOKENS', raising=False)
    else:
        monkeypatch.setenv('FOOTBALL_ASSISTANT_MAX_OUTPUT_TOKENS', str(explicit))
    config = Settings.from_env()
    assert config.max_output_tokens == (4096 if explicit is None else explicit)
    assert config.model_timeout == 17 and config.model_request_limit == 2
    assert config.model_extra_body == {'fixture_option': True}


@pytest.mark.parametrize('explicit', [None, 160, 180, 512])
def test_real_sdk_sends_selected_completion_cap_once_and_keeps_short_reply_guidance(tmp_path, monkeypatch, explicit):
    """An in-memory provider verifies wiring, not a prediction of real model reasoning length."""
    original_client = service.AsyncOpenAI
    requests, client_options = [], []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'fixture', 'created': 0, 'object': 'chat.completion', 'model': 'fixture-model',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'reasoning_content': 'PRIVATE_THINKING',
                                              'content': '先说结论，再聊两句就好。'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 100, 'total_tokens': 101},
        })
    def client(**kwargs):
        client_options.append({'timeout': kwargs['timeout'], 'max_retries': kwargs['max_retries']})
        kwargs['http_client'] = httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)
        return original_client(**kwargs)
    monkeypatch.setattr(service, 'AsyncOpenAI', client)
    overrides = {} if explicit is None else {'max_output_tokens': explicit}
    config = settings(tmp_path, base_url='https://model.invalid/v1', model='fixture-model', api_key='FIXTURE-KEY',
                      model_timeout=17, model_request_limit=1, model_budget_id='fixture-one-request',
                      model_extra_body={'fixture_option': {'enabled': True}}, **overrides)
    store = CompanionStore(None)
    agent = service.AgentService(config, store)
    try:
        result = asyncio.run(agent.general_advice('下一场呢？', 'fixture'))
        assert result['reply'] == '先说结论，再聊两句就好。'
        assert 'PRIVATE_THINKING' not in str(result)
        assert len(requests) == 1
        assert requests[0].get('max_completion_tokens', requests[0].get('max_tokens')) == (4096 if explicit is None else explicit)
        prompt = ' '.join(message['content'] for message in requests[0]['messages'] if message['role'] == 'system')
        assert '默认用1到3句短句回应' in prompt
        assert requests[0]['fixture_option'] == config.model_extra_body['fixture_option'] == {'enabled': True}
        assert client_options == [{'timeout': 17, 'max_retries': 0}]
        with pytest.raises(service.ModelBudgetExceeded):
            asyncio.run(agent.general_advice('再来一条', 'fixture'))
        assert len(requests) == 1
    finally:
        agent.close()
        store.close()
