@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  FSNovel Downloader - fsnovel.com
echo ============================================================
echo.
echo  [1] Tai ban goc (chu Han, khong dich)
echo  [2] Tai + Dich tieng Viet (engine free: Caiyun+Google)
echo  [3] Tai + Dich (Gemini - can API key)
echo  [4] Tai 1 truyen cu the
echo  [5] Tiep tuc tu trang cu (nhap so trang)
echo  [6] Thoat
echo.
set /p choice="Chon (1-6): "

if "%choice%"=="1" goto ORIGIN
if "%choice%"=="2" goto TRANSLATE
if "%choice%"=="3" goto GEMINI
if "%choice%"=="4" goto SINGLE
if "%choice%"=="5" goto RESUME
if "%choice%"=="6" goto END
goto END

:ORIGIN
echo.
echo [Tai ban goc - khong dich]
py -u fsnovel_downloader.py --delay 1.5
goto DONE

:TRANSLATE
echo.
echo [Tai + Dich tieng Viet - Caiyun/Google]
py -u fsnovel_downloader.py --translate --engine free --delay 1.5
goto DONE

:GEMINI
echo.
set /p GKEY="Nhap Gemini API key: "
if "%GKEY%"=="" (
    echo [!] Chua nhap API key, dung lai.
    goto DONE
)
echo [Tai + Dich bang Gemini]
py -u fsnovel_downloader.py --translate --engine gemini --gemini-key "%GKEY%" --delay 1.5
goto DONE

:SINGLE
echo.
set /p URL="Nhap URL truyen: "
if "%URL%"=="" (
    echo [!] Chua nhap URL, dung lai.
    goto DONE
)
set /p TRANS="Dich sang tieng Viet? (y/N): "
if /i "%TRANS%"=="y" (
    py -u fsnovel_downloader.py --translate --url "%URL%"
) else (
    py -u fsnovel_downloader.py --url "%URL%"
)
goto DONE

:RESUME
echo.
set /p PAGE="Bat dau tu trang so: "
if "%PAGE%"=="" set PAGE=1
set /p TRANS="Dich sang tieng Viet? (y/N): "
if /i "%TRANS%"=="y" (
    py -u fsnovel_downloader.py --translate --start-page %PAGE%
) else (
    py -u fsnovel_downloader.py --start-page %PAGE%
)
goto DONE

:DONE
echo.
echo ============================================================
echo  Xong!
echo ============================================================
pause

:END
