@echo off
cd /d %~dp0
start http://localhost:5000
powershell -Command "Start-Process python -ArgumentList 'frontend.py' -Verb RunAs -WorkingDirectory '%~dp0'"
