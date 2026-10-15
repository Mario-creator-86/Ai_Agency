@echo off
rem Repornire curata a studioului, fara tastatura (dublu-click din File Explorer).
rem Ruleaza scripts\restart.py: Ctrl+C catre start.py (oprire curata, GPU verificat oprit),
rem apoi pornire din nou intr-o consola noua. Ziua taiata e reluata de studio dupa pornire.
cd /d "%~dp0"
echo === Repornire studio: %date% %time% >> data\logs\restart_studio_cmd.log
uv run --locked python -X utf8 scripts\restart.py --wait 600 >> data\logs\restart_studio_cmd.log 2>&1
echo === Cod de iesire: %errorlevel% >> data\logs\restart_studio_cmd.log
exit
