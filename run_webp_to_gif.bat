@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Dang khoi dong WebP to GIF Converter...
py webp_to_gif_gui.py
