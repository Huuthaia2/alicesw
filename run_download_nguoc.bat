@echo off
REM ============================================================
REM  AliceSW - Tai + Dich NGUOC (tu trang CUOI ve trang 1)
REM  Huu ich khi: listing sap xep moi nhat truoc -> --reverse
REM  bat dau tu truyen CU nhat, khong tai trung truyen da dich.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title AliceSW - Tai + Dich NGUOC (tag me con)

python -u alicesw_downloader.py "https://www.alicesw.com/search?q=%%E6%%AF%%8D%%E5%%AD%%90&f=tag"  --all --reverse --no-translate --workers 4

echo.
echo === Da xong. Nhan phim bat ky de dong cua so. ===
pause >nul
