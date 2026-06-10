@echo off
REM ============================================================
REM  AliceSW - Watcher MP3: translated/ -> translated/mp3/
REM  Quet lien tuc downloaded/translated, doc truyen .txt -> .mp3 (gTTS).
REM  Chay SONG SONG voi run_download.bat + run_translate.bat.
REM
REM  LUU Y: khau nay CAN thu vien 'gTTS' (py -m pip install gTTS),
REM  va ffmpeg de hau ky (toc do 1.15x + bitrate 32k) - thieu thi bo qua hau ky.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title AliceSW - Tao MP3 tu translated (watcher)

REM  --vpn warp       = Cloudflare WARP (doi IP khi 429)
REM  --vpn protonvpn  = ProtonVPN CLI/service
REM  --vpn none       = khong doi IP, chi backoff
REM  --vpn auto       = tu dong chon (protonvpn truoc, fallback warp)
REM  --no-auto        = giu co dinh so thread (khong tu tang/giam)
python -u txt_to_mp3.py --workers 9 --chunk-delay 0.2 --vpn hotspot  --no-auto --max-size 3

echo.
echo === Watcher MP3 da dung. Nhan phim bat ky de dong cua so. ===
pause >nul
