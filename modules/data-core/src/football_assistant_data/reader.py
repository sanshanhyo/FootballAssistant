"""Standalone observation server. No companion, Agent or provider imports."""
from __future__ import annotations
from .app import create_app, serve
from .config import Settings
from .server_lock import writer_guard


def create_reader_app(settings: Settings | None = None):
    return create_app(settings or Settings.from_env(reader_only=True),enable_agent=False)


def main():
    try:
        serve(Settings.from_env(reader_only=True),enable_agent=False)
    except RuntimeError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
