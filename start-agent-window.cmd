@echo off
rem Double-click entry for the Agent Workbench desktop window (needs: pip install -e ".[desktop]").
rem Reruns start-agent.cmd with a hidden console: commands the agent runs inherit it and never
rem flash a window, and closing the desktop window stops the server.
set "AGENT_LAUNCHER=%~dp0start-agent.cmd"
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath $env:AGENT_LAUNCHER -ArgumentList '--window' -WindowStyle Hidden"
