@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FSNovel - Tai truyen fsnovel.com

python -u fsnovel_downloader.py --translate --engine google --delay 1.0

echo.
echo === FSNovel da xong. Nhan phim bat ky de dong. ===
pause >nul
