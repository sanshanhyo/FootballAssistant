"""Launcher tests do not spawn a backend or desktop process."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("run_mvp", ROOT / "scripts" / "run_mvp.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def clean_env(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *args, **kwargs: {})
    for key in ("FOOTBALL_ASSISTANT_RUNTIME_FILE", "FOOTBALL_ASSISTANT_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)


def test_environment_uses_backend_default_not_package_directory(clean_env):
    environment = launcher.launch_environment()
    assert environment["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(ROOT / "local-data" / "runtime.json")


def test_explicit_environment_and_cli_paths(clean_env, monkeypatch, tmp_path):
    data = tmp_path / "data with spaces"
    runtime = tmp_path / "custom runtime.json"
    monkeypatch.setenv("FOOTBALL_ASSISTANT_DATA_DIR", str(data))
    assert launcher.launch_environment()["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(data / "runtime.json")
    monkeypatch.setenv("FOOTBALL_ASSISTANT_RUNTIME_FILE", str(runtime))
    assert launcher.launch_environment()["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(runtime)
    selected = tmp_path / "selected.json"
    assert launcher.launch_environment(str(selected))["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(selected)


def test_packaged_windows_receives_explicit_runtime(clean_env, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **options: calls.append((command, options)))
    environment = launcher.launch_environment()
    executable = tmp_path / "dist-alpha" / "win-unpacked" / "FootballAssistant.exe"
    launcher.launch_companion(executable, environment)
    assert calls[0][0] == [str(executable)]
    assert calls[0][1]["env"] == environment
    assert calls[0][1]["cwd"] == str(ROOT)


def test_backend_and_companion_receive_same_runtime(clean_env, monkeypatch):
    calls = []
    monkeypatch.setattr(launcher, "verify_runtime", lambda *args: None)
    states = iter([False, True])
    monkeypatch.setattr(launcher, "health_state", lambda _: next(states))
    monkeypatch.setattr(launcher, "open_backend_log", lambda: 123)
    monkeypatch.setattr(launcher.os, "close", lambda _: None)
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **options: calls.append((command, options)))
    environment = launcher.launch_environment()
    launcher.launch_backend("http://127.0.0.1:17827/health", environment)
    assert calls[0][1]["env"] == environment
    assert calls[0][0][-1] == "football-assistant-backend"


def test_existing_backend_is_not_restarted(clean_env, monkeypatch):
    monkeypatch.setattr(launcher, "verify_runtime", lambda *args: None)
    monkeypatch.setattr(launcher, "health_state", lambda _: True)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not restart"))
    launcher.launch_backend("http://127.0.0.1:17827/health", launcher.launch_environment())


def test_cli_accepts_alpha_package_and_runtime_override(clean_env, monkeypatch, tmp_path):
    executable = tmp_path / "dist-alpha" / "win-unpacked" / "FootballAssistant.exe"
    selected = tmp_path / "backend runtime.json"
    calls = []
    monkeypatch.setattr(launcher.sys, "argv", ["run_mvp.py", "--companion-path", str(executable), "--runtime-file", str(selected)])
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(launcher, "package_exists", lambda path: path == executable)
    monkeypatch.setattr(launcher, "launch_backend", lambda url, environment: calls.append(("backend", environment)))
    monkeypatch.setattr(launcher, "launch_companion", lambda path, environment: calls.append((path, environment)))
    assert launcher.main() == 0
    assert calls[1][0] == executable
    assert calls[0][1] == calls[1][1]
    assert calls[0][1]["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(selected)


def test_dotenv_paths_and_port_without_importing_model_credentials(clean_env, monkeypatch, tmp_path):
    import dotenv
    monkeypatch.delenv("FOOTBALL_ASSISTANT_PORT", raising=False)
    monkeypatch.delenv("FOOTBALL_ASSISTANT_API_KEY", raising=False)
    monkeypatch.setattr(dotenv, "dotenv_values", lambda _: {
        "FOOTBALL_ASSISTANT_DATA_DIR": str(tmp_path),
        "FOOTBALL_ASSISTANT_PORT": "17829",
        "FOOTBALL_ASSISTANT_API_KEY": "test-only-secret",
    })
    environment = launcher.launch_environment()
    assert environment["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(tmp_path / "runtime.json")
    assert launcher.backend_url(environment) == "http://127.0.0.1:17829/health"
    assert "FOOTBALL_ASSISTANT_API_KEY" not in environment
    assert "FOOTBALL_ASSISTANT_API_KEY" not in launcher.os.environ
    monkeypatch.setenv("FOOTBALL_ASSISTANT_PORT", "17830")
    assert launcher.backend_url(launcher.launch_environment()) == "http://127.0.0.1:17830/health"


def test_relative_backend_configuration_is_root_relative_from_other_cwd(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FOOTBALL_ASSISTANT_DATA_DIR", "relative-data")
    assert launcher.launch_environment()["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(ROOT / "relative-data/runtime.json")
    monkeypatch.setenv("FOOTBALL_ASSISTANT_RUNTIME_FILE", "relative/runtime.json")
    assert launcher.launch_environment()["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(ROOT / "relative/runtime.json")
    assert launcher.launch_environment("explicit.json")["FOOTBALL_ASSISTANT_RUNTIME_FILE"] == str(tmp_path / "explicit.json")


def test_healthy_backend_with_missing_runtime_does_not_launch(clean_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(launcher.sys, "argv", ["run_mvp.py", "--companion-path", str(tmp_path / "FootballAssistant.exe"), "--runtime-file", str(tmp_path / "missing.json")])
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(launcher, "package_exists", lambda _: True)
    monkeypatch.setattr(launcher, "health_state", lambda _: True)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not launch anything"))
    assert launcher.main() == 1
    output = capsys.readouterr()
    assert "selected runtime file" in output.err
    assert "Opened" not in output.out


@pytest.mark.parametrize("base_url,token", [("http://127.0.0.1:17828", "a" * 32), ("https://example.com", "a" * 32), ("http://127.0.0.1:17827", "short")])
def test_wrong_or_unsafe_runtime_never_contacts_service(clean_env, monkeypatch, tmp_path, base_url, token):
    import json
    from football_assistant_data.reader_client import ReaderClient
    selected = tmp_path / "runtime.json"
    selected.write_text(json.dumps({"base_url": base_url, "token": token}), encoding="utf-8")
    monkeypatch.setattr(ReaderClient, "get", lambda *args: pytest.fail("must not send token"))
    with pytest.raises(RuntimeError, match="selected runtime file"):
        launcher.verify_runtime("http://127.0.0.1:17827/health", launcher.launch_environment(str(selected)))


def test_matching_runtime_requires_authenticated_read_only_status(clean_env, monkeypatch, tmp_path):
    import json
    from football_assistant_data.reader_client import ReaderClient, ReaderError
    selected = tmp_path / "runtime.json"
    selected.write_text(json.dumps({"base_url": "http://127.0.0.1:17827", "token": "a" * 32}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(ReaderClient, "get", lambda self, endpoint: calls.append((self.runtime_file, endpoint)))
    environment = launcher.launch_environment(str(selected))
    launcher.verify_runtime("http://127.0.0.1:17827/health", environment)
    assert calls == [(selected, "/v1/status")]
    def rejected(*args):
        raise ReaderError("http_401", "test auth rejected")
    monkeypatch.setattr(ReaderClient, "get", rejected)
    with pytest.raises(RuntimeError, match="cannot authenticate"):
        launcher.verify_runtime("http://127.0.0.1:17827/health", environment)


def test_bridge_root_is_explicit_and_can_be_persisted_in_env_config(clean_env, monkeypatch, tmp_path):
    import dotenv
    monkeypatch.delenv('FOOTBALL_ASSISTANT_PRIVATE_ROOT', raising=False)
    assert 'FOOTBALL_ASSISTANT_PRIVATE_ROOT' not in launcher.launch_environment()
    configured = tmp_path / 'private bridge'
    monkeypatch.setattr(dotenv, 'dotenv_values', lambda *args, **kwargs: {'FOOTBALL_ASSISTANT_PRIVATE_ROOT': str(configured)})
    assert launcher.launch_environment()['FOOTBALL_ASSISTANT_PRIVATE_ROOT'] == str(configured)
    selected = tmp_path / 'explicit'
    assert launcher.launch_environment(bridge_private_root=str(selected))['FOOTBALL_ASSISTANT_PRIVATE_ROOT'] == str(selected)
    link = tmp_path / 'linked'
    link.symlink_to(configured)
    assert launcher.launch_environment(bridge_private_root=str(link))['FOOTBALL_ASSISTANT_PRIVATE_ROOT'] == str(link)


def test_double_click_mvp_entry_reuses_frozen_launcher_without_game_or_secrets():
    entry = ROOT / 'scripts' / 'MVP.command'
    text = entry.read_text(encoding='utf-8')
    assert 'uv run --frozen --extra save --extra agent python scripts/run_mvp.py "$@"' in text
    assert 'launch_isolated.py' not in text and '--launch' not in text
    assert 'API_KEY' not in text and 'runtime.json' not in text
    assert '此入口不启动或修改游戏' in text


def test_missing_model_configuration_warns_without_printing_status_secrets(clean_env, monkeypatch, tmp_path, capsys):
    import json
    from football_assistant_data.reader_client import ReaderClient
    selected = tmp_path / 'runtime.json'
    selected.write_text(json.dumps({'base_url': 'http://127.0.0.1:17827', 'token': 'TEST-private-token'}))
    monkeypatch.setattr(ReaderClient, 'get', lambda *args: {'modelConfigured': False, 'unexpected_secret': 'TEST-DO-NOT-PRINT'})
    launcher.verify_runtime('http://127.0.0.1:17827/health', launcher.launch_environment(str(selected)))
    output = capsys.readouterr()
    assert '模型尚未配置' in output.err
    assert 'TEST-DO-NOT-PRINT' not in output.err and 'TEST-private-token' not in output.err


def test_double_click_wrapper_uses_project_cwd_and_arguments_without_launching_real_services(tmp_path):
    import os
    import shutil
    import subprocess
    zsh = shutil.which('zsh')
    if not zsh:
        pytest.skip('zsh is needed only for the macOS wrapper test')
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    uv = bin_dir / 'uv'
    uv.write_text('#!/bin/sh\nprintf "TEST_CWD=%s\\n" "$PWD"\nprintf "TEST_ARG=%s\\n" "$@"\n')
    uv.chmod(0o700)
    result = subprocess.run([zsh, str(ROOT / 'scripts/MVP.command'), '--check'], cwd=tmp_path,
        env={**os.environ, 'PATH': str(bin_dir), 'HOME': str(tmp_path)}, text=True, capture_output=True, check=True)
    assert f'TEST_CWD={ROOT}' in result.stdout
    assert 'TEST_ARG=scripts/run_mvp.py' in result.stdout
    assert 'TEST_ARG=--check' in result.stdout
    assert 'TEST_ARG=--launch' not in result.stdout
    uv.unlink()
    result = subprocess.run([zsh, str(ROOT / 'scripts/MVP.command')], cwd=tmp_path,
        env={**os.environ, 'PATH': str(bin_dir), 'HOME': str(tmp_path)}, text=True, capture_output=True)
    assert result.returncode == 1 and '需要先安装 uv' in result.stderr
