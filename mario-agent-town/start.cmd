@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Instaleaza Node.js 24 sau mai nou, apoi reincearca.
  pause
  exit /b 1
)
node -e "if(Number(process.versions.node.split('.')[0])^<24)process.exit(1)"
if errorlevel 1 (
  echo Este necesar Node.js 24 sau mai nou.
  pause
  exit /b 1
)
if not exist .env copy .env.example .env >nul
echo Deschide http://127.0.0.1:8012 in browser dupa pornire.
node --env-file-if-exists=.env server.mjs
pause
