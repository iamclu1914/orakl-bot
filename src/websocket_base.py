"""
WebSocket Base Class for Real-Time Options/Stock Streaming
Replaces REST API polling with instant push-based updates
"""
import asyncio
import os
from typing import Callable, List, Set
from polygon import WebSocketClient
from polygon.websocket.models import WebSocketMessage, EquityTrade, EquityAgg, OptionsTrade
from datetime import datetime
import pytz
from src.utils.logger import logger


class PolygonWebSocketBase:
    """Base class for real-time streaming with automatic reconnection"""

    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self.api_key = os.getenv('POLYGON_API_KEY')
        self.watchlist = os.getenv('WATCHLIST', 'SPY,QQQ').split(',')

        # WebSocket client and state
        self.client = None
        self.connected = False
        self.subscribed_symbols: Set[str] = set()

        # Market hours (US Eastern Time)
        self.tz = pytz.timezone('America/New_York')

        # Deduplication cache
        self.seen_signals: Set[str] = set()
        self.cache_clear_interval = 300  # Clear cache every 5 minutes

    def is_market_hours(self) -> bool:
        """Check if market is open (9:30 AM - 4:00 PM ET, Mon-Fri)"""
        now = datetime.now(self.tz)

        # Check if weekend
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Check if within trading hours
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

        return market_open <= now <= market_close

    async def connect(self):
        """Connect to Polygon WebSocket with automatic reconnection"""
        try:
            logger.info(f"[{self.bot_name}] Connecting to Polygon WebSocket...")

            self.client = WebSocketClient(
                api_key=self.api_key,
                feed='delayed',  # Use 'delayed' for free tier, 'realtime' for paid
                market='options',  # Will be overridden in subclasses
                subscriptions=[]
            )

            # Register message handler
            self.client.on_message = self.on_message

            await self.client.connect()
            self.connected = True
            logger.info(f"[{self.bot_name}] WebSocket connected successfully")

        except Exception as e:
            logger.error(f"[{self.bot_name}] WebSocket connection failed: {e}")
            self.connected = False
            # Retry after 30 seconds
            await asyncio.sleep(30)
            await self.connect()

    async def subscribe_options_trades(self, symbols: List[str]):
        """Subscribe to real-time options trades for given symbols"""
        try:
            # Convert stock symbols to options wildcard subscriptions
            # Example: 'SPY' -> 'O:SPY*' (all SPY options contracts)
            option_patterns = [f"O:{symbol.strip()}*" for symbol in symbols]

            for pattern in option_patterns:
                await self.client.subscribe(pattern)
                self.subscribed_symbols.add(pattern)
                logger.info(f"[{self.bot_name}] Subscribed to options trades: {pattern}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Subscription failed: {e}")

    async def subscribe_stock_trades(self, symbols: List[str]):
        """Subscribe to real-time stock trades for given symbols"""
        try:
            for symbol in symbols:
                symbol = symbol.strip()
                await self.client.subscribe(f"T.{symbol}")
                self.subscribed_symbols.add(symbol)
                logger.info(f"[{self.bot_name}] Subscribed to stock trades: {symbol}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Subscription failed: {e}")

    async def subscribe_aggregates(self, symbols: List[str]):
        """Subscribe to 1-minute aggregate bars for given symbols"""
        try:
            for symbol in symbols:
                symbol = symbol.strip()
                await self.client.subscribe(f"AM.{symbol}")
                self.subscribed_symbols.add(symbol)
                logger.info(f"[{self.bot_name}] Subscribed to 1-min aggregates: {symbol}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Subscription failed: {e}")

    def on_message(self, msgs: List[WebSocketMessage]):
        """Handle incoming WebSocket messages - override in subclasses"""
        raise NotImplementedError("Subclasses must implement on_message()")

    def generate_signal_id(self, symbol: str, timestamp: int, trade_type: str) -> str:
        """Generate unique signal ID for deduplication"""
        return f"{symbol}_{timestamp}_{trade_type}"

    def is_duplicate_signal(self, signal_id: str) -> bool:
        """Check if signal already processed"""
        if signal_id in self.seen_signals:
            return True
        self.seen_signals.add(signal_id)
        return False

    async def clear_cache_periodically(self):
        """Clear signal cache every 5 minutes to prevent memory growth"""
        while True:
            await asyncio.sleep(self.cache_clear_interval)
            logger.info(f"[{self.bot_name}] Clearing signal cache ({len(self.seen_signals)} entries)")
            self.seen_signals.clear()

    async def monitor_connection(self):
        """Monitor WebSocket connection and reconnect if needed"""
        while True:
            await asyncio.sleep(60)

            if not self.connected:
                logger.warning(f"[{self.bot_name}] Connection lost, reconnecting...")
                await self.connect()

                # Re-subscribe after reconnection
                if hasattr(self, 'resubscribe'):
                    await self.resubscribe()

    async def run(self):
        """Main run loop - connect, subscribe, and handle messages"""
        try:
            # Connect to WebSocket
            await self.connect()

            # Subscribe to streams (implemented by subclasses)
            await self.subscribe()

            # Start background tasks
            cache_task = asyncio.create_task(self.clear_cache_periodically())
            monitor_task = asyncio.create_task(self.monitor_connection())

            logger.info(f"[{self.bot_name}] WebSocket streaming started - monitoring {len(self.watchlist)} symbols")

            # Keep running
            await asyncio.gather(cache_task, monitor_task)

        except Exception as e:
            logger.error(f"[{self.bot_name}] WebSocket run error: {e}")
            self.connected = False

    async def subscribe(self):
        """Subscribe to relevant streams - override in subclasses"""
        raise NotImplementedError("Subclasses must implement subscribe()")

    async def resubscribe(self):
        """Re-subscribe after reconnection - override in subclasses"""
        await self.subscribe()
