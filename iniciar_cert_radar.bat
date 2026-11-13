@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m cert_radar serve
