@echo off
echo ╔════════════════════════════════════════════════════╗
echo ║   ORAKL Bot v2.0 Enhanced - Activation Script     ║
echo ╚════════════════════════════════════════════════════╝
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8+ from python.org
    pause
    exit /b 1
)

echo [1/5] Checking Python installation...
python --version
echo.

REM Check if config.env exists
if not exist "config.env" (
    if not exist ".env" (
        echo [ERROR] Configuration file not found!
        echo Please ensure config.env or .env exists
        pause
        exit /b 1
    )
)

REM Copy config.env to .env if .env doesn't exist
if not exist ".env" (
    echo [2/5] Creating .env from config.env...
    copy config.env .env
    echo ✓ Configuration file created
) else (
    echo [2/5] Using existing .env file...
    echo ✓ Configuration found
)
echo.

REM Install/Update dependencies
echo [3/5] Installing/updating dependencies...
echo This may take a few minutes...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [WARNING] Some dependencies may have failed to install
    echo The bot may still work, but check for errors
) else (
    echo ✓ All dependencies installed successfully
)
echo.

REM Create logs directory
if not exist "logs" (
    echo [4/5] Creating logs directory...
    mkdir logs
    echo ✓ Logs directory created
) else (
    echo [4/5] Logs directory exists...
    echo ✓ Logs ready
)
echo.

REM Run configuration validation
echo [5/5] Validating configuration...
python -c "from src.config import Config; Config.validate()" 2>nul
if errorlevel 1 (
    echo [WARNING] Configuration validation failed
    echo Please check your .env file settings
    echo.
    echo Common issues:
    echo   - POLYGON_API_KEY not set or invalid
    echo   - DISCORD_WEBHOOK_URL not set
    echo   - Invalid threshold values
    echo.
    set /p continue="Continue anyway? (y/N): "
    if /i not "%continue%"=="y" (
        echo Activation cancelled
        pause
        exit /b 1
    )
) else (
    echo ✓ Configuration valid
)
echo.

echo ═════════════════════════════════════════════════════
echo    Ready to start ORAKL Bot v2.0 Enhanced! 🚀
echo ═════════════════════════════════════════════════════
echo.
echo What would you like to do?
echo.
echo [1] Start bot in this window (Recommended)
echo [2] Start bot in background (Hidden)
echo [3] Exit without starting
echo.
set /p choice="Enter choice (1-3): "

if "%choice%"=="1" (
    echo.
    echo Starting ORAKL Bot...
    echo Press Ctrl+C to stop the bot
    echo.
    python main.py
) else if "%choice%"=="2" (
    echo.
    echo Starting bot in background...
    start /B pythonw main.py
    echo ✓ Bot started in background
    echo.
    echo To stop: Use Task Manager to end Python process
    echo Logs: Check logs\orakl_YYYYMMDD.log
    timeout /t 5
) else (
    echo.
    echo Activation complete. Run this script again to start the bot.
)

echo.
pause
