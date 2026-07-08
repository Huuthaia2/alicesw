@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Langyou Downloader
py langyou_downloader.py
pause
