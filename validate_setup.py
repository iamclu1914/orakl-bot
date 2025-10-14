#!/usr/bin/env python3
"""
ORAKL Bot Setup Validator
Checks if everything is ready before activation
"""

import sys
import os
from pathlib import Path

def print_status(message, status):
    """Print status with color"""
    symbols = {"✓": "✓", "✗": "✗", "⚠": "⚠"}
    print(f"{symbols.get(status, status)} {message}")

def validate_python():
    """Check Python version"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print_status(f"Python {version.major}.{version.minor}.{version.micro} installed", "✓")
        return True
    else:
        print_status(f"Python {version.major}.{version.minor} is too old (need 3.8+)", "✗")
        return False

def validate_config():
    """Check configuration files"""
    env_exists = Path(".env").exists()
    config_env_exists = Path("config.env").exists()
    
    if env_exists:
        print_status(".env file found", "✓")
        return True
    elif config_env_exists:
        print_status("config.env found (needs to be renamed to .env)", "⚠")
        print("  → Run: copy config.env .env")
        return False
    else:
        print_status("No configuration file found", "✗")
        return False

def validate_directories():
    """Check required directories"""
    required = ['src', 'src/bots', 'src/utils']
    all_exist = True
    
    for dir_path in required:
        if Path(dir_path).exists():
            print_status(f"Directory {dir_path}/ exists", "✓")
        else:
            print_status(f"Directory {dir_path}/ missing", "✗")
            all_exist = False
    
    # Create logs directory if missing
    if not Path("logs").exists():
        Path("logs").mkdir()
        print_status("Created logs/ directory", "✓")
    else:
        print_status("logs/ directory exists", "✓")
    
    return all_exist

def validate_modules():
    """Check if required modules can be imported"""
    modules_to_check = [
        ('aiohttp', 'aiohttp'),
        ('pandas', 'pandas'),
        ('numpy', 'numpy'),
        ('discord', 'discord.py'),
        ('src.config', 'ORAKL config'),
    ]
    
    all_ok = True
    for module_name, display_name in modules_to_check:
        try:
            __import__(module_name)
            print_status(f"{display_name} available", "✓")
        except ImportError:
            print_status(f"{display_name} not installed", "✗")
            all_ok = False
    
    return all_ok

def validate_config_values():
    """Check configuration values"""
    try:
        from src.config import Config
        
        # Check API key
        if Config.POLYGON_API_KEY and Config.POLYGON_API_KEY != 'your_polygon_key_here':
            print_status("Polygon API key configured", "✓")
        else:
            print_status("Polygon API key not set", "✗")
            return False
        
        # Check webhook
        if Config.DISCORD_WEBHOOK_URL and 'your_webhook_here' not in Config.DISCORD_WEBHOOK_URL:
            print_status("Discord webhook configured", "✓")
        else:
            print_status("Discord webhook not set", "✗")
            return False
        
        # Check watchlist
        if Config.WATCHLIST and len(Config.WATCHLIST) > 0:
            print_status(f"Watchlist configured ({len(Config.WATCHLIST)} symbols)", "✓")
        else:
            print_status("Watchlist is empty", "✗")
            return False
        
        # Validate configuration
        try:
            Config.validate()
            print_status("Configuration validation passed", "✓")
            return True
        except Exception as e:
            print_status(f"Configuration validation failed: {e}", "✗")
            return False
            
    except Exception as e:
        print_status(f"Error loading configuration: {e}", "✗")
        return False

def main():
    """Main validation"""
    print("=" * 60)
    print("ORAKL Bot v2.0 Enhanced - Setup Validator")
    print("=" * 60)
    print()
    
    print("[1/5] Checking Python installation...")
    python_ok = validate_python()
    print()
    
    print("[2/5] Checking configuration files...")
    config_ok = validate_config()
    print()
    
    print("[3/5] Checking directories...")
    dirs_ok = validate_directories()
    print()
    
    print("[4/5] Checking dependencies...")
    modules_ok = validate_modules()
    print()
    
    if not modules_ok:
        print("⚠ Missing dependencies detected!")
        print("→ Install with: pip install -r requirements.txt")
        print()
    
    print("[5/5] Validating configuration values...")
    if config_ok:
        config_values_ok = validate_config_values()
    else:
        print_status("Skipping (no .env file)", "⚠")
        config_values_ok = False
    print()
    
    print("=" * 60)
    if python_ok and config_ok and dirs_ok and modules_ok and config_values_ok:
        print("✓ ALL CHECKS PASSED - READY TO ACTIVATE!")
        print("=" * 60)
        print()
        print("To start the bot, run:")
        print("  python main.py")
        print()
        print("Or use the activation script:")
        print("  ACTIVATE_BOT.bat")
        print()
        return 0
    else:
        print("✗ SOME CHECKS FAILED - PLEASE FIX ISSUES ABOVE")
        print("=" * 60)
        print()
        if not config_ok:
            print("Quick fix:")
            print("  copy config.env .env")
        if not modules_ok:
            print("Install dependencies:")
            print("  pip install -r requirements.txt")
        print()
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nValidation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)

