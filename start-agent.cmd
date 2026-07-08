@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=src"
if "%AGENT_PORT%"=="" set "AGENT_PORT=8000"
set /a AGENT_PORT_END=%AGENT_PORT%+19
set "AGENT_LOG=%~dp0.agent\start-agent.log"
set "AGENT_PYTHON="

if not exist "%~dp0.agent" mkdir "%~dp0.agent"
echo [%DATE% %TIME%] Starting Agent Workbench > "%AGENT_LOG%"
echo Workspace: %CD%>> "%AGENT_LOG%"
where python >> "%AGENT_LOG%" 2>&1

if exist "%~dp0.venv\Scripts\python.exe" set "AGENT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined AGENT_PYTHON if exist "%~dp0venv\Scripts\python.exe" set "AGENT_PYTHON=%~dp0venv\Scripts\python.exe"
if not defined AGENT_PYTHON if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "AGENT_PYTHON=%CONDA_PREFIX%\python.exe"
if not defined AGENT_PYTHON if exist "%USERPROFILE%\miniconda3\python.exe" set "AGENT_PYTHON=%USERPROFILE%\miniconda3\python.exe"
if not defined AGENT_PYTHON if exist "%USERPROFILE%\anaconda3\python.exe" set "AGENT_PYTHON=%USERPROFILE%\anaconda3\python.exe"
for /f "delims=" %%P in ('where python 2^>nul') do (
  if not defined AGENT_PYTHON (
    echo %%P | findstr /I /C:"\Microsoft\WindowsApps\python.exe" >nul
    if errorlevel 1 set "AGENT_PYTHON=%%P"
  )
)

if not defined AGENT_PYTHON (
  echo Could not find a usable Python. Install Python or disable the WindowsApps python alias.
  echo Could not find a usable Python. Install Python or disable the WindowsApps python alias.>> "%AGENT_LOG%"
  pause >nul
  exit /b 1
)

echo Python: %AGENT_PYTHON%>> "%AGENT_LOG%"
"%AGENT_PYTHON%" --version >> "%AGENT_LOG%" 2>&1
"%AGENT_PYTHON%" -c "import agent.cli" >> "%AGENT_LOG%" 2>&1
if errorlevel 1 (
  echo Could not import agent.cli with %AGENT_PYTHON%. See %AGENT_LOG%.
  echo Could not import agent.cli with %AGENT_PYTHON%.>> "%AGENT_LOG%"
  pause >nul
  exit /b 1
)

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
"%AGENT_PYTHON%" -m agent.cli start --cwd "%CD%" --port %AGENT_PORT% >> "%AGENT_LOG%" 2>&1
set "AGENT_EXIT=%ERRORLEVEL%"
echo Python exited with code %AGENT_EXIT%.>> "%AGENT_LOG%"

echo.
echo Agent Workbench exited with code %AGENT_EXIT%.
echo Log: %AGENT_LOG%
echo Agent Workbench stopped. Press any key to close this window.
pause >nul
exit /b %AGENT_EXIT%
