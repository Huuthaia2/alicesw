@echo off
REM ============================================================
REM  AliceSW - Watcher DICH: origin/ -> translated/
REM  Quet lien tuc downloaded/origin, dich sang tieng Viet.
REM  Chay SONG SONG voi run_download.bat (mo cua so rieng).
REM  Engine free (Caiyun->Google->Bing) - khong can API key.
REM
REM  LUU Y: khau dich CAN thu vien 'translators' -> phai chay
REM  bang ban Python da cai (py -m pip install translators).
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title AliceSW - Dich origin -^> translated (watcher)

python -u alicesw_translate.py --file-workers 9 --engine google --retry-failed --nguoc

echo.
echo === Watcher dich da dung. Nhan phim bat ky de dong cua so. ===
pause >nul
