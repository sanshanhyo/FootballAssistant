"""Sanitized failure categories; fake credentials and in-memory provider transport only."""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, APIResponseValidationError
from pydantic_ai.exceptions import ModelHTTPError, ModelConnectionError, ModelTimeoutError, UnexpectedModelBehavior, UserError

from football_assistant_agent import service
from football_assistant_agent.storage import CompanionStore
from football_assistant_data.offseason_conversation import OffseasonConversation
from test_backend import settings

PRIVATE = 'PRIVATE_KEY_URL_PROMPT_BODY'
SCOPE = {'save_id': 'fixture-save', 'character_id': 'official.eckera'}


@pytest.fixture
def model_fixture(tmp_path, monkeypatch):
    state = {'error': None, 'output': 'fixture reply', 'calls': 0, 'client_error': None}
    class Client:
        def __init__(self, **kwargs):
            state['client_options'] = kwargs
            if state['client_error']:
                raise state['client_error']
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Agent:
        def __init__(self, *args, **kwargs): state['agent_options'] = kwargs
        async def run(self, *args, **kwargs):
            state['calls'] += 1
            if state['error']:
                raise state['error']
            return SimpleNamespace(output=state['output'])
    monkeypatch.setattr(service, 'AsyncOpenAI', Client)
    monkeypatch.setattr(service, 'Agent', Agent)
    monkeypatch.setattr(service, 'OpenAICompatibleProvider', lambda *a, **k: object())
    monkeypatch.setattr(service, 'OpenAIChatModel', lambda *a, **k: object())
    store = CompanionStore(None)
    agent = service.AgentService(settings(tmp_path, base_url='https://model.invalid/v1',
                                         model='fixture-model', api_key='FIXTURE-KEY'), store)
    yield agent, store, state
    agent.close()
    store.close()


def invoke(agent):
    return asyncio.run(agent.general_advice('fixture question', 'conversation', character_context=SCOPE))


def assert_safe(error, reason, stage, status=None):
    assert error.reason == reason
    assert error.stage == stage
    assert error.status_code == status
    assert set(vars(error)) == {'reason', 'stage', 'status_code'}
    assert PRIVATE not in str(error) + str(vars(error))
    assert 'https://' not in str(error) + str(vars(error))


@pytest.mark.parametrize('status,reason', [
    (400, 'request_rejected'), (401, 'auth'), (403, 'auth'), (404, 'request_rejected'),
    (408, 'timeout'), (422, 'request_rejected'), (429, 'rate_limit'),
    (500, 'provider_error'), (503, 'provider_error'), (504, 'timeout'),
])
def test_provider_http_failures_are_classified_without_body_or_retry(model_fixture, status, reason):
    agent, store, state = model_fixture
    state['error'] = ModelHTTPError(status, PRIVATE, body={'error': PRIVATE})
    with pytest.raises(service.ModelUnavailable) as caught:
        invoke(agent)
    assert_safe(caught.value, reason, 'provider', status)
    assert agent.last_error and store.counts()['messages'] == 0
    assert state['calls'] == 1
    assert state['client_options']['max_retries'] == state['agent_options']['retries'] == 0


@pytest.mark.parametrize('error,reason', [
    (TimeoutError(PRIVATE), 'timeout'),
    (APITimeoutError(httpx.Request('POST', 'https://model.invalid/' + PRIVATE)), 'timeout'),
    (APIConnectionError(message=PRIVATE, request=httpx.Request('POST', 'https://model.invalid/' + PRIVATE)), 'connection'),
    (ModelConnectionError(PRIVATE, PRIVATE), 'connection'),
    (ModelTimeoutError(PRIVATE, PRIVATE), 'timeout'),
    (UnexpectedModelBehavior(PRIVATE, body=PRIVATE), 'invalid_response'),
    (APIResponseValidationError(httpx.Response(200, request=httpx.Request('POST', 'https://model.invalid')), PRIVATE), 'invalid_response'),
    (RuntimeError(PRIVATE), 'unknown'),
])
def test_transport_or_response_failures_keep_only_safe_categories(model_fixture, error, reason):
    agent, store, state = model_fixture
    state['error'] = error
    with pytest.raises(service.ModelUnavailable) as caught:
        invoke(agent)
    assert_safe(caught.value, reason, 'provider')
    assert agent.last_error and store.counts()['messages'] == 0 and state['calls'] == 1


@pytest.mark.parametrize('error,reason', [
    (ImportError(PRIVATE), 'dependency'), (TypeError(PRIVATE), 'configuration'),
    (ValueError(PRIVATE), 'configuration'), (UserError(PRIVATE), 'configuration'),
])
def test_client_initialization_failure_never_blames_auth_without_status(model_fixture, error, reason):
    agent, store, state = model_fixture
    state['client_error'] = error
    with pytest.raises(service.ModelUnavailable) as caught:
        invoke(agent)
    assert_safe(caught.value, reason, 'client')
    assert state['calls'] == 0 and agent.last_error
    assert store.counts()['messages'] == 0


@pytest.mark.parametrize('method', ['memories', 'recent_messages', 'reserve_model_request', 'append_turn'])
def test_storage_failures_are_not_mislabeled_as_model_connectivity(model_fixture, monkeypatch, method):
    agent, store, state = model_fixture
    def failed(*args, **kwargs): raise sqlite3.OperationalError(PRIVATE)
    monkeypatch.setattr(store, method, failed)
    with pytest.raises(service.ModelUnavailable) as caught:
        invoke(agent)
    assert_safe(caught.value, 'storage', 'storage')
    assert state['calls'] == (1 if method == 'append_turn' else 0)
    assert store.counts()['messages'] == 0


@pytest.mark.parametrize('output', ['', '  ', None, {'body': PRIVATE}])
def test_nontext_or_empty_reply_is_invalid_response(model_fixture, output):
    agent, store, state = model_fixture
    state['output'] = output
    with pytest.raises(service.ModelUnavailable) as caught:
        invoke(agent)
    assert_safe(caught.value, 'invalid_response', 'response')
    assert agent.last_error and store.counts()['messages'] == 0


def test_bounded_cause_chain_supports_wrapped_timeout_without_reading_messages():
    error = RuntimeError(PRIVATE)
    error.__cause__ = APITimeoutError(httpx.Request('POST', 'https://model.invalid/' + PRIVATE))
    assert_safe(service._model_failure(error, 'provider'), 'timeout', 'provider')
    error.__cause__ = error
    assert_safe(service._model_failure(error, 'provider'), 'unknown', 'provider')


def test_model_and_reader_busy_keep_previous_error_state_and_do_not_call_provider(model_fixture):
    agent, store, state = model_fixture
    async def check():
        reader = OffseasonConversation()
        body = SimpleNamespace(message='你好', conversation_id='conversation', character_context=None)
        await agent._lock.acquire()
        await reader.lock.acquire()
        try:
            with pytest.raises(service.ModelUnavailable) as caught:
                await reader.reply(body, None, agent)
            assert_safe(caught.value, 'busy', 'lock')
            assert agent.last_error is False
            agent.last_error = True
            with pytest.raises(service.ModelUnavailable) as caught:
                await agent.chat('你好', None)
            assert_safe(caught.value, 'busy', 'lock')
            assert agent.last_error is True  # Busy neither invents nor clears a previous failure.
        finally:
            agent._lock.release()
            reader.lock.release()
    asyncio.run(check())
    assert state['calls'] == 0 and store.counts()['messages'] == 0
    assert 'client_options' not in state


def test_success_clears_previous_failure_without_a_synthetic_reply(model_fixture):
    agent, _, state = model_fixture
    agent.last_error = True
    assert invoke(agent)['reply'] == state['output']
    assert agent.last_error is False and state['calls'] == 1


@pytest.mark.parametrize('status,reason', [(200, None), (401, 'auth'), (429, 'rate_limit'), (400, 'request_rejected')])
def test_real_sdk_in_memory_transport_preserves_request_and_sanitized_failure(tmp_path, monkeypatch, status, reason):
    """No sockets, proxy changes, external requests, or mocked model classes."""
    original_client = service.AsyncOpenAI
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        body = ({'id': 'fixture', 'created': 0, 'object': 'chat.completion', 'model': 'fixture-model',
                 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'fixture reply'}, 'finish_reason': 'stop'}],
                 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
                if status == 200 else {'error': {'message': PRIVATE, 'type': PRIVATE, 'code': PRIVATE}})
        return httpx.Response(status, json=body)
    def client(**kwargs):
        kwargs['http_client'] = httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)
        return original_client(**kwargs)
    monkeypatch.setattr(service, 'AsyncOpenAI', client)
    store = CompanionStore(None)
    agent = service.AgentService(settings(tmp_path, base_url='https://model.invalid/v1',
                                         model='fixture-model', api_key='FIXTURE-KEY'), store)
    try:
        if reason is None:
            assert invoke(agent)['reply'] == 'fixture reply'
        else:
            with pytest.raises(service.ModelUnavailable) as caught:
                invoke(agent)
            assert_safe(caught.value, reason, 'provider', status)
        assert len(requests) == 1
        assert requests[0]['model'] == 'fixture-model'
        assert 'messages' in requests[0]
    finally:
        agent.close()
        store.close()


def test_diagnostic_fields_reject_free_form_or_invalid_values():
    error = service.ModelUnavailable('fixture', reason=PRIVATE, stage=PRIVATE, status_code=True)
    assert_safe(error, 'unknown', 'provider')
