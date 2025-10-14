@echo off
title ORAKL Options Flow Bot
cd /d "%~dp0"

echo ========================================
echo      ORAKL OPTIONS FLOW BOT
echo      Starting Bot...
echo ========================================
echo.

python main.py

if %errorlevel% neq 0 (
    echo.
    echo Bot stopped with error.
    pause
) else (
    echo.
    echo Bot stopped normally.
    pause
)
