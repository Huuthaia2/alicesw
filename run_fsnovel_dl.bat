@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FSNovel - Tai truyen fsnovel.com

python -u fsnovel_downloader.py --translate --engine free --delay 1.5

echo.
echo === FSNovel da xong. Nhan phim bat ky de dong. ===
pause >nul
