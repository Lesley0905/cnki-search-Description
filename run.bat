@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo.
    echo CNKI Search - Usage:
    echo   run.bat "keywords"
    echo   run.bat "keywords" --core-only --years 2020-2025
    echo   run.bat --batch examples\thesis_queries.json --core-only --years 2020-2025 --max-pages 3
    echo.
    pause
    exit /b
)

echo.
echo ========================================
echo   CNKI Search
echo ========================================
echo.
python -m cnki_search %*
echo.
echo ========================================
echo   Results saved to: results\
echo ========================================
pause
