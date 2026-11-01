"""Local configuration. Never print credentials or borrow other projects' settings."""
from __future__ import annotations

import os
import sys
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path.cwd() if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runtime_file: Path
    port: int = 17827
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    model_timeout: float = 45.0
    max_output_tokens: int = 180
    model_extra_body: dict = field(default_factory=dict)
    model_request_limit: int = 0
    model_budget_id: str = "default"
    runtime_stale_seconds: float = 10
    runtime_disconnect_seconds: float = 30
    stale_seconds: int = 300
    max_request_bytes: int = 131072
    bridge_private_root: Path | None = None
    persona_file: Path | None = None
    windows_finite_registration: dict | None = None

    @property
    def model_configured(self) -> bool:
        return all((self.base_url, self.model, self.api_key))

    @classmethod
    def from_env(cls, *, reader_only: bool = False) -> "Settings":
        if not reader_only:
            explicit_env = os.environ.get("FOOTBALL_ASSISTANT_ENV_FILE")
            selected_env = Path(explicit_env).expanduser() if explicit_env else ROOT / ".env"
            if explicit_env and not selected_env.is_file():
                raise ValueError("The explicitly selected backend dotenv file is missing; no fallback was loaded.")
            if explicit_env or os.environ.get("FOOTBALL_ASSISTANT_DESKTOP") != "1":
                load_dotenv(selected_env, override=False)
        data_dir = Path(os.environ.get("FOOTBALL_ASSISTANT_DATA_DIR", ROOT / "local-data")).expanduser().resolve()
        runtime_file = Path(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_FILE", data_dir / "runtime.json")).expanduser().resolve()
        configured_root = os.environ.get('FOOTBALL_ASSISTANT_PRIVATE_ROOT')
        bridge_private_root = Path(configured_root).expanduser().absolute() if configured_root else None
        finite_raw = os.environ.get('FOOTBALL_ASSISTANT_WINDOWS_FINITE_REGISTRATION')
        finite_registration = None
        if finite_raw:
            from .windows_finite_observations import registration
            from .windows_discovery_import import _unique_object
            if not bridge_private_root or len(finite_raw) > 2048:
                raise ValueError('Finite source requires an explicit approved private root')
            finite_registration = registration(json.loads(finite_raw, object_pairs_hook=_unique_object))
        port = int(os.environ.get("FOOTBALL_ASSISTANT_PORT", "17827"))
        if not 1 <= port <= 65535:
            raise ValueError("FOOTBALL_ASSISTANT_PORT must be 1..65535")
        if reader_only:
            # Independent reader needs no .env or model configuration.
            return cls(data_dir=data_dir,runtime_file=runtime_file,port=port,bridge_private_root=bridge_private_root,windows_finite_registration=finite_registration,
                       token=os.environ.get("FOOTBALL_ASSISTANT_TOKEN") or secrets.token_urlsafe(32),
                       runtime_stale_seconds=float(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_STALE_SECONDS","10")),
                       runtime_disconnect_seconds=float(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_DISCONNECT_SECONDS","30")))
        return cls(
            data_dir=data_dir, runtime_file=runtime_file, port=port, bridge_private_root=bridge_private_root, windows_finite_registration=finite_registration,
            persona_file=Path(os.environ["FOOTBALL_ASSISTANT_PERSONA_FILE"]).expanduser().absolute() if os.environ.get("FOOTBALL_ASSISTANT_PERSONA_FILE") else None,
            token=os.environ.get("FOOTBALL_ASSISTANT_TOKEN") or secrets.token_urlsafe(32),
            base_url=os.environ.get("FOOTBALL_ASSISTANT_BASE_URL", "").strip(),
            model=os.environ.get("FOOTBALL_ASSISTANT_MODEL", "").strip(),
            api_key=os.environ.get("FOOTBALL_ASSISTANT_API_KEY", "").strip(),
            model_timeout=float(os.environ.get("FOOTBALL_ASSISTANT_MODEL_TIMEOUT", "45")),
            max_output_tokens=int(os.environ.get("FOOTBALL_ASSISTANT_MAX_OUTPUT_TOKENS", "180")),
            model_extra_body=json.loads(os.environ.get("FOOTBALL_ASSISTANT_MODEL_EXTRA_BODY", "{}")),
            model_request_limit=int(os.environ.get("FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT", "0")),
            model_budget_id=os.environ.get("FOOTBALL_ASSISTANT_MODEL_BUDGET_ID", "default"),
            runtime_stale_seconds=float(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_STALE_SECONDS", "10")),
            runtime_disconnect_seconds=float(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_DISCONNECT_SECONDS", "30")),
        )
