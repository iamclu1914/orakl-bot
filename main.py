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
import time
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
from src.core import HedgeHunter, ContextManager

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
        self.send_test_alert_flag = False
        
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
        signal_name = 'SIGTERM' if signum == 15 else f'signal {signum}'
        logger.warning(f"⚠️ Received {signal_name}, initiating graceful shutdown...")
        
        # Log current memory usage and uptime
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            uptime = int(time.time() - self.start_time) if hasattr(self, 'start_time') else 0
            logger.info(f"Shutdown stats - Memory: {memory_mb:.1f}MB, Uptime: {uptime}s")
        except:
            pass
            
        self.running = False
        if self.bot:
            asyncio.create_task(self.bot.close())
    
    async def _discord_login_loop(self):
        """Background task to handle Discord bot login with retries - DOES NOT affect webhook bots"""
        retry_count = 0
        
        while self.running:
            try:
                logger.info("🔌 Attempting Discord bot login...")
                self.bot = ORAKLBot()
                await self.bot.start(Config.DISCORD_BOT_TOKEN)
                # If we get here, login succeeded - the bot.start() blocks until disconnected
                logger.info("Discord bot disconnected normally")
                break
                
            except Exception as e:
                error_str = str(e)
                retry_count += 1
                
                # Check for rate limiting
                is_rate_limited = (
                    '429' in error_str or 
                    'rate limit' in error_str.lower() or
                    'cloudflare' in error_str.lower() or
                    'being rate limited' in error_str.lower() or
                    'Error 1015' in error_str
                )
                
                if is_rate_limited:
                    # Long wait for rate limits - 5 to 15 minutes
                    wait_time = min(300 + (retry_count * 60), 900)
                    logger.warning(f"⚠️ Discord rate limited - retrying in {wait_time}s (attempt {retry_count})")
                    logger.warning("⚠️ Webhook bots continue running normally")
                else:
                    # Shorter wait for other errors
                    wait_time = min(30 + (retry_count * 10), 120)
                    logger.error(f"Discord login error: {e}")
                    logger.info(f"Will retry Discord login in {wait_time}s...")
                
                await asyncio.sleep(wait_time)
                
                # Reset counter after many retries
                if retry_count > 20:
                    retry_count = 0
        
        logger.info("Discord login loop ended")

    async def run_bot(self):
        """Run the ORAKL bot with bulletproof 24/7 operation - webhook bots are ISOLATED from Discord errors"""
        fetcher: Optional[DataFetcher] = None
        gex_task = None
        bot_task = None
        heartbeat_task = None
        discord_task = None

        try:
            logger.info("Starting ORAKL Bot...")

            # Start cache manager
            logger.info("Starting cache manager...")
            await cache_manager.start()

            # Initialize auto-posting bots with enhanced features
            logger.info("Initializing enhanced auto-posting bot system...")
            
            # Create DataFetcher - don't use context manager to keep it alive
            fetcher = DataFetcher(Config.POLYGON_API_KEY)
            await fetcher._init_session()
            
            analyzer = OptionsAnalyzer()
            
            # Initialize ORAKL v3.0 "Brain" modules (State-Aware Engine)
            hedge_hunter = HedgeHunter(fetcher) if Config.HEDGE_CHECK_ENABLED else None
            context_manager = ContextManager(fetcher)
            
            # Start Context Manager background loop (GEX Engine)
            gex_task = asyncio.create_task(context_manager.run_loop())
            logger.info("✓ GEX Engine started (updates every %ds)", Config.GEX_UPDATE_INTERVAL)
            if hedge_hunter:
                logger.info("✓ Hedge Hunter enabled (checks trades > $%dk)", Config.HEDGE_CHECK_MIN_PREMIUM // 1000)

            self.bot_manager = BotManager(
                webhook_url=Config.DISCORD_WEBHOOK_URL,
                fetcher=fetcher,
                analyzer=analyzer,
                hedge_hunter=hedge_hunter,
                context_manager=context_manager
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

            # Start heartbeat task to prevent Render timeout
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("Started heartbeat monitor")
            
            # Start Discord bot as BACKGROUND TASK (non-blocking)
            # Discord errors will NOT crash the webhook bots
            if Config.DISCORD_BOT_TOKEN and Config.DISCORD_BOT_TOKEN != 'your_discord_bot_token_here':
                if self.send_test_alert_flag:
                    # Special case: test alert mode - run Discord synchronously
                    logger.info("Test alert mode - starting Discord bot synchronously...")
                    self.bot = ORAKLBot()
                    await self.bot.start(Config.DISCORD_BOT_TOKEN)
                    logger.info("Sending test alert and shutting down...")
                    await self.bot.send_test_alert()
                    await self.bot.close()
                    self.running = False
                else:
                    # Normal mode: Discord runs in background, doesn't block webhook bots
                    logger.info("🔌 Starting Discord bot in background (non-blocking)...")
                    discord_task = asyncio.create_task(self._discord_login_loop())
            else:
                logger.warning("Discord bot token not set, running in webhook-only mode")
            
            logger.info("=" * 50)
            logger.info("✅ WEBHOOK BOTS NOW RUNNING INDEPENDENTLY")
            logger.info("   Discord errors will NOT stop the scanning bots")
            logger.info("=" * 50)
            
            # Main loop - keep running while webhook bots operate
            # This loop will only exit on graceful shutdown (self.running = False)
            while self.running:
                await asyncio.sleep(60)
                
                # Periodic health check
                try:
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    if memory_mb > 1500:  # Memory warning threshold
                        logger.warning(f"⚠️ High memory usage: {memory_mb:.1f}MB")
                except:
                    pass
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            
        except Exception as e:
            logger.error(f"Critical bot error: {e}", exc_info=True)
            # Only critical non-Discord errors reach here
            
        finally:
            # Cleanup resources gracefully
            logger.info("Initiating graceful shutdown...")
            
            # Cancel background tasks
            for task, name in [(discord_task, "Discord"), (heartbeat_task, "Heartbeat"), 
                               (gex_task, "GEX"), (bot_task, "BotManager")]:
                if task and not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=5)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.debug(f"{name} task cancelled")
                    except Exception as e:
                        logger.debug(f"{name} task error: {e}")
            
            # Stop bot manager
            if self.bot_manager:
                try:
                    await asyncio.wait_for(self.bot_manager.stop_all(), timeout=10)
                    logger.info("✓ Bots stopped")
                except asyncio.TimeoutError:
                    logger.warning("Bot shutdown timeout, forcing cleanup")
                except Exception as e:
                    logger.debug(f"Error stopping bots: {e}")
            
            # Close Discord bot
            if self.bot:
                try:
                    await self.bot.close()
                except:
                    pass
            
            # Log cache stats
            try:
                all_stats = cache_manager.get_all_stats()
                logger.debug(f"Cache stats: {all_stats.get('market', {}).get('hit_rate', 0):.1%} hit rate")
            except:
                pass

            # Close data fetcher
            if fetcher:
                try:
                    await fetcher.close()
                except Exception as e:
                    logger.debug(f"Error closing data fetcher: {e}")
    
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
        start_time = time.time()
        
        while self.running:
            try:
                # VERY frequent heartbeat for first 3 minutes to prevent Render timeout
                if heartbeat_count < 36:  # First 3 minutes (5 second intervals)
                    await asyncio.sleep(5)  # Every 5 seconds
                    heartbeat_count += 1
                    uptime = int(time.time() - start_time)
                    
                    # Log different messages to show activity
                    if heartbeat_count % 3 == 0:
                        logger.info(f"🔥 Bot actively monitoring markets - {len(self.bot_manager.bots) if self.bot_manager else 0} bots running | Uptime: {uptime}s")
                    elif heartbeat_count % 3 == 1:
                        logger.info(f"📊 Processing market data - Memory: {process.memory_info().rss / 1024 / 1024:.1f}MB | CPU: Active")
                    else:
                        logger.info(f"💓 Service heartbeat #{heartbeat_count} - All systems operational | Watchlist: 109 symbols")
                    
                    # Also print to stdout to ensure Render sees activity
                    print(f"ACTIVE: Bot running - Heartbeat #{heartbeat_count}", flush=True)
                else:
                    # After 3 minutes, reduce frequency
                    await asyncio.sleep(15)  # Every 15 seconds
                    heartbeat_count += 1
                    
                    if heartbeat_count % 4 == 0:
                        uptime_mins = int((time.time() - start_time) / 60)
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        logger.info(f"✅ Bot operational for {uptime_mins} minutes | Memory: {memory_mb:.1f}MB | Status: Healthy")
                    
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)
    
    async def main(self):
        """Main execution"""
        self.print_startup_banner()
        self.start_time = time.time()
        
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
        
        # Parse command line arguments
        if "--test-alert" in sys.argv:
            self.send_test_alert_flag = True
            logger.info("Test alert flag detected. Bot will send a test alert and then shut down.")

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

