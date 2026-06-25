@echo off
cd /d "%~dp0.."
py compress_mp3.py --dir "%~dp0"
pause
