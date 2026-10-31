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
        ReaderClient(runtime_file, timeout=1.5).get("/v1/status")
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


def launch_companion(path: Path, environment: dict[str, str]) -> None:
    if sys.platform == "darwin":
        command = ["open", "-a", str(path), "--args", "--runtime-file", environment["FOOTBALL_ASSISTANT_RUNTIME_FILE"]]
    else:
        command = [str(path)]
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    print("Opened the FootballAssistant desktop companion.")


def launch_environment(runtime_file: str | None = None) -> dict[str, str]:
    # Match backend path precedence without importing model secrets from .env into Electron.
    from dotenv import dotenv_values

    values = dotenv_values(ROOT / ".env")
    environment = dict(os.environ)
    for key in ("FOOTBALL_ASSISTANT_DATA_DIR", "FOOTBALL_ASSISTANT_RUNTIME_FILE", "FOOTBALL_ASSISTANT_PORT"):
        if key not in environment and values.get(key) is not None:
            environment[key] = values[key]
    def backend_path(value: str | Path) -> Path:
        expanded = Path(value).expanduser()
        return (ROOT / expanded).resolve()  # Child backend always runs with cwd=ROOT.

    data_dir = backend_path(environment.get("FOOTBALL_ASSISTANT_DATA_DIR", ROOT / "local-data"))
    # CLI paths belong to the invoking shell; environment/.env paths belong to backend cwd.
    selected = Path(runtime_file).expanduser().resolve() if runtime_file else backend_path(
        environment.get("FOOTBALL_ASSISTANT_RUNTIME_FILE", data_dir / "runtime.json"))
    return {**environment, "FOOTBALL_ASSISTANT_DATA_DIR": str(data_dir),
            "FOOTBALL_ASSISTANT_RUNTIME_FILE": str(selected)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local FootballAssistant MVP.")
    parser.add_argument("--check", action="store_true", help="Check the package, uv, and backend without starting anything.")
    parser.add_argument("--companion-path", type=Path, help="Explicit built .exe or .app (for example, dist-alpha/win-unpacked/FootballAssistant.exe).")
    parser.add_argument("--runtime-file", help="Explicit backend runtime file; otherwise use backend environment/.env configuration.")
    args = parser.parse_args()

    try:
        app_path = args.companion_path.expanduser().resolve() if args.companion_path else companion_path()
        environment = launch_environment(args.runtime_file)
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

    try:
        launch_backend(url, environment)
        launch_companion(app_path, environment)
    except (OSError, RuntimeError) as error:
        print(f"Could not launch FootballAssistant MVP: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
