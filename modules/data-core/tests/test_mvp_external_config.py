"""Explicit local config fixtures only; no provider, real runtime, or desktop launch."""
import os
from pathlib import Path
import pytest
from test_mvp_launcher import launcher


@pytest.fixture
def isolated_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(('FOOTBALL_ASSISTANT_', 'UV_ENV_FILE')):
            monkeypatch.delenv(key)


def config(root, name, key):
    directory = root / name; directory.mkdir()
    file = directory / 'local.env'
    file.write_text(f'FOOTBALL_ASSISTANT_API_KEY={key}\nFOOTBALL_ASSISTANT_MODEL=TEST-model\n'
        'FOOTBALL_ASSISTANT_BASE_URL=https://TEST.invalid/v1\nFOOTBALL_ASSISTANT_DATA_DIR=private-data\n'
        'FOOTBALL_ASSISTANT_PRIVATE_ROOT=bridge\n')
    return file


def test_two_explicit_configs_keep_separate_data_and_backend_credentials_without_copying(isolated_env, tmp_path):
    first = config(tmp_path, 'first', 'TEST-secret-first')
    second = config(tmp_path, 'second', 'TEST-secret-second')
    for file, key in [(first, 'TEST-secret-first'), (second, 'TEST-secret-second')]:
        env = launcher.launch_environment(env_file=str(file))
        assert env['FOOTBALL_ASSISTANT_API_KEY'] == key
        assert env['FOOTBALL_ASSISTANT_DATA_DIR'] == str(file.parent / 'private-data')
        assert env['FOOTBALL_ASSISTANT_RUNTIME_FILE'] == str(file.parent / 'private-data/runtime.json')
        assert env['FOOTBALL_ASSISTANT_PRIVATE_ROOT'] == str(file.parent / 'bridge')
        assert not (file.parent / 'private-data').exists()  # No migration or config copy.
        safe = launcher.companion_environment(env)
        assert safe['FOOTBALL_ASSISTANT_RUNTIME_FILE'] == env['FOOTBALL_ASSISTANT_RUNTIME_FILE']
        assert all(not k.startswith('FOOTBALL_ASSISTANT_') or k == 'FOOTBALL_ASSISTANT_RUNTIME_FILE' for k in safe)
        assert key not in str(safe)


def test_explicit_cli_data_and_runtime_paths_use_caller_cwd_not_config_directory(isolated_env, tmp_path, monkeypatch):
    file = config(tmp_path, 'config', 'TEST-secret')
    caller = tmp_path / 'caller'; caller.mkdir(); monkeypatch.chdir(caller)
    env = launcher.launch_environment(env_file=str(file), data_dir='chosen-data')
    assert env['FOOTBALL_ASSISTANT_DATA_DIR'] == str(caller / 'chosen-data')
    assert env['FOOTBALL_ASSISTANT_RUNTIME_FILE'] == str(caller / 'chosen-data/runtime.json')
    env = launcher.launch_environment(env_file=str(file), data_dir='chosen-data', runtime_file='chosen-runtime.json')
    assert env['FOOTBALL_ASSISTANT_RUNTIME_FILE'] == str(caller / 'chosen-runtime.json')


def test_missing_explicit_file_never_falls_back_or_launches(isolated_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher.sys, 'argv', ['run_mvp.py', '--env-file', str(tmp_path / 'missing.env'), '--companion-path', str(tmp_path / 'app')])
    monkeypatch.setattr(launcher, 'launch_backend', lambda *args: pytest.fail('must not launch'))
    assert launcher.main() == 1
    assert 'no other configuration was searched' in capsys.readouterr().err


def test_companion_allowlist_drops_known_and_arbitrary_ambient_secrets(isolated_env):
    env = {'HOME': '/TEST-home', 'PATH': '/TEST-bin', 'FOOTBALL_ASSISTANT_RUNTIME_FILE': '/TEST-runtime.json',
        'FOOTBALL_ASSISTANT_API_KEY': 'TEST-secret', 'OPENAI_API_KEY': 'TEST-secret', 'ANTHROPIC_API_KEY': 'TEST-secret',
        'AWS_SECRET_ACCESS_KEY': 'TEST-secret', 'CUSTOM_PRIVATE_TOKEN': 'TEST-secret', 'UV_ENV_FILE': '/TEST-private.env',
        'FOOTBALL_ASSISTANT_MODEL': 'TEST-model', 'FOOTBALL_ASSISTANT_TOKEN': 'TEST-secret'}
    safe = launcher.companion_environment(env)
    assert safe == {key: env[key] for key in ('HOME', 'PATH', 'FOOTBALL_ASSISTANT_RUNTIME_FILE')}


def test_start_backend_gets_external_config_but_companion_does_not(isolated_env, tmp_path, monkeypatch):
    file = config(tmp_path, 'config', 'TEST-secret')
    env = launcher.launch_environment(env_file=str(file))
    calls = []
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda command, **kwargs: calls.append((command, kwargs)))
    monkeypatch.setattr(launcher.sys, 'platform', 'darwin')
    states = iter([False, True]); monkeypatch.setattr(launcher, 'health_state', lambda url: next(states))
    monkeypatch.setattr(launcher, 'verify_runtime', lambda *args: None)
    monkeypatch.setattr(launcher, 'open_backend_log', lambda: 123)
    monkeypatch.setattr(launcher.os, 'close', lambda fd: None)
    launcher.launch_backend('http://127.0.0.1:17827/health', env)
    launcher.launch_companion(tmp_path / 'TEST.app', env)
    assert calls[0][1]['env']['FOOTBALL_ASSISTANT_API_KEY'] == 'TEST-secret'
    assert 'TEST-secret' not in str(calls[1])
    assert calls[1][0][-1] == env['FOOTBALL_ASSISTANT_RUNTIME_FILE']


def test_explicit_empty_config_does_not_fall_back_to_candidate_dotenv(isolated_env, tmp_path, monkeypatch):
    from football_assistant_data import config as backend_config
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    (candidate / '.env').write_text('FOOTBALL_ASSISTANT_API_KEY=TEST-WRONG-ROOT\nFOOTBALL_ASSISTANT_MODEL=TEST-WRONG-MODEL\n')
    external = tmp_path / 'explicit.env'; external.write_text('# deliberately unconfigured\n')
    monkeypatch.setattr(backend_config, 'ROOT', candidate)
    env = launcher.launch_environment(env_file=str(external))
    for key, value in env.items():
        if key.startswith('FOOTBALL_ASSISTANT_'): monkeypatch.setenv(key, value)
    settings = backend_config.Settings.from_env()
    assert settings.api_key == '' and settings.model == ''
    assert settings.data_dir == tmp_path / 'local-data'
    external.unlink()
    with pytest.raises(ValueError, match='no fallback'):
        backend_config.Settings.from_env()


def test_explicit_relative_runtime_and_environment_precedence_are_documented_behavior(isolated_env, tmp_path, monkeypatch):
    file = config(tmp_path, 'config', 'TEST-file-secret')
    with file.open('a') as target: target.write('FOOTBALL_ASSISTANT_RUNTIME_FILE=connections/runtime.json\n')
    monkeypatch.setenv('FOOTBALL_ASSISTANT_API_KEY', 'TEST-explicit-environment-secret')
    env = launcher.launch_environment(env_file=str(file), data_dir=str(tmp_path / 'explicit-data'))
    assert env['FOOTBALL_ASSISTANT_API_KEY'] == 'TEST-explicit-environment-secret'
    assert env['FOOTBALL_ASSISTANT_DATA_DIR'] == str(tmp_path / 'explicit-data')
    assert env['FOOTBALL_ASSISTANT_RUNTIME_FILE'] == str(file.parent / 'connections/runtime.json')


def test_cli_external_configuration_reaches_normal_start_path_without_printing_credentials(isolated_env, tmp_path, monkeypatch, capsys):
    file = config(tmp_path, 'config', 'TEST-CLI-SECRET')
    app = tmp_path / 'TEST.app'; data = tmp_path / 'existing-data'
    monkeypatch.setattr(launcher.sys, 'argv', ['run_mvp.py', '--env-file', str(file), '--data-dir', str(data), '--companion-path', str(app)])
    monkeypatch.setattr(launcher.sys, 'platform', 'darwin')
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: '/TEST/uv')
    monkeypatch.setattr(launcher, 'package_exists', lambda path: path == app)
    backend = []; processes = []
    monkeypatch.setattr(launcher, 'launch_backend', lambda url, env: backend.append(env))
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda command, **kwargs: processes.append((command, kwargs)))
    assert launcher.main() == 0
    assert backend[0]['FOOTBALL_ASSISTANT_API_KEY'] == 'TEST-CLI-SECRET'
    assert backend[0]['FOOTBALL_ASSISTANT_DATA_DIR'] == str(data)
    assert processes[0][0][-1] == str(data / 'runtime.json')
    assert 'TEST-CLI-SECRET' not in str(processes)
    output = capsys.readouterr()
    assert 'TEST-CLI-SECRET' not in output.out + output.err
