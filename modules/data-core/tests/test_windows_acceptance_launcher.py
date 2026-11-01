"""No game, model, subprocess or network calls: injected one-shot acceptance flow."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from football_assistant_data import windows_acceptance_launcher as launcher


def plan():
    return dict(schema_version=1, app_commit=launcher.APP_COMMIT,
                candidate_dir=launcher.APPROVED_PARENT + r'\reviewed-candidate',
                portable_exe=r'C:\reviewed\FootballAssistant.exe', portable_sha256=launcher.PORTABLE_SHA256,
                bridge_sha256='b'*64, game_sha256=launcher.GAME_SHA256, pid=123, entry_tid=456,
                session_id='11111111-1111-4111-8111-111111111111', user_data_name='acceptance-one')


def encode(value):
    return json.dumps(value, separators=(',', ':')).encode()


def validate(value):
    raw = encode(value)
    return launcher.validate_plan(raw, hashlib.sha256(raw).hexdigest())


def test_exact_reviewed_plan_and_digest():
    assert validate(plan()) == plan()
    with pytest.raises(ValueError, match='plan_digest_mismatch'):
        launcher.validate_plan(encode(plan()), '0'*64)
    for key, value in [('extra', 'x'), ('schema_version', True), ('app_commit', 'old'),
                       ('pid', True), ('bridge_sha256', 'bad'), ('candidate_dir', r'C:\elsewhere'),
                       ('portable_exe', r'\\server\share\pet.exe'), ('user_data_name', '../escape')]:
        bad = plan(); bad[key] = value
        with pytest.raises(ValueError):
            validate(bad)


def test_environment_has_no_credentials_or_implicit_mock_configuration():
    environment = launcher.launch_environment(dict(PATH='safe', SystemRoot='windows', OPENAI_API_KEY='secret',
        ANTHROPIC_API_KEY='secret', HTTPS_PROXY='secret', FA_COMPANION_MODE='mock',
        FOOTBALL_ASSISTANT_ENV_FILE='old-secrets', FOOTBALL_ASSISTANT_WINDOWS_FINITE_REGISTRATION='untrusted'),
        'private-userdata', {'batch_id': 'own-batch'})
    assert 'secret' not in json.dumps(environment)
    assert environment['PATH'] == 'safe'
    assert 'FA_COMPANION_MODE' not in environment
    assert json.loads(environment['FOOTBALL_ASSISTANT_WINDOWS_FINITE_REGISTRATION']) == {'batch_id': 'own-batch'}
    assert environment['FA_COMPANION_USER_DATA_DIR'] == 'private-userdata'


def test_request_and_registration_derive_from_own_unique_nonce_generation():
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    values = iter(UUID(int=n) for n in range(1, 5))
    request, registration = launcher.make_request(plan(), now, lambda: next(values))
    assert len(request) == 14
    assert request['mode'] == 'profile_all_rows'
    assert launcher.utc(request['expires_at']) - now == timedelta(seconds=120)
    for key in ('batch_id', 'page_epoch', 'first_nonce', 'second_nonce', 'expires_at'):
        assert registration[key] == request[key]
    assert registration['entry_tid'] == plan()['entry_tid']
    with pytest.raises(ValueError, match='duplicate_request_uuid'):
        launcher.make_request(plan(), now, lambda: UUID(int=1))


class Clock:
    def __init__(self):
        self.start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.seconds = 0
    def now(self):
        return self.start + timedelta(seconds=self.seconds)
    def monotonic(self):
        return self.seconds
    def sleep(self, seconds):
        self.seconds += seconds


class Files:
    def __init__(self, trusted):
        self.trusted = trusted
        self.mutations = []
        self.request = None
        self.terminal = False
    def verify_user(self):
        return True
    def hash_local_file(self, path, bound):
        return self.trusted['bridge_sha256'] if bound == 64*1024*1024 else launcher.PORTABLE_SHA256
    def read_control(self, root, name, private=True):
        record = {key: self.trusted[key] for key in launcher.SOURCE_KEYS}
        if name == 'session.json':
            record.update(schema_version=4, mode='goalkeeper_rows0_3', window_class='UnityWndClass',
                finite_rows_enabled_by_default=False, raw_diagnostics_only=True, allowed_scopes=['profile_all_rows'])
        elif name == 'module-status.json':
            record['state'] = 'ready'
        else:
            record.update(consumed=self.terminal, terminal=self.terminal,
                          outcome='completed' if self.terminal else 'running', batch_id=None)
        return record
    def assert_unused(self, root):
        assert self.request is None
    def harden_capture(self, root):
        self.mutations.append('acl')
    def create_user_data(self, name):
        self.mutations.append('userdata')
        return Path('private-userdata')
    def stage_portable(self, *args):
        self.mutations.append('stage_portable')
        return Path('private-userdata/verified.exe')
    def write_new(self, root, name, payload):
        self.mutations.append(name)
        if name == 'finite-rows-request.json':
            assert self.request is None
            self.request = json.loads(payload)
    def read_runtime(self, user_data):
        return dict(base_url='http://127.0.0.1:17827', token='PRIVATE_TOKEN_DO_NOT_OUTPUT', pid=789,
                    started_at='2026-11-01T00:00:00+00:00')


def envelope(trusted, request, clock):
    groups = []
    for category, count in [('goalkeeper', 13), ('mental', 14), ('physical', 8)]:
        rows = [dict(row_index=i, value=10, label_display=f'PRIVATE_LABEL_{i}', capture_freshness='fresh',
                     field_provenance=dict(capture_started_at=request['requested_at'],
                       capture_finished_at=request['requested_at'], association='same_row_same_chunk', player_identity=None))
                for i in range(count)]
        groups.append(dict(category_key=category, rows=rows))
    return dict(status='experimental_ui_current_page_attributes', source='ui', identity=None,
        business_identity_known=False, production_ready=False,
        provenance=dict(platform='windows-x64', adapter_id='footballassistant.windows-finite-ui',
                        session_id=trusted['session_id'], expires_at=request['expires_at']),
        current_page_attributes=dict(batch_id=request['batch_id'], snapshot_atomic=False,
            business_identity_known=False, identity=None, retention='approved_finite_capture_summary', groups=groups,
            progress=dict(chunks_received=18, chunks_expected=18, rows_received=35, rows_expected=35, complete=True)))


def harness(monkeypatch, files=None, **overrides):
    trusted = plan(); files = files or Files(trusted); clock = Clock(); events = []; spawn_calls = []
    lifetime = SimpleNamespace(alive=lambda: True, close=lambda: events.append('closed'))
    monkeypatch.setattr(launcher, 'ensure_port_free', lambda: None)
    def fetch(runtime, endpoint):
        if endpoint == '/v1/status':
            return {'modelConfigured': False}
        if clock.now() > launcher.utc(files.request['expires_at']):
            return {'status': 'unavailable', 'current_page_attributes': None}
        return envelope(trusted, files.request, clock)
    def spawn(*args, **kwargs):
        spawn_calls.append((args, kwargs))
        return SimpleNamespace(poll=lambda: None)
    options = dict(approved_acl=True, approved_capture=True, stable_profile=True, execute_actions=True,
                   now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep, spawn=spawn,
                   fetch=fetch, lifetime_factory=lambda *args: lifetime, emit=events.append)
    options.update(overrides)
    result = launcher.execute(trusted, files, **options)
    return result, files, events, spawn_calls, clock


def test_full_35_row_capture_then_natural_expiry_no_raw_data(monkeypatch):
    result, files, events, spawned, clock = harness(monkeypatch)
    assert result['status'] == 'api_capture_and_expiry_verified'
    assert result['rows_received'] == 35 and result['chunks_received'] == 18
    assert result['expiry_clear_verified'] is True and clock.seconds > 120
    assert result['automatic_model_calls'] == 0 and result['ai_answer_verified'] is False
    assert result['pet_ui_attributes_verified'] is False
    assert files.mutations == ['acl', 'userdata', 'stage_portable', 'settings.json', 'finite-rows-request.json']
    assert len(spawned) == 1 and events[-1] == 'closed'
    public = json.dumps([result, events])
    assert 'PRIVATE' not in public and plan()['session_id'] not in public


@pytest.mark.parametrize('gate', ['approved_acl', 'approved_capture', 'stable_profile'])
def test_each_approval_gate_blocks_all_mutations(monkeypatch, gate):
    result, files, events, spawned, _ = harness(monkeypatch, **{gate: False})
    assert result['code'] == 'explicit_approval_required'
    assert files.mutations == [] and spawned == [] and events[-1] == 'closed'


def test_readonly_preflight_no_mutations(monkeypatch):
    result, files, events, spawned, _ = harness(monkeypatch, execute_actions=False)
    assert result['status'] == 'preflight_passed' and result['approval_required']
    assert files.mutations == [] and spawned == []


def test_terminal_session_never_rearmed(monkeypatch):
    files = Files(plan()); files.terminal = True
    result, files, _, spawned, _ = harness(monkeypatch, files=files)
    assert result['code'] == 'fresh_session_required'
    assert files.mutations == [] and spawned == []


def test_untrusted_exception_payload_is_not_printed(monkeypatch):
    files = Files(plan())
    def refuse():
        raise OSError('PRIVATE_TOKEN and raw player values')
    files.verify_user = refuse
    result, files, _, spawned, _ = harness(monkeypatch, files=files)
    assert result['code'] == 'acceptance_operation_failed'
    assert 'PRIVATE' not in json.dumps(result)
    assert files.mutations == [] and spawned == []


def test_capture_poll_expires_without_republishing(monkeypatch):
    def fetch(runtime, endpoint):
        return {'modelConfigured': False} if endpoint == '/v1/status' else {'status': 'unavailable'}
    result, files, _, spawned, clock = harness(monkeypatch, fetch=fetch)
    assert result['code'] == 'capture_not_verified_before_expiry'
    assert clock.seconds == 120 and len(spawned) == 1
    assert files.mutations.count('finite-rows-request.json') == 1


def test_runtime_replacement_does_not_continue_or_leak_token(monkeypatch):
    files = Files(plan()); reads = [0]
    original = files.read_runtime
    def runtime(root):
        result = original(root); reads[0] += 1
        if reads[0] > 1:
            result['token'] = 'DIFFERENT_PRIVATE_TOKEN'
        return result
    files.read_runtime = runtime
    result, _, _, _, _ = harness(monkeypatch, files=files)
    assert result['code'] == 'runtime_replaced'
    assert 'PRIVATE' not in json.dumps(result)


def test_http_auth_failure_is_terminal_not_startup_retry(monkeypatch):
    import urllib.error
    def fetch(runtime, endpoint):
        raise urllib.error.HTTPError('http://127.0.0.1:17827/PRIVATE', 401, 'PRIVATE', {}, None)
    result, files, _, spawned, clock = harness(monkeypatch, fetch=fetch)
    assert result['code'] == 'local_api_http_failure'
    assert clock.seconds == 0 and len(spawned) == 1
    assert 'PRIVATE' not in json.dumps(result)


def test_partial_acl_failure_reports_attempt_without_claiming_success(monkeypatch):
    files = Files(plan())
    def fail(root):
        raise PermissionError('PRIVATE_PATH')
    files.harden_capture = fail
    result, _, _, spawned, _ = harness(monkeypatch, files=files)
    assert result['acl_change_attempted'] is True and result['acl_changed'] is False
    assert result['capture_requested'] is False and spawned == []


@pytest.mark.parametrize('mutate', [
    lambda value: value['provenance'].update(session_id='other'),
    lambda value: value['current_page_attributes'].update(snapshot_atomic=True),
    lambda value: value['current_page_attributes'].update(batch_id='other'),
    lambda value: value['current_page_attributes']['progress'].update(rows_received=34),
    lambda value: value.update(business_identity_known=True),
])
def test_api_provenance_tamper_rejected(monkeypatch, mutate):
    files = Files(plan())
    def fetch(runtime, endpoint):
        if endpoint == '/v1/status':
            return {'modelConfigured': False}
        value = envelope(plan(), files.request, Clock())
        mutate(value)
        return value
    result, _, _, _, _ = harness(monkeypatch, files=files, fetch=fetch)
    assert result['status'] == 'failed' and result['ai_answer_verified'] is False
