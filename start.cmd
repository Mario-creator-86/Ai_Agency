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

REM A venv can outlive its uv-managed base interpreter. Repair it before uv run probes it.
if not exist ".venv\Scripts\python.exe" goto launch
".venv\Scripts\python.exe" -c "import sqlite3" >nul 2>nul
if not errorlevel 1 goto launch

if not exist ".python-version" (
  echo The Python runtime is unavailable and .python-version is missing.
  pause
  exit /b 1
)
set "STUDIO_PYTHON_VERSION="
set /p STUDIO_PYTHON_VERSION=<".python-version"
if not defined STUDIO_PYTHON_VERSION (
  echo The Python runtime is unavailable and .python-version is empty.
  pause
  exit /b 1
)
echo Restoring the project's Python %STUDIO_PYTHON_VERSION% runtime...
uv python install --reinstall --no-bin --no-registry "%STUDIO_PYTHON_VERSION%"
if errorlevel 1 (
  echo Python could not be restored. Check the download error above and try again.
  echo An older uv may not know this Python version; update uv using its installation method.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sqlite3" >nul 2>nul
if errorlevel 1 (
  echo The project's environment still cannot start after restoring Python.
  echo Its .venv\pyvenv.cfg may point to a different Python installation.
  pause
  exit /b 1
)

:launch
uv run --locked python scripts\start.py %*
set EXITCODE=%errorlevel%

if not "%EXITCODE%"=="0" (
  echo.
  echo The studio did not start. The error above says which step failed.
  pause
)
exit /b %EXITCODE%
