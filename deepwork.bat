@echo off
cd /d %~dp0
powershell -Command "Start-Process python -ArgumentList 'frontend.py' -Verb RunAs -WorkingDirectory '%~dp0'"
timeout /t 3 /nobreak >nul
start http://localhost:5000
