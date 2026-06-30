@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=src"
if "%AGENT_PORT%"=="" set "AGENT_PORT=8765"
set "AGENT_URL=http://127.0.0.1:%AGENT_PORT%/"

echo Starting Agent Workbench at %AGENT_URL%
echo Workspace: %CD%
start "" "%AGENT_URL%"
python -m agent.cli start --cwd "%CD%" --port %AGENT_PORT%

echo.
echo Agent Workbench stopped. Press any key to close this window.
pause >nul
