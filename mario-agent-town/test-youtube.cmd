@echo off
cd /d "%~dp0"
if not exist diagnostic mkdir diagnostic
echo Citesc canalele YouTube conectate in studio (doar citire)...
node test-youtube.mjs
echo.
echo Gata. Fereastra se inchide in 10 secunde.
timeout /t 10 >nul
