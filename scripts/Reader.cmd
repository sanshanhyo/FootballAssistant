@echo off
cd /d "%~dp0.."
set "UV_PROJECT_ENVIRONMENT=%CD%\.venv-reader"
uv run --frozen python scripts\launch_reader.py
if errorlevel 1 pause
