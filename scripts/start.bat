@echo off
title ORAKL Options Flow Bot
cd /d "%~dp0\.."

:start
echo ========================================
echo     ORAKL OPTIONS FLOW BOT
echo     Starting at %date% %time%
echo ========================================

python main.py

if %errorlevel% neq 0 (
    echo.
    echo ORAKL Bot crashed with error code %errorlevel%
    echo Restarting in 10 seconds...
    timeout /t 10 /nobreak >nul
    goto start
)

echo ORAKL Bot stopped normally.
pause
