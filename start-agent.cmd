@echo off
setlocal

cd /d "%~dp0"
set "PYTHONPATH=src"
if "%AGENT_PORT%"=="" set "AGENT_PORT=8000"
set "AGENT_LOG=%~dp0.agent\start-agent.log"
set "AGENT_PYTHON="
rem --window opens the desktop window instead of a browser tab; start-agent-window.cmd
rem passes it with a hidden console, where nobody can press a key, so failures open the log.
set "AGENT_OPEN=--open-browser"
if /I "%~1"=="--window" set "AGENT_OPEN=--window"

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
  if "%AGENT_OPEN%"=="--window" (notepad "%AGENT_LOG%") else (pause >nul)
  exit /b 1
)

echo Python: %AGENT_PYTHON%>> "%AGENT_LOG%"
"%AGENT_PYTHON%" --version >> "%AGENT_LOG%" 2>&1
"%AGENT_PYTHON%" -c "import agent.cli" >> "%AGENT_LOG%" 2>&1
if errorlevel 1 (
  echo Could not import agent.cli with %AGENT_PYTHON%. See %AGENT_LOG%.
  echo Could not import agent.cli with %AGENT_PYTHON%.>> "%AGENT_LOG%"
  if "%AGENT_OPEN%"=="--window" (notepad "%AGENT_LOG%") else (pause >nul)
  exit /b 1
)

echo Starting Agent Workbench from port %AGENT_PORT%. Browser opens after the server starts.
echo Workspace: %CD%
echo Requested port: %AGENT_PORT%>> "%AGENT_LOG%"
"%AGENT_PYTHON%" -m agent.cli start --cwd "%CD%" --port %AGENT_PORT% %AGENT_OPEN% >> "%AGENT_LOG%" 2>&1
set "AGENT_EXIT=%ERRORLEVEL%"
echo Python exited with code %AGENT_EXIT%.>> "%AGENT_LOG%"
if "%AGENT_OPEN%"=="--window" (
  if not "%AGENT_EXIT%"=="0" notepad "%AGENT_LOG%"
  exit /b %AGENT_EXIT%
)

echo.
echo Agent Workbench exited with code %AGENT_EXIT%.
echo Log: %AGENT_LOG%
echo Agent Workbench stopped. Press any key to close this window.
pause >nul
exit /b %AGENT_EXIT%
