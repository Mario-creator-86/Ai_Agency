@echo off
setlocal
cd /d "%~dp0"
set R=%~dp0instalare-raport.txt
echo Verific calculatorul pentru Mario Agent Town... > "%R%"
echo [data] %date% %time% >> "%R%"
echo. >> "%R%"
echo [node] >> "%R%"
where node >> "%R%" 2>&1
node --version >> "%R%" 2>&1
echo. >> "%R%"
echo [npm] >> "%R%"
call npm --version >> "%R%" 2>&1
call npm prefix -g >> "%R%" 2>&1
echo. >> "%R%"
echo [winget] >> "%R%"
winget --version >> "%R%" 2>&1
echo. >> "%R%"
echo [codex] >> "%R%"
where codex >> "%R%" 2>&1
call codex --version >> "%R%" 2>&1
call codex login status >> "%R%" 2>&1
echo. >> "%R%"
echo [claude] >> "%R%"
where claude >> "%R%" 2>&1
call claude --version >> "%R%" 2>&1
echo. >> "%R%"
echo [ollama] >> "%R%"
where ollama >> "%R%" 2>&1
ollama --version >> "%R%" 2>&1
ollama list >> "%R%" 2>&1
echo. >> "%R%"
echo [port 8012] >> "%R%"
netstat -ano | findstr ":8012" >> "%R%" 2>&1
echo. >> "%R%"
echo [gata] >> "%R%"
echo Verificarea s-a terminat. Fereastra se inchide.
timeout /t 3 >nul
