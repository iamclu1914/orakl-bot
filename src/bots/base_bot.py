"""Base class for auto-posting bots"""
import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from abc import ABC, abstractmethod
import time
from dataclasses import dataclass, field
from collections import deque, defaultdict
import sqlite3
from pathlib import Path
import threading
import math

from src.config import Config
from src.utils.exceptions import BotException, BotNotRunningException, WebhookException
from src.utils.resilience import exponential_backoff_retry, BoundedDeque
from src.utils.validation import DataValidator
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

@dataclass
class BotMetrics:
    """Bot performance metrics"""
    scan_count: int = 0
    signal_count: int = 0
    error_count: int = 0
    last_scan_time: Optional[datetime] = None
    last_signal_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    scan_durations: deque = field(default_factory=lambda: deque(maxlen=100))
    webhook_success_count: int = 0
    webhook_failure_count: int = 0
    start_time: datetime = field(default_factory=datetime.now)


class BaseAutoBot(ABC):
    """Base class for all auto-posting bots with enhanced monitoring"""

    def __init__(
        self, 
        webhook_url: str, 
        name: str, 
        scan_interval: int = 300,
        hedge_hunter: Optional[Any] = None,
        context_manager: Optional[Any] = None
    ):
        """
        Initialize base bot

        Args:
            webhook_url: Discord webhook URL
            name: Bot name
            scan_interval: Scan interval in seconds (default: 5 minutes)
            hedge_hunter: Optional HedgeHunter instance for synthetic trade detection
            context_manager: Optional ContextManager instance for GEX regime tracking
        """
        self.webhook_url = webhook_url
        self.name = name
        self.scan_interval = scan_interval
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.metrics = BotMetrics()
        self._scan_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._error_history = BoundedDeque(maxlen=100, ttl_seconds=3600)
        self._consecutive_errors = 0
        self._max_consecutive_errors = 25  # Increased from 10
        self._cooldowns: Dict[str, datetime] = {}
        self._skip_records: deque = deque(maxlen=200)
        # Aggregate filter/skip reasons (INFO-level) so we can understand "0 signals" quickly.
        self._filter_counts: Dict[str, int] = defaultdict(int)
        self._filter_report_interval_seconds: int = int(
            getattr(Config, "FILTER_REPORT_INTERVAL_SECONDS", 300)
        )
        self._filter_last_report_ts: float = time.time()
        self.concurrency_limit = getattr(Config, 'MAX_CONCURRENT_REQUESTS', 10)
        self.symbol_scan_timeout = getattr(Config, 'SYMBOL_SCAN_TIMEOUT', 20)
        self._state_lock = threading.Lock()
        self._state_db: Optional[sqlite3.Connection] = None
        self._state_db_path: Optional[Path] = None
        self._low_performers: set[str] = set()

        # Webhook posting can be very bursty in Kafka/event-driven mode. Use a per-bot
        # lock + pacing to avoid Discord 429 storms and to prevent concurrent POSTs.
        self._webhook_post_lock: Optional[asyncio.Lock] = None
        self._last_webhook_post_ts: float = 0.0
        self._webhook_min_interval_seconds: float = float(
            getattr(Config, "DISCORD_WEBHOOK_MIN_INTERVAL_SECONDS", 0.25)
        )
        
        # ORAKL v3.0 Brain modules
        self.hedge_hunter = hedge_hunter
        self.context_manager = context_manager
        
        self._init_state_store()

    async def start_event_mode(self) -> None:
        """
        Start bot in event-driven mode (Kafka): create HTTP session + mark running,
        but DO NOT start the scheduled scan loop.
        """
        if self.running:
            return

        self.running = True

        # Create session (normally created in start()); needed for webhook posting in Kafka mode.
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)

        logger.info(f"{self.name} started in event-driven mode (Kafka) - scan loop disabled")

    def _init_state_store(self) -> None:
        """Initialize persistent state storage for cooldowns and outcomes."""
        try:
            state_path_value = getattr(Config, 'STATE_DB_PATH', 'state/bot_state.db')
            self._state_db_path = Path(state_path_value)
            self._state_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_db = sqlite3.connect(self._state_db_path, check_same_thread=False)
            self._state_db.row_factory = sqlite3.Row
            with self._state_lock:
                self._state_db.execute("PRAGMA journal_mode=WAL;")
                self._state_db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cooldowns (
                        key TEXT NOT NULL,
                        bot TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        PRIMARY KEY (key, bot)
                    )
                    """
                )
                self._state_db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS outcomes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bot TEXT NOT NULL,
                        signal_key TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        option_ticker TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        target1 REAL NOT NULL,
                        target2 REAL NOT NULL,
                        target3 REAL NOT NULL,
                        stop REAL NOT NULL,
                        breakeven REAL,
                        last_price REAL,
                        dte INTEGER,
                        posted_at TEXT NOT NULL,
                        last_updated TEXT NOT NULL,
                        hit_target1 INTEGER DEFAULT 0,
                        hit_target2 INTEGER DEFAULT 0,
                        hit_target3 INTEGER DEFAULT 0,
                        stopped_out INTEGER DEFAULT 0,
                        resolved INTEGER DEFAULT 0,
                        UNIQUE(bot, signal_key)
                    )
                    """
                )
                self._state_db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                    """
                )
                self._state_db.commit()
        except Exception as exc:
            logger.error(f"{self.name} failed to initialize state store: {exc}")
            self._state_db = None
            self._state_db_path = None

    def _state_execute(self, query: str, params: tuple = (), commit: bool = True):
        if not self._state_db:
            return None
        with self._state_lock:
            cursor = self._state_db.execute(query, params)
            if commit:
                self._state_db.commit()
            return cursor

    def _get_metadata(self, key: str) -> Optional[str]:
        cursor = self._state_execute("SELECT value FROM metadata WHERE key=?", (key,), commit=False)
        row = cursor.fetchone() if cursor else None
        return row["value"] if row else None

    def _set_metadata(self, key: str, value: str) -> None:
        self._state_execute(
            """
            INSERT INTO metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value)
        )

    def _record_signal_outcome(self, signal: Dict, exits: Dict) -> None:
        """Persist signal details for post-alert tracking."""
        if not self._state_db:
            return

        signal_key = signal.get('signal_key')
        option_ticker = signal.get('option_ticker')
        if not signal_key or not option_ticker:
            return

        entry_price = float(signal.get('ask') or 0.0)
        target1 = float(exits.get('target1') or 0.0)
        target2 = float(exits.get('target2') or 0.0)
        target3 = float(exits.get('target3') or 0.0)
        stop_loss = float(exits.get('stop_loss') or 0.0)
        breakeven = exits.get('breakeven_trigger')
        breakeven_value = float(breakeven) if breakeven is not None else None
        posted_at = datetime.utcnow().isoformat()
        self._state_execute(
            """
            INSERT INTO outcomes (
                bot, signal_key, symbol, option_ticker, direction,
                entry_price, target1, target2, target3, stop, breakeven, last_price, dte,
                posted_at, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bot, signal_key) DO UPDATE SET
                entry_price=excluded.entry_price,
                target1=excluded.target1,
                target2=excluded.target2,
                target3=excluded.target3,
                stop=excluded.stop,
                breakeven=excluded.breakeven,
                last_price=excluded.last_price,
                dte=excluded.dte,
                last_updated=excluded.last_updated
            """,
            (
                self.name,
                signal_key,
                signal.get('ticker'),
                option_ticker,
                signal.get('type'),
                entry_price,
                target1,
                target2,
                target3,
                stop_loss,
                breakeven_value,
                entry_price,
                signal.get('days_to_expiry'),
                posted_at,
                posted_at
            )
        )

    def _fetch_pending_outcomes(self) -> List[sqlite3.Row]:
        cursor = self._state_execute(
            "SELECT * FROM outcomes WHERE bot=? AND resolved=0",
            (self.name,),
            commit=False
        )
        return cursor.fetchall() if cursor else []

    def _update_outcome_status(self, outcome_id: int, updates: Dict[str, Any]) -> None:
        if not updates or not self._state_db:
            return
        updates['last_updated'] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{column}=?" for column in updates.keys())
        params = list(updates.values())
        params.append(outcome_id)
        self._state_execute(
            f"UPDATE outcomes SET {set_clause} WHERE id=?",
            tuple(params)
        )

    def _summarize_outcomes(self, days: int = 7) -> Dict[str, Any]:
        """Aggregate recent outcome performance for reporting."""
        summary = {
            'signals': 0,
            'hit_target1': 0,
            'hit_target2': 0,
            'hit_target3': 0,
            'stopped_out': 0,
            'win_rate': 0.0,
            'expected_gain': 0.0
        }
        if not self._state_db:
            return summary

        threshold = (datetime.utcnow() - timedelta(days=days)).isoformat()
        cursor = self._state_execute(
            """
            SELECT
                COUNT(*) AS signals,
                SUM(hit_target1) AS hit_target1,
                SUM(hit_target2) AS hit_target2,
                SUM(hit_target3) AS hit_target3,
                SUM(stopped_out) AS stopped_out
            FROM outcomes
            WHERE bot=? AND posted_at >= ?
            """,
            (self.name, threshold),
            commit=False
        )
        row = cursor.fetchone() if cursor else None
        if not row or not row["signals"]:
            return summary

        signals = row["signals"] or 0
        hit_t1 = row["hit_target1"] or 0
        hit_t2 = row["hit_target2"] or 0
        hit_t3 = row["hit_target3"] or 0
        stopped = row["stopped_out"] or 0

        summary['signals'] = signals
        summary['hit_target1'] = hit_t1
        summary['hit_target2'] = hit_t2
        summary['hit_target3'] = hit_t3
        summary['stopped_out'] = stopped
        summary['win_rate'] = hit_t1 / signals if signals else 0.0

        # Approximate blended gain based on target ladder assumptions (in multiples of entry risk).
        expected_gain = (
            (hit_t3 * 3.0) +
            ((hit_t2 - hit_t3) * 1.5) +
            ((hit_t1 - hit_t2) * 0.75) -
            (stopped * 0.30)
        )
        summary['expected_gain'] = expected_gain / signals if signals else 0.0
        return summary

    def _maybe_flag_symbol(self, symbol: str) -> None:
        """Log symbols with consistently poor performance for manual review."""
        if not self._state_db or not symbol or symbol in self._low_performers:
            return

        min_samples = getattr(Config, 'PERFORMANCE_SYMBOL_MIN_OBS', 20)
        min_win_rate = getattr(Config, 'PERFORMANCE_SYMBOL_MIN_WIN', 0.2)
        cursor = self._state_execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(hit_target1) AS wins
            FROM outcomes
            WHERE bot=? AND symbol=?
            """,
            (self.name, symbol),
            commit=False
        )
        row = cursor.fetchone() if cursor else None
        if not row:
            return

        total = row["total"] or 0
        if total < min_samples:
            return
        wins = row["wins"] or 0
        win_rate = wins / total if total else 0.0
        if win_rate < min_win_rate:
            logger.warning(
                f"{self.name} low-performing symbol detected: {symbol} "
                f"(win rate {win_rate:.1%} over {total} signals)"
            )
            self._low_performers.add(symbol)

    # =========================================================================
    # ORAKL v3.0 Brain Validation Methods
    # =========================================================================
    
    async def validate_signal(
        self,
        symbol: str,
        premium: float,
        option_size: int,
        sentiment: str,
        sip_timestamp: Optional[int] = None
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Run the 'Brain' checks on a potential signal before alerting.
        
        This validates signals through:
        1. HedgeHunter - Checks if the trade is hedged with opposing stock
        2. ContextManager - Gets market regime (Gamma Exposure) context
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL')
            premium: Total premium of the trade in dollars
            option_size: Number of contracts
            sentiment: 'bullish' or 'bearish' - apparent direction
            sip_timestamp: Optional SIP timestamp in nanoseconds (for hedge check)
        
        Returns:
            Tuple of (is_valid, metadata_dict)
            - is_valid: True if signal should be alerted, False if filtered
            - metadata: Dict with 'hedge_status', 'market_context', etc.
        """
        metadata = {
            "hedge_status": "SKIPPED",
            "hedge_reason": "",
            "market_context": {},
            "regime": "NEUTRAL",
            "flip_level": 0,
            "net_gex": 0,
            "G": 0.5,
            "brain_validated": False
        }
        
        # 1. Hedge Check (Only for Whale Trades with timestamp)
        min_premium = getattr(Config, 'HEDGE_CHECK_MIN_PREMIUM', 500000)
        if self.hedge_hunter and premium >= min_premium and sip_timestamp:
            try:
                is_hedged, reason = await self.hedge_hunter.check_hedge(
                    symbol=symbol,
                    option_ts_nanos=sip_timestamp,
                    option_size=option_size,
                    sentiment=sentiment,
                    premium=premium
                )
                
                if is_hedged:
                    logger.info(f"🚫 {self.name} Filtered Synthetic {symbol}: {reason}")
                    metadata["hedge_status"] = "HEDGED"
                    metadata["hedge_reason"] = reason
                    return False, metadata
                
                metadata["hedge_status"] = "✅ VERIFIED UNHEDGED"
                metadata["hedge_reason"] = reason
                metadata["brain_validated"] = True
                
            except Exception as e:
                logger.warning(f"[{self.name}] HedgeHunter check failed for {symbol}: {e}")
                metadata["hedge_status"] = "CHECK_FAILED"
                metadata["hedge_reason"] = str(e)
        
        # 2. Context Check (Get market regime)
        if self.context_manager:
            try:
                context = self.context_manager.get_context(symbol)
                metadata["market_context"] = context
                metadata["regime"] = context.get('regime', 'NEUTRAL')
                metadata["flip_level"] = context.get('flip_level', 0)
                metadata["net_gex"] = context.get('net_gex', 0)
                metadata["G"] = context.get('G', 0.5)
                metadata["call_wall"] = context.get('call_wall', 0)
                metadata["put_wall"] = context.get('put_wall', 0)
                metadata["brain_validated"] = True
            except Exception as e:
                logger.warning(f"[{self.name}] ContextManager check failed for {symbol}: {e}")
        
        return True, metadata
    
    def get_brain_status(self) -> Dict[str, Any]:
        """Get status of Brain modules for this bot"""
        return {
            "hedge_hunter_enabled": self.hedge_hunter is not None,
            "context_manager_enabled": self.context_manager is not None,
            "hedge_check_min_premium": getattr(Config, 'HEDGE_CHECK_MIN_PREMIUM', 500000)
        }

    async def start(self):
        """Start the bot with enhanced error handling and monitoring"""
        if self.running:
            logger.warning(f"{self.name} already running")
            return

        if self._state_db is None:
            self._init_state_store()

        self.running = True
        self.metrics.start_time = datetime.now()
        
        # Initialize session with timeout
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        
        logger.info(f"{self.name} started - scanning every {self.scan_interval}s")

        # Start health check task
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        # Start main scanning loop
        self._scan_task = asyncio.create_task(self._scan_loop())
        
        try:
            # Wait for tasks
            await asyncio.gather(
                self._scan_task,
                self._health_check_task
            )
        except asyncio.CancelledError:
            logger.info(f"{self.name} tasks cancelled")
        finally:
            await self._cleanup()

    async def stop(self):
        """Stop the bot gracefully"""
        logger.info(f"Stopping {self.name}...")
        self.running = False
        
        # Cancel tasks
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
        
        # Wait for cleanup
        await self._cleanup()
        logger.info(f"{self.name} stopped")

    def should_run_now(self) -> bool:
        """
        Determine if the bot should execute a scan right now.
        Default implementation limits scanning to regular US market hours.
        Override in subclasses for custom trading windows.
        """
        return MarketHours.is_market_open(include_extended=False)

    def _inactive_sleep_duration(self) -> int:
        """
        Determine how long to sleep between checks when the bot is outside its active window.
        Uses a minimum of 60 seconds so we are responsive at the open without spamming logs overnight.
        """
        return max(min(self.scan_interval, 300), 60)

    async def _scan_loop(self):
        """Main scanning loop with error recovery"""
        recovery_attempts = 0
        while True:  # Keep running even if self.running becomes False
            try:
                # Check if we need to restart
                if not self.running and recovery_attempts < 3:
                    recovery_attempts += 1
                    logger.info(f"{self.name} attempting auto-recovery (attempt {recovery_attempts}/3)...")
                    await asyncio.sleep(60)  # Wait 1 minute before recovery
                    self._consecutive_errors = 0  # Reset error counter
                    self.running = True  # Restart
                    logger.info(f"{self.name} auto-recovery successful")
                
                if not self.running and recovery_attempts >= 3:
                    logger.error(f"{self.name} failed to recover after 3 attempts, stopping permanently")
                    break
                    
                if not self.should_run_now():
                    sleep_time = self._inactive_sleep_duration()
                    logger.debug(f"{self.name} outside active trading window, sleeping {sleep_time}s")
                    
                    # Fix: Update last scan time even when skipping to keep health check happy
                    # This prevents "unhealthy" status during extended market closures
                    self.metrics.last_scan_time = datetime.now()
                    
                    await asyncio.sleep(sleep_time)
                    continue

                scan_start = time.time()
                
                # Perform scan
                await self._perform_scan()
                
                # Record metrics
                scan_duration = time.time() - scan_start
                self.metrics.scan_durations.append(scan_duration)
                self.metrics.scan_count += 1
                self.metrics.last_scan_time = datetime.now()
                
                # Reset error counter and recovery attempts on success
                self._consecutive_errors = 0
                recovery_attempts = 0
                
                # Wait for next scan
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                await self._handle_scan_error(e)
                
                # Conservative exponential backoff on errors (max 5 minutes)
                backoff_time = min(30 * (1.5 ** self._consecutive_errors), 300)
                logger.warning(f"{self.name} backing off for {int(backoff_time)}s after error")
                await asyncio.sleep(backoff_time)
            
            # Periodic cleanup (approx every scan)
            self._cleanup_cooldowns()
    
    async def _perform_scan(self):
        """Perform a single scan with generous timeout"""
        try:
            # Add timeout to prevent hanging - adaptive based on symbol timeout and concurrency
            watchlist_size = len(getattr(self, 'watchlist', [])) if hasattr(self, 'watchlist') else 100
            concurrency = max(1, self.concurrency_limit)
            # Estimate batches and total time using per-symbol guardrail
            num_batches = max(1, math.ceil(watchlist_size / concurrency))
            timeout_duration = num_batches * (self.symbol_scan_timeout + 2) + 60  # small buffer per batch + global buffer
            timeout_duration = max(180, min(timeout_duration, 600))  # keep between 3 and 10 minutes
            scan_start = time.time()
            await asyncio.wait_for(
                self.scan_and_post(),
                timeout=timeout_duration
            )
            duration = time.time() - scan_start
            logger.info("%s scan completed in %.1fs (timeout %.0fs)", self.name, duration, timeout_duration)
        except asyncio.TimeoutError:
            logger.error("%s scan hit timeout after %.0fs (limit %.0fs)", self.name, time.time() - scan_start, timeout_duration)
            raise BotException(f"{self.name} scan timeout exceeded after {timeout_duration}s")
    
    async def _handle_scan_error(self, error: Exception):
        """Handle scan errors with tracking"""
        self._consecutive_errors += 1
        self.metrics.error_count += 1
        self.metrics.last_error_time = datetime.now()
        
        # Store error details
        await self._error_history.append({
            'timestamp': datetime.now(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'consecutive_count': self._consecutive_errors
        })
        
        logger.error(f"{self.name} scan error ({self._consecutive_errors}/{self._max_consecutive_errors}): {error}")
        
        # Check if we should stop due to too many errors
        if self._consecutive_errors >= self._max_consecutive_errors:
            logger.critical(f"{self.name} stopping due to {self._consecutive_errors} consecutive errors")
            self.running = False
            # Note: Will be auto-restarted by health check or scan loop
    
    async def _health_check_loop(self):
        """Periodic health check loop"""
        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute
                health = await self.get_health()
                
                if not health['healthy']:
                    logger.warning(f"{self.name} health check failed: {health}")
                    
            except Exception as e:
                logger.error(f"{self.name} health check error: {e}")
    
    async def _cleanup(self):
        """Clean up resources"""
        if self.session and not self.session.closed:
            try:
                await self.session.close()
                # Give connector time to close properly
                await asyncio.sleep(0.25)
            except Exception as e:
                logger.warning(f"{self.name} error closing session: {e}")
            finally:
                self.session = None
        if self._state_db:
            with self._state_lock:
                try:
                    self._state_db.close()
                except Exception as exc:
                    logger.warning(f"{self.name} error closing state DB: {exc}")
                finally:
                    self._state_db = None
    
    async def scan_and_post(self):
        """Default concurrent scanning implementation with bounded concurrency"""
        if not hasattr(self, '_scan_symbol'):
            raise NotImplementedError("Either implement scan_and_post or _scan_symbol")

        full_watchlist = getattr(self, 'watchlist', [])
        batch_watchlist = full_watchlist
        batch_limit = getattr(self, 'scan_batch_size', 0)
        if batch_limit and len(full_watchlist) > batch_limit:
            batches = (len(full_watchlist) + batch_limit - 1) // batch_limit
            batch_index = self.metrics.scan_count % batches
            start = batch_index * batch_limit
            batch_watchlist = full_watchlist[start:start + batch_limit]
            logger.info(
                "%s starting concurrent scan batch %d/%d: %d of %d symbols (max %d concurrent)",
                self.name,
                batch_index + 1,
                batches,
                len(batch_watchlist),
                len(full_watchlist),
                self.concurrency_limit,
            )
        else:
            logger.info(
                "%s starting concurrent scan of %d symbols (max %d concurrent)",
                self.name,
                len(batch_watchlist),
                self.concurrency_limit,
            )

        watchlist = batch_watchlist
        total_symbols = len(watchlist)

        if total_symbols == 0:
            logger.debug(f"{self.name} watchlist empty, skipping scan")
            return

        semaphore = asyncio.Semaphore(max(1, self.concurrency_limit))
        all_signals: List[Dict] = []

        async def run_symbol(symbol: str):
            async with semaphore:
                return await self._scan_symbol_safe(symbol)

        results = []
        batch_size = max(1, self.concurrency_limit)
        for offset in range(0, total_symbols, batch_size):
            batch = watchlist[offset:offset + batch_size]
            batch_results = await asyncio.gather(
                *(run_symbol(symbol) for symbol in batch),
                return_exceptions=True
            )
            results.extend(batch_results)

        for result in results:
            if isinstance(result, list):
                all_signals.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"{self.name} scan error: {result}")

        logger.info(f"{self.name} found {len(all_signals)} signals")
        for signal in all_signals:
            try:
                await self._post_signal(signal)
            except Exception as e:
                logger.error(f"{self.name} error posting signal: {e}")
    
    async def _scan_symbol_safe(self, symbol: str):
        """Safely scan a symbol with error handling"""
        try:
            return await asyncio.wait_for(
                self._scan_symbol(symbol),
                timeout=self.symbol_scan_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"{self.name} - {symbol} scan timed out after {self.symbol_scan_timeout}s; skipping")
            return []
        except Exception as e:
            logger.error(f"{self.name} error scanning {symbol}: {e}")
            return []

    @exponential_backoff_retry(
        max_retries=3,
        base_delay=1.0,
        exceptions=(aiohttp.ClientError, asyncio.TimeoutError)
    )
    async def post_to_discord(self, embed: Dict) -> bool:
        """
        Post embed to Discord webhook with retry logic

        Args:
            embed: Discord embed dictionary
            
        Returns:
            True if successful, False otherwise
        """
        if not self.session:
            logger.error("Session not initialized")
            return False

        try:
            # Validate embed structure
            if not isinstance(embed, dict) or 'title' not in embed:
                logger.error(f"Invalid embed structure: {embed}")
                return False

            # Safety check for Index Whale Bot score threshold
            if self.name == "Index Whale Bot":
                min_score = getattr(self, "min_score", None)
                if isinstance(min_score, (int, float)):
                    embed_fields = embed.get("fields") or []
                    score_found = False
                    for field in embed_fields:
                        value = field.get("value")
                        if not isinstance(value, str):
                            continue
                        if "Score" in value:
                            score_found = True
                        if "**" in value and "/100" in value:
                            try:
                                score_segment = value.split("**", 1)[1]
                                score_text = score_segment.split("/100", 1)[0]
                                score_value = float(score_text.strip())
                                if score_value < min_score:
                                    logger.warning(
                                        "%s blocked low-score embed (%.1f < %.1f)",
                                        self.name,
                                        score_value,
                                        min_score,
                                    )
                                    return False
                            except (IndexError, ValueError):
                                continue
                    if not score_found:
                        logger.debug(
                            "%s embed lacked score field; allowing post but continuing guard",
                            self.name,
                        )

            payload = {
                "embeds": [embed],
                "username": f"ORAKL {self.name}"
            }

            # Lazily create lock (safe in both scan + event-driven modes).
            if self._webhook_post_lock is None:
                self._webhook_post_lock = asyncio.Lock()

            # Single-file posts per bot + pacing prevents 429 storms when many events trigger at once.
            async with self._webhook_post_lock:
                max_attempts = 5
                for attempt in range(1, max_attempts + 1):
                    # Enforce a minimum spacing between posts to this webhook.
                    now = time.monotonic()
                    sleep_for = (self._last_webhook_post_ts + self._webhook_min_interval_seconds) - now
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)

                    async with self.session.post(self.webhook_url, json=payload) as response:
                        if response.status == 204:
                            self._last_webhook_post_ts = time.monotonic()
                            logger.debug(f"{self.name} posted successfully")
                            self.metrics.webhook_success_count += 1
                            self.metrics.last_signal_time = datetime.now()
                            self.metrics.signal_count += 1
                            return True

                        error_text = await response.text()
                        logger.error(f"{self.name} webhook error {response.status}: {error_text}")
                        self.metrics.webhook_failure_count += 1

                        if response.status == 429:  # Rate limited
                            # Discord returns fractional seconds in either header or body
                            retry_after_header = response.headers.get('X-RateLimit-Reset-After')
                            retry_after = None
                            if retry_after_header:
                                try:
                                    retry_after = float(retry_after_header)
                                except ValueError:
                                    retry_after = None
                            if retry_after is None:
                                try:
                                    error_json = json.loads(error_text)
                                    retry_after = float(error_json.get('retry_after', 1.0))
                                except (ValueError, TypeError, json.JSONDecodeError):
                                    retry_after = 1.0
                            retry_after = max(retry_after, 0.1)
                            logger.warning(
                                "%s rate limited by Discord; sleeping for %.2fs before retry (attempt %d/%d)",
                                self.name,
                                retry_after,
                                attempt,
                                max_attempts,
                            )
                            await asyncio.sleep(retry_after + 0.10)  # small safety buffer
                            continue

                        return False

                return False
        except Exception as e:
            logger.error(f"{self.name} post error: {e}")
            self.metrics.webhook_failure_count += 1
            return False

    def _sanitize_value(self, value, placeholder: str = "--") -> str:
        """Sanitize value for Discord embed"""
        if value is None:
            return placeholder
        
        # Handle numeric values
        if isinstance(value, (int, float)):
            # Check for NaN
            if value != value:
                return placeholder
            # Check for infinity
            if value == float('inf') or value == float('-inf'):
                return placeholder
            # Format floats nicely
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)
        
        # Convert to string and ensure not empty
        str_value = str(value)
        return str_value if str_value.strip() else placeholder

    def create_embed(
        self,
        title: str,
        description: str,
        color: int,
        fields: list = None,
        footer: str = None,
        thumbnail_url: str = None,
        author: Dict = None
    ) -> Dict:
        """
        Create Discord embed with validation

        Args:
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: List of field dicts
            footer: Footer text
            thumbnail_url: Thumbnail image URL
            author: Author information dict

        Returns:
            Discord embed dictionary
        """
        # Validate and sanitize inputs
        title = self._sanitize_value(title, placeholder="Alert")
        if not title or title.strip() == "":
            title = "Alert"
        title = title[:256]
        
        description = self._sanitize_value(description, placeholder="")
        if description and len(description) > 4096:
            description = description[:4093] + "..."
        
        # Ensure color is valid
        if not isinstance(color, int) or color < 0 or color > 0xFFFFFF:
            color = 0x0099ff  # Default blue
        
        embed = {
            "title": title,
            "description": description or "",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": []
        }
        
        # Add fields with validation
        if fields:
            for field in fields[:25]:  # Discord limit is 25 fields
                if isinstance(field, dict) and 'name' in field and 'value' in field:
                    # Sanitize field values
                    field_name = self._sanitize_value(field['name'], placeholder=" ")[:256]
                    field_value = self._sanitize_value(field['value'])[:1024]
                    
                    # Skip fields with no meaningful content
                    if (not field_value or field_value.strip() == "--") and (not field_name or field_name.strip() == ""):
                        continue
                    if not field_value or field_value.strip() == "--":
                        continue
                    
                    embed["fields"].append({
                        "name": field_name if field_name.strip() else " ",
                        "value": field_value,
                        "inline": bool(field.get('inline', True))
                    })

        if footer:
            embed["footer"] = {"text": self._sanitize_value(footer)[:2048]}
            
        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}
            
        if author:
            embed["author"] = author

        return embed
    
    def _cooldown_active(self, key: str, cooldown_seconds: int = 900) -> bool:
        """Check whether a signal is within cooldown window"""
        now = datetime.now()
        last_seen = self._cooldowns.get(key)
        if last_seen is None and self._state_db:
            cursor = self._state_execute(
                "SELECT timestamp FROM cooldowns WHERE key=? AND bot=?",
                (key, self.name),
                commit=False
            )
            row = cursor.fetchone() if cursor else None
            if row:
                try:
                    last_seen = datetime.fromisoformat(row["timestamp"])
                    self._cooldowns[key] = last_seen
                except ValueError:
                    last_seen = None
        if last_seen and (now - last_seen).total_seconds() < cooldown_seconds:
            return True
        return False

    def _cleanup_cooldowns(self, max_age_hours: int = 24) -> None:
        """Remove old cooldown entries to prevent memory leaks."""
        try:
            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            # Create list of keys to remove to avoid runtime error during iteration
            to_remove = [k for k, v in self._cooldowns.items() if v < cutoff]
            
            for k in to_remove:
                del self._cooldowns[k]
                
            if to_remove and len(to_remove) > 100:
                logger.debug(f"{self.name} cleaned up {len(to_remove)} old cooldown entries")
                
        except Exception as e:
            logger.error(f"{self.name} error cleaning cooldowns: {e}")

    def _mark_cooldown(self, key: str) -> None:
        """Mark a signal as posted for cooldown tracking"""
        timestamp = datetime.now()
        self._cooldowns[key] = timestamp
        if self._state_db:
            self._state_execute(
                """
                INSERT INTO cooldowns (key, bot, timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(key, bot) DO UPDATE SET timestamp=excluded.timestamp
                """,
                (key, self.name, timestamp.isoformat())
            )

    def _log_skip(self, symbol: str, reason: str) -> None:
        """Record skip reasons for quick diagnostics"""
        entry = {
            'time': datetime.now().isoformat(timespec='seconds'),
            'symbol': symbol,
            'reason': reason
        }
        self._skip_records.append(entry)
        logger.debug(f"{self.name} skip {symbol}: {reason}")

    def _count_filter(self, reason: str, symbol: Optional[str] = None, sample_record: bool = False) -> None:
        """
        Count a filter/skip reason and periodically emit an INFO summary.

        Use this for very frequent early-return filters (e.g., premium too small) where
        per-event debug logs would be too noisy.
        """
        if not reason:
            reason = "unknown"
        self._filter_counts[reason] += 1

        # Optionally store a sampled record for deeper inspection.
        if sample_record and symbol:
            self._log_skip(symbol, reason)

        self._maybe_report_filter_counts()

    def _maybe_report_filter_counts(self) -> None:
        """Emit periodic filter summaries at INFO and reset counts."""
        now = time.time()
        if (now - self._filter_last_report_ts) < self._filter_report_interval_seconds:
            return

        if self._filter_counts:
            top = sorted(self._filter_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
            summary = ", ".join([f"{k}={v}" for k, v in top])
            logger.info(f"{self.name} filter summary (last ~{self._filter_report_interval_seconds}s): {summary}")

        self._filter_counts.clear()
        self._filter_last_report_ts = now
    
    def get_skip_records(self, limit: int = 50) -> List[Dict[str, str]]:
        """
        Get recent skip records for diagnostics.
        
        Args:
            limit: Maximum number of records to return (default 50)
            
        Returns:
            List of skip record dictionaries with time, symbol, and reason
        """
        records = list(self._skip_records)
        return records[-limit:] if len(records) > limit else records
    
    async def get_health(self) -> Dict[str, Any]:
        """
        Get bot health status
        
        Returns:
            Health status dictionary
        """
        if not self.running:
            return {
                'healthy': False,
                'status': 'stopped',
                'name': self.name,
                'metrics': self._get_metrics_summary()
            }
        
        # If the bot hasn't completed an initial scan yet, treat it as starting up
        if self.metrics.scan_count == 0 or not self.metrics.last_scan_time:
            return {
                'healthy': True,
                'status': 'starting',
                'name': self.name,
                'scan_interval': self.scan_interval,
                'time_since_last_scan': None,
                'consecutive_errors': self._consecutive_errors,
                'metrics': self._get_metrics_summary()
            }

        # Calculate health indicators once scans are underway
        now = datetime.now()
        time_since_last_scan = (
            (now - self.metrics.last_scan_time).total_seconds()
            if self.metrics.last_scan_time else float('inf')
        )
        
        # Health criteria - bot is healthy if:
        # 1. Running and scans are happening on schedule
        # 2. Not experiencing consecutive errors
        # 3. Either has successful webhooks OR hasn't needed to send any yet
        # Use max(scan_interval * 3, 180) for tolerance - ensures at least 3 min grace
        # This prevents false "unhealthy" states for high-frequency bots (e.g., 60s interval)
        health_tolerance = max(self.scan_interval * 3, 180)
        scan_healthy = time_since_last_scan < health_tolerance
        error_healthy = self._consecutive_errors < 5

        # Webhook health: if we've sent signals, check success rate
        # If no signals sent yet (e.g. market closed), that's still healthy
        total_webhook_attempts = self.metrics.webhook_success_count + self.metrics.webhook_failure_count
        if total_webhook_attempts > 0:
            webhook_healthy = self.metrics.webhook_failure_count < self.metrics.webhook_success_count * 0.1
        else:
            webhook_healthy = True  # No signals yet is okay

        healthy = scan_healthy and error_healthy and webhook_healthy
        
        return {
            'healthy': healthy,
            'status': 'running',
            'name': self.name,
            'scan_interval': self.scan_interval,
            'time_since_last_scan': time_since_last_scan,
            'consecutive_errors': self._consecutive_errors,
            'metrics': self._get_metrics_summary()
        }
    
    def _get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get summary of bot metrics
        
        Returns:
            Metrics summary dictionary
        """
        uptime = (datetime.now() - self.metrics.start_time).total_seconds()
        
        # Calculate average scan duration
        avg_scan_duration = (
            sum(self.metrics.scan_durations) / len(self.metrics.scan_durations)
            if self.metrics.scan_durations else 0
        )
        
        return {
            'uptime_seconds': uptime,
            'scan_count': self.metrics.scan_count,
            'signal_count': self.metrics.signal_count,
            'error_count': self.metrics.error_count,
            'error_rate': self.metrics.error_count / max(self.metrics.scan_count, 1),
            'avg_scan_duration': avg_scan_duration,
            'webhook_success_rate': (
                self.metrics.webhook_success_count / 
                max(self.metrics.webhook_success_count + self.metrics.webhook_failure_count, 1)
            ),
            'last_scan_time': self.metrics.last_scan_time.isoformat() if self.metrics.last_scan_time else None,
            'last_signal_time': self.metrics.last_signal_time.isoformat() if self.metrics.last_signal_time else None,
            'last_error_time': self.metrics.last_error_time.isoformat() if self.metrics.last_error_time else None
        }
    
    def get_status(self) -> str:
        """
        Get bot status string
        
        Returns:
            Status string
        """
        if not self.running:
            return "⚫ Stopped"
        elif self._consecutive_errors >= 5:
            return "🔴 Error"
        elif self._consecutive_errors > 0:
            return "🟡 Warning"
        else:
            return "🟢 Running"
    
    def apply_quality_filters(self, signal: Dict) -> bool:
        """
        Universal quality filters for all options signals
        
        Args:
            signal: Signal dictionary with trade details
            
        Returns:
            True if signal passes all quality checks, False otherwise
        """
        try:
            # Check bid-ask spread if available
            if 'bid_ask_spread' in signal:
                if signal['bid_ask_spread'] > 0.10:  # >10% spread
                    logger.debug(f"{self.name} - Rejected signal: Spread too wide ({signal['bid_ask_spread']*100:.1f}%)")
                    return False
            
            # Verify open interest
            if 'open_interest' in signal:
                if signal.get('open_interest', 0) < 100:
                    logger.debug(f"{self.name} - Rejected signal: Low OI ({signal.get('open_interest', 0)})")
                    return False
            
            # Validate volume/OI ratio
            if 'volume' in signal and 'open_interest' in signal:
                volume = signal.get('volume', 0)
                oi = signal.get('open_interest', 1)
                volume_oi_ratio = volume / oi if oi > 0 else 0
                
                if volume_oi_ratio < 0.5:  # Volume should be at least 50% of OI
                    logger.debug(f"{self.name} - Rejected signal: Low volume/OI ratio ({volume_oi_ratio:.2f})")
                    return False
            
            # Ensure smart money percentage (if available)
            if 'smart_money_volume' in signal and 'volume' in signal:
                smart_money_pct = signal.get('smart_money_volume', 0) / signal.get('volume', 1)
                if smart_money_pct < 0.6:  # At least 60% smart money
                    logger.debug(f"{self.name} - Rejected signal: Low smart money % ({smart_money_pct*100:.0f}%)")
                    return False
            
            # Check minimum premium threshold
            if 'premium' in signal:
                min_premium = 5000  # $5k minimum
                if signal.get('premium', 0) < min_premium:
                    logger.debug(f"{self.name} - Rejected signal: Premium below threshold (${signal.get('premium', 0):,.0f})")
                    return False
            
            # Greeks validation (if available)
            if 'delta' in signal:
                delta = abs(signal.get('delta', 0))
                if delta < 0.25 or delta > 0.75:  # Avoid deep OTM/ITM
                    logger.debug(f"{self.name} - Rejected signal: Delta out of range ({delta:.2f})")
                    return False
            
            # Days to expiry check
            if 'days_to_expiry' in signal:
                dte = signal.get('days_to_expiry', 0)
                if dte < 0:  # Expired
                    logger.debug(f"{self.name} - Rejected signal: Contract expired")
                    return False
            
            # All checks passed
            return True
            
        except Exception as e:
            logger.error(f"{self.name} - Error in quality filter: {e}")
            # On error, be conservative and reject
            return False
    
    def calculate_score(self, metrics: Dict[str, tuple], max_score: int = 100) -> int:
        """
        Generic scoring system for bot signals with configurable tiers

        Args:
            metrics: Dictionary of metric configurations
                    Format: {'metric_name': (value, [(threshold1, points1), (threshold2, points2), ...])}
                    Example: {'premium': (1500000, [(10000000, 50), (5000000, 45), (2500000, 40)])}
            max_score: Maximum possible score (default 100)

        Returns:
            Integer score (0-max_score)

        Example:
            score = self.calculate_score({
                'premium': (total_premium, [
                    (10000000, 50),  # $10M+ → 50 points
                    (5000000, 45),   # $5M+ → 45 points
                    (2500000, 40),   # $2.5M+ → 40 points
                    (1000000, 35)    # $1M+ → 35 points
                ]),
                'volume': (total_volume, [
                    (2000, 20),  # 2000+ → 20 points
                    (1000, 17),  # 1000+ → 17 points
                    (500, 14)    # 500+ → 14 points
                ])
            })
        """
        score = 0

        for metric_name, config in metrics.items():
            value, tiers = config

            # Find matching tier (highest threshold met)
            for threshold, points in tiers:
                if value >= threshold:
                    score += points
                    break  # Only award points for highest tier met

        return min(score, max_score)

    def create_signal_embed_with_disclaimer(self, title: str, description: str, color: int,
                                           fields: List[Dict], footer: str,
                                           disclaimer: str = "Please always do your own due diligence on top of these trade ideas.") -> Dict:
        """
        Create signal embed with automatic disclaimer field appended

        This is a convenience wrapper around create_embed() that automatically adds
        the standard disclaimer field at the end.

        Args:
            title: Embed title
            description: Embed description
            color: Hex color code (e.g., 0xFFD700 for gold)
            fields: List of field dictionaries
            footer: Footer text
            disclaimer: Disclaimer text (default: standard due diligence message)

        Returns:
            Discord embed dictionary

        Example:
            embed = self.create_signal_embed_with_disclaimer(
                title=f"🏆 {ticker} - Signal",
                description="High conviction trade",
                color=0xFFD700,
                fields=[
                    {"name": "Ticker", "value": ticker, "inline": True},
                    {"name": "Price", "value": f"${price:.2f}", "inline": True}
                ],
                footer="Bot Name | Signal Type"
            )
        """
        # Add disclaimer field
        fields_with_disclaimer = fields + [{
            "name": "",
            "value": disclaimer,
            "inline": False
        }]

        return self.create_embed(
            title=title,
            description=description,
            color=color,
            fields=fields_with_disclaimer,
            footer=footer
        )

    def rank_signals(self, signals: List[Dict]) -> List[Dict]:
        """
        Rank signals by quality and urgency
        
        Args:
            signals: List of signal dictionaries
            
        Returns:
            Sorted list of top signals
        """
        if not signals:
            return []
        
        try:
            for signal in signals:
                # Calculate urgency score based on time decay and momentum
                urgency = 0
                
                # Time decay factor (DTE)
                dte = signal.get('days_to_expiry', 99)
                if dte == 0:
                    urgency += 40
                elif dte == 1:
                    urgency += 25
                elif dte <= 3:
                    urgency += 15
                
                # Momentum acceleration
                if signal.get('momentum_accelerating', False):
                    urgency += 30
                
                # Volume surge
                volume_ratio = signal.get('volume_ratio', 1)
                if volume_ratio > 5:
                    urgency += 30
                elif volume_ratio > 3:
                    urgency += 20
                elif volume_ratio > 2:
                    urgency += 10
                
                # Directional conviction (for bullseye)
                conviction = signal.get('directional_conviction', 0)
                if conviction >= 0.90:
                    urgency += 20
                elif conviction >= 0.85:
                    urgency += 15
                elif conviction >= 0.80:
                    urgency += 10
                
                # Pattern strength (for scalps)
                pattern_strength = signal.get('pattern_strength', 0)
                if pattern_strength >= 90:
                    urgency += 25
                elif pattern_strength >= 85:
                    urgency += 20
                elif pattern_strength >= 80:
                    urgency += 15
                
                # Calculate priority score
                quality_score = signal.get('ai_score', signal.get('scalp_score', 50))
                signal['urgency_score'] = urgency
                signal['priority_score'] = (quality_score * 0.6) + (urgency * 0.4)
            
            # Sort by priority score and return top 3
            sorted_signals = sorted(signals, key=lambda x: x['priority_score'], reverse=True)
            
            # Log ranking results
            logger.info(f"{self.name} - Ranked {len(signals)} signals, returning top {min(3, len(sorted_signals))}")
            for i, sig in enumerate(sorted_signals[:3]):
                logger.debug(f"  #{i+1}: {sig.get('ticker')} - Priority: {sig['priority_score']:.1f} "
                           f"(Quality: {sig.get('ai_score', sig.get('scalp_score', 0))}, Urgency: {sig['urgency_score']})")
            
            return sorted_signals[:3]  # Return top 3 signals
            
        except Exception as e:
            logger.error(f"{self.name} - Error ranking signals: {e}")
            # Return original list on error
            return signals[:3]
