@echo off
rem Starts the VyralX viral autopilot loop with logging, for the Startup folder
rem or manual launch. Safe to run twice: the loop refuses a second instance.
setlocal
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" -W ignore "scripts\run_viral_autopilot.py" --loop >> "logs\viral_autopilot.log" 2>&1
