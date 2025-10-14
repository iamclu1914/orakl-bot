@echo off
REM ORAKL Bot v2.0 Enhanced - 24/7 Control Panel

:menu
cls
echo.
echo ╔════════════════════════════════════════════════════╗
echo ║   ORAKL Bot v2.0 Enhanced - Control Panel         ║
echo ║   24/7 Operations Management                      ║
echo ╚════════════════════════════════════════════════════╝
echo.

REM Get current status
pm2 list | findstr "orakl-bot-enhanced" > temp_status.txt
for /f "tokens=8,10,12" %%a in (temp_status.txt) do (
    set STATUS=%%a
    set UPTIME=%%b
    set RESTARTS=%%c
)
del temp_status.txt 2>nul

echo Current Status:
echo   Bot: orakl-bot-enhanced
if "%STATUS%"=="online" (
    echo   Status: 🟢 ONLINE
) else (
    echo   Status: 🔴 OFFLINE
)
echo   Uptime: %UPTIME%
echo   Restarts: %RESTARTS%
echo.
echo ════════════════════════════════════════════════════
echo.
echo [1] View Live Logs
echo [2] View Status
echo [3] Restart Bot
echo [4] Stop Bot
echo [5] Start Bot
echo [6] View Error Logs
echo [7] Monitor Performance
echo [8] View Cache Stats
echo [9] Test Configuration
echo [0] Exit
echo.
set /p choice="Select option (0-9): "

if "%choice%"=="1" goto logs
if "%choice%"=="2" goto status
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto stop
if "%choice%"=="5" goto start
if "%choice%"=="6" goto errors
if "%choice%"=="7" goto monitor
if "%choice%"=="8" goto cache
if "%choice%"=="9" goto test
if "%choice%"=="0" goto end
goto menu

:logs
echo.
echo Starting live log stream...
echo Press Ctrl+C to return to menu
echo.
pm2 logs orakl-bot-enhanced
goto menu

:status
echo.
pm2 describe orakl-bot-enhanced
echo.
pause
goto menu

:restart
echo.
echo Restarting ORAKL Bot...
pm2 restart orakl-bot-enhanced --update-env
echo.
echo ✓ Bot restarted
timeout /t 2 >nul
goto menu

:stop
echo.
echo Are you sure you want to stop the bot?
set /p confirm="Type YES to confirm: "
if /i "%confirm%"=="YES" (
    pm2 stop orakl-bot-enhanced
    echo.
    echo ✓ Bot stopped
) else (
    echo Cancelled
)
timeout /t 2 >nul
goto menu

:start
echo.
echo Starting ORAKL Bot...
pm2 start ecosystem.config.js
pm2 save
echo.
echo ✓ Bot started and saved
timeout /t 2 >nul
goto menu

:errors
echo.
echo Recent Error Logs:
echo ═══════════════════════════════════════════════════
type logs\pm2-error.log | findstr /I "ERROR CRITICAL WARNING" | more
echo.
pause
goto menu

:monitor
echo.
echo Opening PM2 Monitor...
echo Press Ctrl+C to return to menu
echo.
pm2 monit
goto menu

:cache
echo.
echo Viewing latest log for cache statistics...
type logs\orakl_*.log | findstr /I "cache" | more
echo.
pause
goto menu

:test
echo.
echo Testing configuration...
python validate_setup.py
echo.
pause
goto menu

:end
echo.
echo Exiting control panel...
echo Bot continues running in background
timeout /t 2 >nul
exit
