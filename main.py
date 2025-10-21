#!/usr/bin/env python3
"""
ORAKL Options Flow Bot - Main Entry Point
Automatically runs on system startup
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from datetime import datetime
import signal
import psutil
from typing import Optional

# Fix Windows console encoding for Unicode
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from src.discord_bot import ORAKLBot
from src.config import Config
from src.bot_manager import BotManager
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.utils.cache import cache_manager
from src.utils.monitoring import metrics

# Setup logging
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"orakl_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class ORAKLRunner:
    def __init__(self):
        self.bot = None
        self.bot_manager = None
        self.running = True
        
    def check_already_running(self):
        """Check if another instance is already running"""
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid:
                    cmdline = proc.info.get('cmdline') or []
                    if 'main.py' in ' '.join(cmdline) and 'orakl' in ' '.join(cmdline).lower():
                        logger.warning(f"ORAKL Bot already running (PID: {proc.info['pid']})")
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        if self.bot:
            asyncio.create_task(self.bot.close())
    
    async def run_bot(self):
        """Run the ORAKL bot with bulletproof 24/7 operation"""
        restart_count = 0
        max_restarts = 999  # Essentially unlimited restarts for 24/7 operation
        fetcher: Optional[DataFetcher] = None

        while self.running:
            try:
                logger.info(f"Starting ORAKL Bot (attempt {restart_count + 1})")

                # Start cache manager
                logger.info("Starting cache manager...")
                await cache_manager.start()

                # Initialize auto-posting bots with enhanced features
                logger.info("Initializing enhanced auto-posting bot system...")
                
                # Create DataFetcher - don't use context manager to keep it alive
                fetcher = DataFetcher(Config.POLYGON_API_KEY)
                await fetcher._init_session()
                
                analyzer = OptionsAnalyzer()

                self.bot_manager = BotManager(
                    webhook_url=Config.DISCORD_WEBHOOK_URL,
                    fetcher=fetcher,
                    analyzer=analyzer
                )

                # Log memory before starting bots
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"Memory usage before bot start: {memory_mb:.1f}MB")
                
                # Start auto-posting bots in background
                bot_task = asyncio.create_task(self.bot_manager.start_all())
                logger.info("✓ Enhanced auto-posting bots started successfully")
                
                # Log memory after starting bots
                await asyncio.sleep(2)  # Give bots time to initialize
                memory_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"Memory usage after bot start: {memory_mb:.1f}MB")
                
                # CRITICAL: Add immediate heartbeat to prevent Render timeout
                logger.info("🤖 ORAKL Bot is now running and monitoring markets 24/7")
                logger.info("💓 Service heartbeat active - bot is healthy")
                
                # Log bot status with accurate reporting
                status = self.bot_manager.get_bot_status()
                logger.info(f"Active bots: {status['total_bots']}")
                for bot_info in status['bots']:
                    status_emoji = "✓" if bot_info['running'] else "✗"
                    logger.info(f"  {status_emoji} {bot_info['name']}: Scan interval {bot_info['scan_interval']}s")

                # Start heartbeat task FIRST to prevent Render timeout
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                logger.info("Started heartbeat monitor")
                
                # Start Discord bot if token is available
                if Config.DISCORD_BOT_TOKEN and Config.DISCORD_BOT_TOKEN != 'your_discord_bot_token_here':
                    logger.info("Starting Discord bot...")
                    self.bot = ORAKLBot()
                    await self.bot.start(Config.DISCORD_BOT_TOKEN)
                else:
                    logger.warning("Discord bot token not set, running in webhook-only mode")
                    logger.info("Bot will continue running and posting signals to webhook...")
                    
                    # Keep running indefinitely
                    while self.running:
                        await asyncio.sleep(60)
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
                
            except Exception as e:
                logger.error(f"Bot encountered error: {e}", exc_info=True)
                restart_count += 1
                
                # Always restart for 24/7 operation
                wait_time = min(restart_count * 5, 30)  # Max 30 second wait
                logger.warning(f"Restarting in {wait_time} seconds... (attempt {restart_count})")
                await asyncio.sleep(wait_time)
                
                # Reset restart count if we've been running for a while
                if restart_count > 20:
                    restart_count = 0
                    logger.info("Reset restart counter after sustained operation")
            
            finally:
                # Cleanup resources gracefully (never fail)
                try:
                    logger.debug("Cleaning up resources...")
                    
                    if self.bot_manager:
                        try:
                            await asyncio.wait_for(
                                self.bot_manager.stop_all(),
                                timeout=10
                            )
                            logger.debug("✓ Bots stopped")
                        except asyncio.TimeoutError:
                            logger.warning("Bot shutdown timeout, forcing cleanup")
                        except Exception as e:
                            logger.debug(f"Error stopping bots: {e}")
                    
                    # Don't stop cache manager - keep it running for next iteration
                    # Only log stats
                    try:
                        all_stats = cache_manager.get_all_stats()
                        logger.debug(f"Cache stats: {all_stats.get('market', {}).get('hit_rate', 0):.1%} hit rate")
                    except Exception as e:
                        logger.debug(f"Error logging metrics: {e}")

                    if fetcher:
                        try:
                            await fetcher.close()
                        except Exception as e:
                            logger.debug(f"Error closing data fetcher: {e}")
                        finally:
                            fetcher = None
                
                except Exception as e:
                    logger.error(f"Cleanup error (non-fatal): {e}")
                
                # Small delay before restart
                if self.running and restart_count > 0:
                    await asyncio.sleep(2)
    
    def print_startup_banner(self):
        """Display enhanced startup banner"""
        banner = """
╔════════════════════════════════════════════════════╗
║     ORAKL OPTIONS FLOW BOT v2.0 ENHANCED 🚀       ║
║     Polygon API + Discord + Advanced Analytics     ║
║     Production-Ready with Auto-Recovery            ║
╚════════════════════════════════════════════════════╝
        """
        print(banner)
        logger.info("=" * 60)
        logger.info("ORAKL Enhanced Bot Starting...")
        logger.info("=" * 60)
        logger.info(f"System: {sys.platform}")
        logger.info(f"Python: {sys.version.split()[0]}")
        logger.info(f"Working Directory: {os.getcwd()}")
        logger.info(f"Process ID: {os.getpid()}")
        log_filename = f"orakl_{datetime.now().strftime('%Y%m%d')}.log"
        logger.info(f"Log File: {log_dir / log_filename}")
        logger.info("")
        logger.info("Enhanced Features:")
        logger.info("  ✓ Exponential backoff retry logic")
        logger.info("  ✓ Circuit breaker for API protection")
        logger.info("  ✓ Rate limiting with token bucket")
        logger.info("  ✓ In-memory caching with TTL")
        logger.info("  ✓ Connection pooling for efficiency")
        logger.info("  ✓ Advanced market context analysis")
        logger.info("  ✓ Health monitoring & metrics")
        logger.info("  ✓ Comprehensive error handling")
        logger.info("=" * 60)
    
    async def _heartbeat_loop(self):
        """Heartbeat loop to prevent Render timeout"""
        heartbeat_count = 0
        process = psutil.Process()
        
        while self.running:
            try:
                # More frequent heartbeat for first 2 minutes
                if heartbeat_count < 12:  # First 2 minutes
                    await asyncio.sleep(10)  # Every 10 seconds
                    heartbeat_count += 1
                    logger.info(f"💓 Bot heartbeat #{heartbeat_count} - Service is active and monitoring {len(self.bot_manager.bots) if self.bot_manager else 0} bots")
                else:
                    await asyncio.sleep(30)  # Then every 30 seconds
                
                # Log memory usage
                memory_mb = process.memory_info().rss / 1024 / 1024
                if heartbeat_count < 12 or heartbeat_count % 2 == 0:
                    logger.info(f"Memory: {memory_mb:.1f}MB | Status: Operational | Uptime: {heartbeat_count * 10}s")
                    
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(10)
    
    async def main(self):
        """Main execution"""
        self.print_startup_banner()
        
        # Check if already running
        if self.check_already_running():
            logger.error("Another instance is already running. Exiting.")
            sys.exit(1)
        
        # Validate configuration
        try:
            Config.validate()
            logger.info("Configuration validated successfully")
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            logger.error("Please check your .env file")
            sys.exit(1)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Health server not needed for Background Workers
        # Only start if PORT is explicitly set (for Web Service compatibility)
        port = os.getenv('PORT')
        if port:
            logger.info(f"PORT detected ({port}), starting health check server")
            try:
                from health_server import start_health_server
                asyncio.create_task(start_health_server(int(port)))
                logger.info("Health check server started successfully")
            except Exception as e:
                logger.warning(f"Could not start health server: {e}")
        else:
            logger.info("Running as Background Worker - no health server needed")
        
        # Run the bot
        await self.run_bot()
        
        logger.info("ORAKL Bot stopped")

if __name__ == "__main__":
    runner = ORAKLRunner()
    
    try:
        asyncio.run(runner.main())
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)
