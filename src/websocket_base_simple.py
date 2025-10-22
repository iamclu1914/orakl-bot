"""
Simple WebSocket Base for Polygon Real-Time Streaming
Uses websockets library for async connections
"""
import asyncio
import json
import os
from typing import List, Set
from datetime import datetime
import pytz
import websockets
from src.utils.logger import logger


class PolygonWebSocketSimple:
    """Simplified WebSocket base class using websockets library"""

    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self.api_key = os.getenv('POLYGON_API_KEY')
        self.watchlist = os.getenv('WATCHLIST', 'SPY,QQQ').split(',')

        # WebSocket connection
        self.ws = None
        self.connected = False

        # Market hours
        self.tz = pytz.timezone('America/New_York')

        # Deduplication
        self.seen_signals: Set[str] = set()

        # Polygon WebSocket URL (delayed feed for free tier)
        self.ws_url = "wss://delayed.polygon.io/stocks"

    def is_market_hours(self) -> bool:
        """Check if market is open"""
        now = datetime.now(self.tz)
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close

    async def connect(self):
        """Connect to Polygon WebSocket"""
        try:
            logger.info(f"[{self.bot_name}] Connecting to {self.ws_url}...")
            self.ws = await websockets.connect(self.ws_url)
            self.connected = True

            # Authenticate
            auth_message = {
                "action": "auth",
                "params": self.api_key
            }
            await self.ws.send(json.dumps(auth_message))

            # Wait for auth response
            response = await self.ws.recv()
            response_data = json.loads(response)

            if response_data[0].get('status') == 'auth_success':
                logger.info(f"[{self.bot_name}] WebSocket authenticated successfully")
                return True
            else:
                logger.error(f"[{self.bot_name}] Authentication failed: {response_data}")
                return False

        except Exception as e:
            logger.error(f"[{self.bot_name}] Connection failed: {e}")
            self.connected = False
            return False

    async def subscribe_trades(self, symbols: List[str]):
        """Subscribe to stock trades"""
        try:
            subscribe_message = {
                "action": "subscribe",
                "params": ",".join([f"T.{s.strip()}" for s in symbols])
            }
            await self.ws.send(json.dumps(subscribe_message))
            logger.info(f"[{self.bot_name}] Subscribed to {len(symbols)} stock trades")
        except Exception as e:
            logger.error(f"[{self.bot_name}] Subscribe failed: {e}")

    async def subscribe_aggregates(self, symbols: List[str]):
        """Subscribe to 1-minute aggregates"""
        try:
            subscribe_message = {
                "action": "subscribe",
                "params": ",".join([f"AM.{s.strip()}" for s in symbols])
            }
            await self.ws.send(json.dumps(subscribe_message))
            logger.info(f"[{self.bot_name}] Subscribed to {len(symbols)} 1-min aggregates")
        except Exception as e:
            logger.error(f"[{self.bot_name}] Subscribe failed: {e}")

    async def listen(self):
        """Listen for WebSocket messages"""
        try:
            while self.connected:
                message = await self.ws.recv()
                data = json.loads(message)

                # Process messages
                for msg in data:
                    ev = msg.get('ev')

                    # Skip status messages
                    if ev == 'status':
                        continue

                    # Handle trade messages
                    elif ev == 'T':
                        await self.on_trade(msg)

                    # Handle aggregate messages
                    elif ev == 'AM':
                        await self.on_aggregate(msg)

        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"[{self.bot_name}] WebSocket connection closed")
            self.connected = False
        except Exception as e:
            logger.error(f"[{self.bot_name}] Listen error: {e}")
            self.connected = False

    async def on_trade(self, msg: dict):
        """Override in subclasses"""
        pass

    async def on_aggregate(self, msg: dict):
        """Override in subclasses"""
        pass

    def generate_signal_id(self, symbol: str, timestamp: int, trade_type: str) -> str:
        """Generate unique signal ID"""
        return f"{symbol}_{timestamp}_{trade_type}"

    def is_duplicate_signal(self, signal_id: str) -> bool:
        """Check if signal already processed"""
        if signal_id in self.seen_signals:
            return True
        self.seen_signals.add(signal_id)
        return False

    async def run(self):
        """Main run loop"""
        try:
            # Connect
            if not await self.connect():
                logger.error(f"[{self.bot_name}] Failed to connect")
                return

            # Subscribe
            await self.subscribe()

            # Listen for messages
            await self.listen()

        except Exception as e:
            logger.error(f"[{self.bot_name}] Run error: {e}")

    async def subscribe(self):
        """Override in subclasses"""
        raise NotImplementedError("Subclasses must implement subscribe()")
