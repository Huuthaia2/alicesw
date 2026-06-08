@echo off
REM ============================================================
REM  AliceSW - Tai + Dich (tag me con: q=母子)
REM  --all        : tai het truyen trong trang search
REM  --workers 1  : tuan tu (bat buoc khi dich - engine Caiyun dung chung)
REM  Truyen ngan (< 8 chuong): tu doi IP qua ProtonVPN CLI sau moi truyen.
REM
REM  LUU Y batch: URL co dau & va % nen:
REM   - boc trong " " (de & khong bi hieu la noi lenh)
REM   - moi % phai viet thanh %% (de batch khong hieu la bien)
REM     %%E6%%AF%%8D = 母 , %%E5%%AD%%90 = 子  -> q=母子
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title AliceSW - Tai + Dich (tag me con)

python -u alicesw_downloader.py "https://www.alicesw.com/search?q=%%E6%%AF%%8D%%E5%%AD%%90&f=tag"  --all --no-translate --workers 4

echo.
echo === Da xong. Nhan phim bat ky de dong cua so. ===
pause >nul
