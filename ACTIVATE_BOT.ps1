# ORAKL Bot v2.0 Enhanced - PowerShell Activation Script

Write-Host "╔════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   ORAKL Bot v2.0 Enhanced - Activation Script     ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Function to check if command exists
function Test-Command($cmdname) {
    return [bool](Get-Command -Name $cmdname -ErrorAction SilentlyContinue)
}

# Check Python installation
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
if (-not (Test-Command python)) {
    Write-Host "[ERROR] Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.8+ from python.org" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$pythonVersion = python --version
Write-Host "✓ Found: $pythonVersion" -ForegroundColor Green
Write-Host ""

# Check configuration
Write-Host "[2/5] Checking configuration..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path "config.env") {
        Write-Host "Creating .env from config.env..." -ForegroundColor Yellow
        Copy-Item "config.env" ".env"
        Write-Host "✓ Configuration file created" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] No configuration file found!" -ForegroundColor Red
        Write-Host "Please ensure config.env or .env exists" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
} else {
    Write-Host "✓ Configuration file exists" -ForegroundColor Green
}
Write-Host ""

# Install dependencies
Write-Host "[3/5] Installing/updating dependencies..." -ForegroundColor Yellow
Write-Host "This may take a few minutes..." -ForegroundColor Gray

try {
    python -m pip install --upgrade pip --quiet | Out-Null
    pip install -r requirements.txt --quiet
    Write-Host "✓ All dependencies installed successfully" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] Some dependencies may have failed" -ForegroundColor Yellow
    Write-Host "The bot may still work, but check for errors" -ForegroundColor Yellow
}
Write-Host ""

# Create logs directory
Write-Host "[4/5] Setting up logs directory..." -ForegroundColor Yellow
if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
    Write-Host "✓ Logs directory created" -ForegroundColor Green
} else {
    Write-Host "✓ Logs directory exists" -ForegroundColor Green
}
Write-Host ""

# Validate configuration
Write-Host "[5/5] Validating configuration..." -ForegroundColor Yellow
try {
    python -c "from src.config import Config; Config.validate()" 2>&1 | Out-Null
    Write-Host "✓ Configuration valid" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] Configuration validation failed" -ForegroundColor Yellow
    Write-Host "Please check your .env file settings" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Common issues:" -ForegroundColor Gray
    Write-Host "  - POLYGON_API_KEY not set or invalid" -ForegroundColor Gray
    Write-Host "  - DISCORD_WEBHOOK_URL not set" -ForegroundColor Gray
    Write-Host "  - Invalid threshold values" -ForegroundColor Gray
    Write-Host ""
    
    $continue = Read-Host "Continue anyway? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        Write-Host "Activation cancelled" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Write-Host ""

# Display ready message
Write-Host "═════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   Ready to start ORAKL Bot v2.0 Enhanced! 🚀" -ForegroundColor Green
Write-Host "═════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "What would you like to do?" -ForegroundColor Yellow
Write-Host ""
Write-Host "[1] Start bot in this window (Recommended)" -ForegroundColor White
Write-Host "[2] Start bot in background (Hidden)" -ForegroundColor White
Write-Host "[3] Exit without starting" -ForegroundColor White
Write-Host ""

$choice = Read-Host "Enter choice (1-3)"

switch ($choice) {
    "1" {
        Write-Host ""
        Write-Host "Starting ORAKL Bot..." -ForegroundColor Green
        Write-Host "Press Ctrl+C to stop the bot" -ForegroundColor Yellow
        Write-Host ""
        python main.py
    }
    "2" {
        Write-Host ""
        Write-Host "Starting bot in background..." -ForegroundColor Yellow
        Start-Process -FilePath "pythonw" -ArgumentList "main.py" -WindowStyle Hidden
        Write-Host "✓ Bot started in background" -ForegroundColor Green
        Write-Host ""
        Write-Host "To stop: Use Task Manager to end Python process" -ForegroundColor Yellow
        Write-Host "Logs: Check logs\orakl_YYYYMMDD.log" -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
    default {
        Write-Host ""
        Write-Host "Activation complete. Run this script again to start the bot." -ForegroundColor Cyan
    }
}

Write-Host ""
Read-Host "Press Enter to exit"
