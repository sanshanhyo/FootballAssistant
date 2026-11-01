@echo off
setlocal
if "%~4"=="" goto usage
if not exist "%~1" (echo Test application not found.& exit /b 1)
if not exist "%~2\dotnet.exe" (echo Local .NET runtime not found.& exit /b 1)
if not exist "%~3" (echo Local calendar reader not found.& exit /b 1)
if not exist "%~4\settings.json" (echo Isolated profile settings.json not found.& exit /b 1)
set "FA_COMPANION_USER_DATA_DIR=%~f4"
set "FOOTBALL_ASSISTANT_RUNTIME_FILE="
set "FOOTBALL_ASSISTANT_DATA_DIR="
set "FOOTBALL_ASSISTANT_ENV_FILE="
set "FOOTBALL_ASSISTANT_PRIVATE_ROOT="
set "FOOTBALL_ASSISTANT_TOKEN="
set "FOOTBALL_ASSISTANT_API_KEY="
set "FOOTBALL_ASSISTANT_BASE_URL="
set "FOOTBALL_ASSISTANT_MODEL="
set "DOTNET_ROOT=%~f2"
set "FOOTBALL_ASSISTANT_OFFSEASON_EXE=%~f3"
start "" "%~f1"
exit /b 0
:usage
echo Usage: launch-calendar-trial.cmd ^<portable-exe^> ^<dotnet-directory^> ^<reader-exe^> ^<isolated-profile^>
exit /b 2
