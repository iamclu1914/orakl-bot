"""Base class for auto-posting bots"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from abc import ABC, abstractmethod
import time
from dataclasses import dataclass, field
from collections import deque

from src.utils.exceptions import BotException, BotNotRunningException, WebhookException
from src.utils.resilience import exponential_backoff_retry, BoundedDeque
from src.utils.validation import DataValidator

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

    def __init__(self, webhook_url: str, name: str, scan_interval: int = 300):
        """
        Initialize base bot

        Args:
            webhook_url: Discord webhook URL
            name: Bot name
            scan_interval: Scan interval in seconds (default: 5 minutes)
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
        self._max_consecutive_errors = 10

    async def start(self):
        """Start the bot with enhanced error handling and monitoring"""
        if self.running:
            logger.warning(f"{self.name} already running")
            return

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

    async def _scan_loop(self):
        """Main scanning loop with error recovery"""
        while self.running:
            try:
                scan_start = time.time()
                
                # Perform scan
                await self._perform_scan()
                
                # Record metrics
                scan_duration = time.time() - scan_start
                self.metrics.scan_durations.append(scan_duration)
                self.metrics.scan_count += 1
                self.metrics.last_scan_time = datetime.now()
                
                # Reset error counter on success
                self._consecutive_errors = 0
                
                # Wait for next scan
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                await self._handle_scan_error(e)
                
                # Conservative exponential backoff on errors (max 5 minutes)
                backoff_time = min(30 * (1.5 ** self._consecutive_errors), 300)
                logger.warning(f"{self.name} backing off for {int(backoff_time)}s after error")
                await asyncio.sleep(backoff_time)
    
    async def _perform_scan(self):
        """Perform a single scan with generous timeout"""
        try:
            # Add timeout to prevent hanging - be generous for API calls
            timeout_duration = max(self.scan_interval * 2, 600)  # 2x interval or 10 min minimum
            await asyncio.wait_for(
                self.scan_and_post(),
                timeout=timeout_duration
            )
        except asyncio.TimeoutError:
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
            await self.session.close()
            self.session = None
    
    @abstractmethod
    async def scan_and_post(self):
        """Scan for signals and post to Discord - must be implemented by subclasses"""
        pass

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
            
            payload = {
                "embeds": [embed],
                "username": f"ORAKL {self.name}"
            }
            
            async with self.session.post(self.webhook_url, json=payload) as response:
                if response.status == 204:
                    logger.debug(f"{self.name} posted successfully")
                    self.metrics.webhook_success_count += 1
                    self.metrics.last_signal_time = datetime.now()
                    self.metrics.signal_count += 1
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"{self.name} webhook error {response.status}: {error_text}")
                    self.metrics.webhook_failure_count += 1
                    
                    if response.status == 429:  # Rate limited
                        retry_after = int(response.headers.get('X-RateLimit-Reset-After', 60))
                        raise WebhookException(
                            f"Discord rate limit hit, retry after {retry_after}s",
                            status_code=429
                        )
                    
                    return False
                    
        except WebhookException:
            raise  # Let retry decorator handle it
        except Exception as e:
            logger.error(f"{self.name} post error: {e}")
            self.metrics.webhook_failure_count += 1
            return False

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
        # Validate inputs
        if not title or len(title) > 256:
            raise ValueError(f"Title must be 1-256 characters, got {len(title) if title else 0}")
        
        if description and len(description) > 4096:
            description = description[:4093] + "..."
        
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
                    embed["fields"].append({
                        "name": str(field['name'])[:256],
                        "value": str(field['value'])[:1024],
                        "inline": field.get('inline', True)
                    })

        if footer:
            embed["footer"] = {"text": str(footer)[:2048]}
            
        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}
            
        if author:
            embed["author"] = author

        return embed
    
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
        
        # Calculate health indicators
        now = datetime.now()
        time_since_last_scan = (
            (now - self.metrics.last_scan_time).total_seconds()
            if self.metrics.last_scan_time else float('inf')
        )
        
        # Health criteria
        scan_healthy = time_since_last_scan < self.scan_interval * 2
        error_healthy = self._consecutive_errors < 5
        webhook_healthy = self.metrics.webhook_failure_count < self.metrics.webhook_success_count * 0.1
        
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
