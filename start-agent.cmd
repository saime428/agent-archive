@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=src"
if "%AGENT_PORT%"=="" set "AGENT_PORT=8000"

for /l %%P in (%AGENT_PORT%,1,8019) do (
  netstat -ano | findstr /R /C:":%%P .*LISTENING" >nul
  if errorlevel 1 (
    set "AGENT_PORT=%%P"
    goto found_port
  )
)

echo No free Agent Workbench port found from %AGENT_PORT% to 8019.
pause >nul
exit /b 1

:found_port
set "AGENT_URL=http://127.0.0.1:%AGENT_PORT%/"

echo Starting Agent Workbench at %AGENT_URL%
echo Workspace: %CD%
start "" "%AGENT_URL%"
python -m agent.cli start --cwd "%CD%" --port %AGENT_PORT%

echo.
echo Agent Workbench stopped. Press any key to close this window.
pause >nul
