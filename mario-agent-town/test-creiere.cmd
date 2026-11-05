@echo off
cd /d "%~dp0"
echo Testez creierele AI (poate dura 1-2 minute)...
node test-creiere.mjs
echo.
echo Gata. Fereastra se inchide in 10 secunde.
timeout /t 10 >nul
