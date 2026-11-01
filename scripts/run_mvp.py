#!/usr/bin/env python3
"""Launch the existing local backend and the already-built companion package."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAC_APP = ROOT / "apps" / "companion" / "dist" / "mac-arm64" / "FootballAssistant.app"
WINDOWS_APP = ROOT / "apps" / "companion" / "dist" / "win-unpacked" / "FootballAssistant.exe"


def backend_url(environment: dict[str, str] | None = None) -> str:
    environment = os.environ if environment is None else environment
    try:
        port = int(environment.get("FOOTBALL_ASSISTANT_PORT", "17827"))
    except ValueError:
        raise RuntimeError("FOOTBALL_ASSISTANT_PORT must be a valid port number.") from None
    if not 1 <= port <= 65535:
        raise RuntimeError("FOOTBALL_ASSISTANT_PORT must be between 1 and 65535.")
    return f"http://127.0.0.1:{port}/health"


def companion_path() -> Path:
    if sys.platform == "darwin":
        return MAC_APP
    if sys.platform == "win32":
        return WINDOWS_APP
    raise RuntimeError("The MVP desktop package is available for macOS and Windows only.")


def package_exists(path: Path) -> bool:
    if sys.platform == "darwin":
        return path.is_dir() and (path / "Contents" / "MacOS" / "FootballAssistant").is_file()
    return path.is_file()


def health_state(url: str) -> bool | None:
    """True for our backend, False when closed, None for another service on its port."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            import json

            payload = json.loads(response.read(4096))
        if payload.get("service") == "football-assistant" and payload.get("status") == "ok":
            return True
        return None
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        return False
    except (ValueError, AttributeError):
        return None


def required_items(app_path: Path, url: str) -> list[str]:
    issues = []
    if shutil.which("uv") is None:
        issues.append("uv was not found; install uv to launch the local Python service.")
    if not (ROOT / "uv.lock").is_file():
        issues.append("uv.lock is missing; run uv lock from the repository root first.")
    if not package_exists(app_path):
        if sys.platform == "darwin":
            issues.append(
                "macOS companion package is missing; build it with "
                "cd apps/companion && npm ci && npm run pack:mac."
            )
        else:
            issues.append(
                "Windows x64 companion package is missing; build it with "
                "cd apps/companion && npm ci && npm run pack:win."
            )
    if health_state(url) is not True:
        issues.append("the FootballAssistant backend is not healthy on the configured loopback port.")
    return issues


def open_backend_log() -> int:
    data_dir = ROOT / "local-data"
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_info = data_dir.lstat()
    if not stat.S_ISDIR(directory_info.st_mode):
        raise RuntimeError("local-data must be a private directory, not a link or special file.")
    if os.name != "nt":
        if directory_info.st_uid != os.getuid():
            raise RuntimeError("local-data must be owned by the current user.")
        os.chmod(data_dir, 0o700)

    log_path = data_dir / "backend.log"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(log_path, flags, 0o600)
    try:
        log_info = os.fstat(descriptor)
        if not stat.S_ISREG(log_info.st_mode):
            raise RuntimeError("local-data/backend.log must be a regular file.")
        if os.name != "nt":
            if log_info.st_uid != os.getuid():
                raise RuntimeError("local-data/backend.log must be owned by the current user.")
            os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def verify_runtime(url: str, environment: dict[str, str]) -> None:
    """Verify only the selected file and authenticated read-only status; never guess paths."""
    from football_assistant_data.reader_client import ReaderClient, ReaderError, runtime_address

    runtime_file = Path(environment["FOOTBALL_ASSISTANT_RUNTIME_FILE"])
    try:
        if not runtime_file.is_file() or runtime_file.stat().st_size > 16_384:
            raise ValueError("Invalid runtime file")
        value = json.loads(runtime_file.read_text(encoding="utf-8"))
        if runtime_address(value) + "/health" != url:
            raise ValueError("Runtime address does not match configured backend")
        if not isinstance(value.get("token"), str) or len(value["token"]) < 16:
            raise ValueError("Invalid runtime token")
        status = ReaderClient(runtime_file, timeout=1.5).get("/v1/status")
        if isinstance(status, dict) and status.get("modelConfigured") is False:
            print("本机服务已连接，但模型尚未配置；请在本机 .env 配置服务地址、模型名和密钥后重启后端。此时不能生成建议。", file=sys.stderr)
    except (OSError, ValueError, TypeError, AttributeError, ReaderError):
        raise RuntimeError(
            "The selected runtime file is missing, invalid, or cannot authenticate to the configured backend. "
            "Use --runtime-file for that backend's runtime.json (and matching FOOTBALL_ASSISTANT_PORT). "
            "No companion was opened; the existing service was left untouched."
        ) from None


def launch_backend(url: str, environment: dict[str, str]) -> None:
    state = health_state(url)
    if state is True:
        verify_runtime(url, environment)
        print("Reusing the healthy local FootballAssistant backend.")
        return
    if state is None:
        raise RuntimeError("The configured loopback port responds with a different service; leaving it untouched.")

    command = ["uv", "run", "--frozen", "--extra", "save", "--extra", "agent", "football-assistant-backend"]
    log_descriptor = open_backend_log()
    try:
        options: dict[str, object] = {
            "cwd": str(ROOT),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": log_descriptor,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if sys.platform == "win32":
            options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)
    finally:
        os.close(log_descriptor)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = health_state(url)
        if state is True:
            verify_runtime(url, environment)
            print("Started the local FootballAssistant backend.")
            return
        if state is None:
            raise RuntimeError("The loopback port was taken by a different service; leaving it untouched.")
        time.sleep(0.4)
    raise RuntimeError("The local backend did not become healthy within 30 seconds; it was not stopped.")


def companion_environment(environment: dict[str, str]) -> dict[str, str]:
    # Positive allowlist: never propagate provider keys, model configuration, uv dotenv
    # settings, arbitrary inherited secrets, or private bridge controls into Electron.
    ordinary = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TMP", "TEMP",
        "LANG", "LC_ALL", "LC_CTYPE", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
        "XDG_CACHE_HOME", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "APPDATA",
        "LOCALAPPDATA", "USERPROFILE", "ALLUSERSPROFILE", "__CF_USER_TEXT_ENCODING",
        "FA_COMPANION_USER_DATA_DIR", "FOOTBALL_ASSISTANT_RUNTIME_FILE"}
    return {key: value for key, value in environment.items() if key in ordinary}


def launch_companion(path: Path, environment: dict[str, str]) -> None:
    if sys.platform == "darwin":
        command = ["open", "-a", str(path), "--args", "--runtime-file", environment["FOOTBALL_ASSISTANT_RUNTIME_FILE"]]
    else:
        command = [str(path)]
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=companion_environment(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    print("Opened the FootballAssistant desktop companion.")


def launch_environment(runtime_file: str | None = None, bridge_private_root: str | None = None,
                       env_file: str | None = None, data_dir: str | None = None) -> dict[str, str]:
    from dotenv import dotenv_values

    configuration = Path(env_file).expanduser().absolute() if env_file else ROOT / ".env"
    if env_file:
        try:
            if not configuration.is_file() or configuration.stat().st_size > 65_536:
                raise OSError("invalid config")
        except OSError:
            raise RuntimeError("The explicitly selected dotenv file is missing, unreadable, or too large; no other configuration was searched.") from None
    try:
        values = dotenv_values(configuration)
    except (OSError, UnicodeError):
        raise RuntimeError("The selected dotenv file could not be read; no configuration values were printed.") from None
    environment = dict(os.environ)
    if env_file:
        environment["FOOTBALL_ASSISTANT_ENV_FILE"] = str(configuration)
    config_keys = ("FOOTBALL_ASSISTANT_DATA_DIR", "FOOTBALL_ASSISTANT_RUNTIME_FILE", "FOOTBALL_ASSISTANT_PORT", "FOOTBALL_ASSISTANT_PRIVATE_ROOT")
    if env_file:
        config_keys += ("FOOTBALL_ASSISTANT_BASE_URL", "FOOTBALL_ASSISTANT_MODEL", "FOOTBALL_ASSISTANT_API_KEY",
            "FOOTBALL_ASSISTANT_TOKEN", "FOOTBALL_ASSISTANT_MODEL_TIMEOUT", "FOOTBALL_ASSISTANT_MAX_OUTPUT_TOKENS",
            "FOOTBALL_ASSISTANT_MODEL_EXTRA_BODY", "FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT", "FOOTBALL_ASSISTANT_MODEL_BUDGET_ID",
            "FOOTBALL_ASSISTANT_RUNTIME_STALE_SECONDS", "FOOTBALL_ASSISTANT_RUNTIME_DISCONNECT_SECONDS")
    for key in config_keys:
        if key not in environment and values.get(key) is not None:
            environment[key] = values[key]
    # Explicit env files define the base of configuration-relative paths. CLI paths
    # retain caller-cwd semantics; no config-file search or implicit database migration.
    base = configuration.parent if env_file else ROOT
    def backend_path(value: str | Path) -> Path:
        return (base / Path(value).expanduser()).resolve()

    selected_data = Path(data_dir).expanduser().resolve() if data_dir else backend_path(
        environment.get("FOOTBALL_ASSISTANT_DATA_DIR", base / "local-data"))
    selected_runtime = Path(runtime_file).expanduser().resolve() if runtime_file else backend_path(
        environment.get("FOOTBALL_ASSISTANT_RUNTIME_FILE", selected_data / "runtime.json"))
    configured_root = bridge_private_root or environment.get("FOOTBALL_ASSISTANT_PRIVATE_ROOT")
    if configured_root:
        # Preserve symlinks for the controller to reject; never resolve them away.
        candidate = Path(configured_root).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() if bridge_private_root else base) / candidate
        environment["FOOTBALL_ASSISTANT_PRIVATE_ROOT"] = str(candidate.absolute())
    return {**environment, "FOOTBALL_ASSISTANT_DATA_DIR": str(selected_data),
            "FOOTBALL_ASSISTANT_RUNTIME_FILE": str(selected_runtime)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local FootballAssistant MVP.")
    parser.add_argument("--check", action="store_true", help="Check the package, uv, and backend without starting anything.")
    parser.add_argument("--companion-path", type=Path, help="Explicit built .exe or .app (for example, dist-alpha/win-unpacked/FootballAssistant.exe).")
    parser.add_argument("--runtime-file", help="Explicit backend runtime file; otherwise use backend environment/.env configuration.")
    parser.add_argument("--bridge-private-root", help="Explicit existing private bridge directory; otherwise use FOOTBALL_ASSISTANT_PRIVATE_ROOT from environment/.env. Never auto-discovered.")
    parser.add_argument("--env-file", help="Explicit existing local dotenv file for backend configuration; never copied into the package.")
    parser.add_argument("--data-dir", help="Explicit backend data directory (relative to invoking cwd); no files are migrated.")
    args = parser.parse_args()

    try:
        app_path = args.companion_path.expanduser().resolve() if args.companion_path else companion_path()
        environment = launch_environment(args.runtime_file, args.bridge_private_root, args.env_file, args.data_dir)
        url = backend_url(environment)
    except (RuntimeError, ValueError) as error:
        print(f"MVP check failed: {error}", file=sys.stderr)
        return 1

    if args.check:
        issues = required_items(app_path, url)
        if not issues:
            try:
                verify_runtime(url, environment)
            except RuntimeError as error:
                issues.append(str(error))
        if issues:
            for issue in issues:
                print(f"- {issue}", file=sys.stderr)
            return 1
        print("MVP prerequisites are present: packaged desktop app, uv, and healthy local backend.")
        return 0

    if shutil.which("uv") is None:
        print("Cannot start the backend: uv was not found.", file=sys.stderr)
        return 1
    if not (ROOT / "uv.lock").is_file():
        print("Cannot start the backend: uv.lock is missing.", file=sys.stderr)
        return 1
    if not package_exists(app_path):
        print(required_items(app_path, url)[0] if shutil.which("uv") is not None else "Desktop package is missing.", file=sys.stderr)
        return 1

    if not environment.get("FOOTBALL_ASSISTANT_PRIVATE_ROOT"):
        print("此启动环境未配置 FOOTBALL_ASSISTANT_PRIVATE_ROOT；新启动的后端无法控制页面读取。请填写已准备好的本机桥接目录；不会自动安装或启动游戏。", file=sys.stderr)
    if sys.platform == "win32":
        print("Windows 桌宠仅有 UI 验证；当前游戏页面采集控制不受支持，不代表端到端游戏读取可用。", file=sys.stderr)
    try:
        launch_backend(url, environment)
        launch_companion(app_path, environment)
    except (OSError, RuntimeError) as error:
        print(f"Could not launch FootballAssistant MVP: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
