@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=src"
if "%AGENT_PORT%"=="" set "AGENT_PORT=8000"
set /a AGENT_PORT_END=%AGENT_PORT%+19
set "AGENT_LOG=%~dp0.agent\start-agent.log"

if not exist "%~dp0.agent" mkdir "%~dp0.agent"
echo [%DATE% %TIME%] Starting Agent Workbench > "%AGENT_LOG%"
echo Workspace: %CD%>> "%AGENT_LOG%"
where python >> "%AGENT_LOG%" 2>&1
python --version >> "%AGENT_LOG%" 2>&1

for /l %%P in (%AGENT_PORT%,1,%AGENT_PORT_END%) do (
  netstat -ano | findstr /R /C:":%%P .*LISTENING" >nul
  if errorlevel 1 (
    set "AGENT_PORT=%%P"
    goto found_port
  )
)

echo No free Agent Workbench port found from %AGENT_PORT% to %AGENT_PORT_END%.
echo No free Agent Workbench port found from %AGENT_PORT% to %AGENT_PORT_END%.>> "%AGENT_LOG%"
pause >nul
exit /b 1

:found_port
set "AGENT_URL=http://127.0.0.1:%AGENT_PORT%/"

echo Starting Agent Workbench at %AGENT_URL%
echo Workspace: %CD%
echo URL: %AGENT_URL%>> "%AGENT_LOG%"
start "" "%AGENT_URL%"
python -m agent.cli start --cwd "%CD%" --port %AGENT_PORT% >> "%AGENT_LOG%" 2>&1
set "AGENT_EXIT=%ERRORLEVEL%"

echo.
echo Agent Workbench exited with code %AGENT_EXIT%.
echo Log: %AGENT_LOG%
echo Agent Workbench stopped. Press any key to close this window.
pause >nul
exit /b %AGENT_EXIT%
