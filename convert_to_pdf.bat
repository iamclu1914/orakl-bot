@echo off
REM Bullseye Bot - Automated PDF Conversion Script
REM Requires Pandoc to be installed: https://pandoc.org/installing.html

echo ========================================
echo Bullseye Bot PDF Converter
echo ========================================
echo.

REM Check if Pandoc is installed
where pandoc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Pandoc is not installed or not in PATH
    echo.
    echo Please install Pandoc from: https://pandoc.org/installing.html
    echo Or use VS Code with "Markdown PDF" extension instead
    echo.
    pause
    exit /b 1
)

echo Pandoc found! Starting conversion...
echo.

REM Convert Part 1
echo [1/3] Converting Part 1 (Main Implementation)...
pandoc BULLSEYE_BOT_COMPLETE_CODE.md -o BULLSEYE_BOT_PART1.pdf --pdf-engine=xelatex -V geometry:margin=0.75in -V fontsize=10pt --highlight-style=tango
if %ERRORLEVEL% EQU 0 (
    echo ✓ Part 1 converted successfully: BULLSEYE_BOT_PART1.pdf
) else (
    echo ✗ Part 1 conversion failed
)
echo.

REM Convert Part 2
echo [2/3] Converting Part 2 (Data & Utilities)...
pandoc BULLSEYE_BOT_PART2_DATA_UTILS.md -o BULLSEYE_BOT_PART2.pdf --pdf-engine=xelatex -V geometry:margin=0.75in -V fontsize=10pt --highlight-style=tango
if %ERRORLEVEL% EQU 0 (
    echo ✓ Part 2 converted successfully: BULLSEYE_BOT_PART2.pdf
) else (
    echo ✗ Part 2 conversion failed
)
echo.

REM Create combined version
echo [3/3] Creating combined PDF...
copy BULLSEYE_BOT_COMPLETE_CODE.md + BULLSEYE_BOT_PART2_DATA_UTILS.md BULLSEYE_BOT_COMBINED.md >nul 2>&1
pandoc BULLSEYE_BOT_COMBINED.md -o BULLSEYE_BOT_COMPLETE.pdf --pdf-engine=xelatex -V geometry:margin=0.75in -V fontsize=9pt --highlight-style=tango --toc --toc-depth=2
if %ERRORLEVEL% EQU 0 (
    echo ✓ Combined PDF created: BULLSEYE_BOT_COMPLETE.pdf
    del BULLSEYE_BOT_COMBINED.md
) else (
    echo ✗ Combined PDF conversion failed
)
echo.

echo ========================================
echo Conversion Complete!
echo ========================================
echo.
echo Generated files:
echo   • BULLSEYE_BOT_PART1.pdf (Main Implementation)
echo   • BULLSEYE_BOT_PART2.pdf (Data & Utilities)
echo   • BULLSEYE_BOT_COMPLETE.pdf (Combined)
echo.
echo Total: ~5,000 lines of documented code
echo.

pause


