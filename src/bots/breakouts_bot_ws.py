"""
Breakouts Bot - WebSocket Real-Time Version
Monitors price breakouts via 1-minute aggregates streaming
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict
from polygon.websocket.models import EquityAgg
from src.websocket_base import PolygonWebSocketBase
from src.config import Config
from src.utils.logger import logger
from src.utils.discord_poster import DiscordPoster
from discord_webhook import DiscordEmbed


class BreakoutsBotWS(PolygonWebSocketBase):
    """Real-time Breakouts detection via 1-minute aggregates"""

    def __init__(self, webhook_url: str, watchlist: List[str]):
        super().__init__("Breakouts Bot WS")
        self.webhook_url = webhook_url
        self.watchlist = watchlist

        # Thresholds
        self.MIN_SCORE = Config.MIN_BREAKOUT_SCORE  # 65
        self.MIN_VOLUME_SURGE = Config.BREAKOUT_MIN_VOLUME_SURGE  # 1.5x

        # Price history (store last 20 bars for support/resistance)
        self.price_history: Dict[str, List[Dict]] = {}
        self.max_history = 20

        # Discord poster
        self.discord = DiscordPoster(webhook_url, "Breakouts Bot WS")

    async def subscribe(self):
        """Subscribe to 1-minute aggregates for watchlist"""
        await self.subscribe_aggregates(self.watchlist)

    def on_message(self, msgs: List):
        """Handle incoming 1-minute aggregate messages"""
        for msg in msgs:
            if not hasattr(msg, 'close') or not hasattr(msg, 'volume'):
                continue

            try:
                asyncio.create_task(self.process_bar(msg))
            except Exception as e:
                logger.error(f"[{self.bot_name}] Error processing bar: {e}")

    async def process_bar(self, bar: EquityAgg):
        """Process 1-minute bar and detect breakouts"""
        try:
            ticker = bar.symbol if hasattr(bar, 'symbol') else str(bar)
            close = bar.close
            volume = bar.volume
            high = bar.high if hasattr(bar, 'high') else close
            low = bar.low if hasattr(bar, 'low') else close
            open_price = bar.open if hasattr(bar, 'open') else close
            timestamp = datetime.fromtimestamp(bar.start / 1000) if hasattr(bar, 'start') else datetime.now()

            # Initialize price history
            if ticker not in self.price_history:
                self.price_history[ticker] = []

            # Add current bar to history
            self.price_history[ticker].append({
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'timestamp': timestamp
            })

            # Keep only last 20 bars
            if len(self.price_history[ticker]) > self.max_history:
                self.price_history[ticker] = self.price_history[ticker][-self.max_history:]

            # Need at least 10 bars of history to detect breakouts
            if len(self.price_history[ticker]) < 10:
                return

            # Calculate average volume (last 10 bars excluding current)
            recent_bars = self.price_history[ticker][-11:-1]
            avg_volume = sum(b['volume'] for b in recent_bars) / len(recent_bars)

            # Check for volume surge
            volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

            if volume_ratio < self.MIN_VOLUME_SURGE:
                return

            # Calculate resistance (highest high in last 10 bars)
            resistance = max(b['high'] for b in recent_bars)

            # Calculate support (lowest low in last 10 bars)
            support = min(b['low'] for b in recent_bars)

            # Detect breakout type
            breakout_type = None
            breakout_level = None

            # Bullish breakout (close above resistance with volume)
            if close > resistance:
                breakout_type = 'BULLISH'
                breakout_level = resistance

            # Bearish breakdown (close below support with volume)
            elif close < support:
                breakout_type = 'BEARISH'
                breakout_level = support

            # No breakout detected
            if not breakout_type:
                return

            # Calculate breakout strength
            distance_pct = abs((close - breakout_level) / breakout_level) * 100

            # Calculate breakout score
            breakout_score = self._calculate_breakout_score(
                volume_ratio, distance_pct, breakout_type
            )

            if breakout_score >= self.MIN_SCORE:
                # Generate signal ID
                signal_id = self.generate_signal_id(
                    ticker, int(timestamp.timestamp()), f'breakout_{breakout_type}'
                )

                # Check deduplication
                if self.is_duplicate_signal(signal_id):
                    return

                # Create breakout signal
                breakout = {
                    'ticker': ticker,
                    'current_price': close,
                    'breakout_level': breakout_level,
                    'breakout_type': breakout_type,
                    'volume': volume,
                    'avg_volume': avg_volume,
                    'volume_ratio': volume_ratio,
                    'distance_pct': distance_pct,
                    'support': support,
                    'resistance': resistance,
                    'breakout_score': breakout_score
                }

                # Post to Discord
                await self._post_signal(breakout)

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error processing bar: {e}")

    def _calculate_breakout_score(self, volume_ratio: float, distance_pct: float,
                                  breakout_type: str) -> int:
        """Calculate breakout score (0-100)"""
        score = 0

        # Volume surge scoring (50%)
        if volume_ratio >= 5.0:
            score += 50
        elif volume_ratio >= 3.0:
            score += 40
        elif volume_ratio >= 2.0:
            score += 30
        elif volume_ratio >= 1.5:
            score += 20

        # Distance from breakout level (30%)
        if distance_pct >= 3.0:
            score += 30
        elif distance_pct >= 2.0:
            score += 25
        elif distance_pct >= 1.0:
            score += 20
        elif distance_pct >= 0.5:
            score += 15

        # Trend confirmation (20%)
        # Would require multi-timeframe analysis - placeholder for now
        score += 15

        return min(score, 100)

    async def _post_signal(self, breakout: Dict):
        """Post breakout signal to Discord"""
        try:
            color = 0x00FF00 if breakout['breakout_type'] == 'BULLISH' else 0xFF0000

            now = datetime.now()
            time_str = now.strftime('%I:%M %p')
            date_str = now.strftime('%m/%d/%y')

            embed = DiscordEmbed(
                title=f"📈 {breakout['ticker']} - {breakout['breakout_type']} Breakout (REAL-TIME)",
                color=color
            )

            embed.add_embed_field(name="Date", value=date_str, inline=True)
            embed.add_embed_field(name="Time", value=time_str, inline=True)
            embed.add_embed_field(name="Ticker", value=breakout['ticker'], inline=True)
            embed.add_embed_field(name="Price", value=f"${breakout['current_price']:.2f}", inline=True)
            embed.add_embed_field(name="Breakout Level", value=f"${breakout['breakout_level']:.2f}", inline=True)
            embed.add_embed_field(name="Distance", value=f"{breakout['distance_pct']:.2f}%", inline=True)
            embed.add_embed_field(name="Volume", value=f"{breakout['volume']:,}", inline=True)
            embed.add_embed_field(name="Avg Volume", value=f"{breakout['avg_volume']:,.0f}", inline=True)
            embed.add_embed_field(name="Volume Surge", value=f"{breakout['volume_ratio']:.1f}x", inline=True)
            embed.add_embed_field(name="Support", value=f"${breakout['support']:.2f}", inline=True)
            embed.add_embed_field(name="Resistance", value=f"${breakout['resistance']:.2f}", inline=True)
            embed.add_embed_field(name="Algo Score", value=str(int(breakout['breakout_score'])), inline=True)

            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text="ORAKL Bot - Breakouts (Real-Time)")

            success = await self.discord.post_embed(embed)

            if success:
                logger.info(f"🚨 BREAKOUT (REAL-TIME): {breakout['ticker']} {breakout['breakout_type']} "
                          f"${breakout['current_price']:.2f} Level:${breakout['breakout_level']:.2f} "
                          f"Volume:{breakout['volume_ratio']:.1f}x Score:{int(breakout['breakout_score'])}")

        except Exception as e:
            logger.error(f"[{self.bot_name}] Error posting signal: {e}")
