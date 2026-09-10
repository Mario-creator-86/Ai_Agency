@echo off
REM One command to start AMN-AI (Autonomous Machine Nexus): dependencies, database, frontend, server.
REM Double-click this file, or run it from a terminal. Ctrl+C stops the studio.
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv was not found on PATH.
  echo Install it from https://docs.astral.sh/uv/ and run this file again.
  pause
  exit /b 1
)

uv run python scripts\start.py %*
set EXITCODE=%errorlevel%

if not "%EXITCODE%"=="0" (
  echo.
  echo The studio did not start. The error above says which step failed.
  pause
)
exit /b %EXITCODE%
