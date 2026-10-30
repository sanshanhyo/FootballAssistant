#!/bin/zsh
set -eu
cd -- "${0:A:h:h}"
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-reader"
exec uv run --frozen python scripts/launch_reader.py
