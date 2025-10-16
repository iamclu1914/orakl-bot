"""
STRAT Pattern Detection Bot
Scans for 3-2-2 Reversal, 2-2 Reversal Retrigger, and 1-3-1 Miyagi patterns
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import pytz
from discord_webhook import DiscordWebhook, DiscordEmbed

from ..config import Config
from ..data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

class STRATPatternBot:
    """Bot for detecting STRAT trading patterns"""

    def __init__(self, data_fetcher: DataFetcher = None):
        self.name = "STRAT Pattern Scanner"
        # Use provided data_fetcher or create new one with API key from config
        self.data_fetcher = data_fetcher if data_fetcher else DataFetcher(Config.POLYGON_API_KEY)
        self.webhook_url = Config.STRAT_WEBHOOK
        self.scan_interval = Config.STRAT_INTERVAL
        self.detected_today = {}
        self.is_running = False
        self.running = False  # Add for compatibility with BotManager.get_bot_status()
        self.est = pytz.timezone('America/New_York')

        logger.info(f"{self.name} initialized")

    def validate_bar(self, bar: Dict) -> bool:
        """Validate a bar has all required fields and valid data"""
        required_fields = ['h', 'l', 'o', 'c']

        for field in required_fields:
            if field not in bar:
                return False
            value = bar[field]
            if value is None or value < 0:
                return False

        high, low, open_price, close = bar['h'], bar['l'], bar['o'], bar['c']

        if high < low:
            return False
        if not (low <= open_price <= high) or not (low <= close <= high):
            return False

        return True

    def detect_bar_type(self, current: Dict, previous: Dict) -> int:
        """
        Identify STRAT bar types
        Returns: 3 (outside), 1 (inside), 2 (up), -2 (down), 0 (none)
        """
        if not self.validate_bar(current) or not self.validate_bar(previous):
            return 0

        curr_high, curr_low = current['h'], current['l']
        prev_high, prev_low = previous['h'], previous['l']

        if curr_high > prev_high and curr_low < prev_low:
            return 3  # Outside bar
        elif curr_high <= prev_high and curr_low >= prev_low:
            return 1  # Inside bar
        elif curr_high > prev_high and curr_low >= prev_low:
            return 2  # 2U (Up)
        elif curr_high <= prev_high and curr_low < prev_low:
            return -2  # 2D (Down)
        return 0

    def check_322_reversal(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        PRD Corrected: 3-2-2 Reversal Pattern (60-minute timeframe)
        1. 8:00 AM → Look for 3-bar (outside bar)
        2. 9:00 AM → 2-bar forms (any direction), mark high/low
        3. 10:00 AM → 2-bar opposite direction (high probability alert)
        """
        if len(bars) < 4:
            return None

        valid_bars = [b for b in bars if self.validate_bar(b)]
        if len(valid_bars) < 4:
            return None

        bars = valid_bars
        pattern_bars = []
        target_hours = {8: None, 9: None, 10: None}

        # Extract bars at 8am, 9am, 10am
        for bar in bars:
            if 't' not in bar:
                continue
            bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
            bar['time'] = bar_time
            bar_hour = bar_time.hour

            if bar_hour in target_hours and target_hours[bar_hour] is None:
                target_hours[bar_hour] = bar

        for hour in [8, 9, 10]:
            if target_hours[hour] is not None:
                pattern_bars.append(target_hours[hour])

        if len(pattern_bars) < 3:
            return None

        bar_8am = pattern_bars[0]
        bar_9am = pattern_bars[1]
        bar_10am = pattern_bars[2]

        # Find previous bar for 8am comparison
        prev_bar = bars[0] if len(bars) > 0 else bar_8am

        # Step 1: 8am must be 3-bar (outside)
        bar1_type = self.detect_bar_type(bar_8am, prev_bar)
        if bar1_type != 3:
            return None

        # Step 2: 9am is a 2-bar (direction doesn't matter)
        bar2_type = self.detect_bar_type(bar_9am, bar_8am)
        if abs(bar2_type) != 2:
            return None

        # Step 3: 10am must be 2-bar in opposite direction
        bar3_type = self.detect_bar_type(bar_10am, bar_9am)
        if abs(bar3_type) != 2:
            return None

        signal = None
        rr = lambda e, t, s: round(abs(t - e) / abs(e - s), 2) if abs(e - s) > 0 else 0

        # If 9am=2U and 10am=2D → Bearish reversal
        if bar2_type == 2 and bar3_type == -2:
            signal = {
                'pattern': '3-2-2 Reversal',
                'direction': 'Bearish',
                'ticker': ticker,
                'timeframe': '60min',
                'entry': bar_10am['c'],
                'target': bar_9am['l'],  # Low of 9am bar
                'stop': bar_9am['h'],    # High of 9am bar
                'risk_reward': rr(bar_10am['c'], bar_9am['l'], bar_9am['h'])
            }
        # If 9am=2D and 10am=2U → Bullish reversal
        elif bar2_type == -2 and bar3_type == 2:
            signal = {
                'pattern': '3-2-2 Reversal',
                'direction': 'Bullish',
                'ticker': ticker,
                'timeframe': '60min',
                'entry': bar_10am['c'],
                'target': bar_9am['h'],  # High of 9am bar
                'stop': bar_9am['l'],    # Low of 9am bar
                'risk_reward': rr(bar_10am['c'], bar_9am['h'], bar_9am['l'])
            }

        return signal

    def check_22_reversal(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        PRD Corrected: 2-2 Reversal Retrigger (4-hour timeframe)
        1. 4:00 AM → Look for 2-bar (2D or 2U)
        2. 8:00 AM → Opens inside previous bar, triggers opposite direction
        3. Target: High/Low of candle BEFORE 4am bar
        Alert sent after 8am candle closes
        """
        if len(bars) < 3:
            return None

        bar_4am = None
        bar_8am = None
        bar_before_4am = None

        for i, bar in enumerate(bars):
            if 't' not in bar:
                continue
            bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
            bar['time'] = bar_time
            bar_hour = bar_time.hour

            if bar_hour == 0 and bar_before_4am is None:  # Midnight bar (before 4am)
                bar_before_4am = (i, bar)
            elif bar_hour == 4 and bar_4am is None:
                bar_4am = (i, bar)
            elif bar_hour == 8 and bar_8am is None:
                bar_8am = (i, bar)

        if not bar_4am or not bar_8am or not bar_before_4am:
            return None

        idx_before, data_before = bar_before_4am
        idx_4am, data_4am = bar_4am
        idx_8am, data_8am = bar_8am

        # Step 1: 4am must be a 2-bar (2D or 2U)
        bar1_type = self.detect_bar_type(data_4am, data_before)
        if abs(bar1_type) != 2:
            return None

        # Step 2: 8am must open inside 4am bar
        opened_inside = (data_8am['o'] <= data_4am['h'] and data_8am['o'] >= data_4am['l'])
        if not opened_inside:
            return None

        # Step 3: 8am must be opposite direction 2-bar
        bar2_type = self.detect_bar_type(data_8am, data_4am)
        if abs(bar2_type) != 2:
            return None

        signal = None

        # If 4am=2D and 8am=2U → Bullish reversal
        if bar1_type == -2 and bar2_type == 2:
            signal = {
                'pattern': '2-2 Reversal Retrigger',
                'direction': 'Bullish',
                'ticker': ticker,
                'timeframe': '4hour',
                'entry': data_8am['c'],
                'target': data_before['h'],  # High of candle BEFORE 4am
                'stop': data_4am['l']
            }
        # If 4am=2U and 8am=2D → Bearish reversal
        elif bar1_type == 2 and bar2_type == -2:
            signal = {
                'pattern': '2-2 Reversal Retrigger',
                'direction': 'Bearish',
                'ticker': ticker,
                'timeframe': '4hour',
                'entry': data_8am['c'],
                'target': data_before['l'],  # Low of candle BEFORE 4am
                'stop': data_4am['h']
            }

        return signal

    def check_131_miyagi(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        PRD Corrected: 1-3-1 Miyagi Pattern (12-hour timeframe)
        1. Identify 1-3-1: Inside → Outside → Inside (3 consecutive candles)
        2. Calculate midpoint of 3rd candle (last 1-bar)
        3. 4th candle direction determines trade:
           - If 4th candle is 2U → take PUTS (reversal from overextension)
           - If 4th candle is 2D → take CALLS (reversal from overextension)
        """
        if len(bars) < 4:
            return None

        # Add time to bars
        for bar in bars:
            if 't' in bar:
                bar['time'] = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)

        # Get last 4 bars
        candle1 = bars[-4]
        candle2 = bars[-3]
        candle3 = bars[-2]
        candle4 = bars[-1]

        # Determine bar types for 1-3-1 pattern
        type1 = self.detect_bar_type(candle1, bars[-5] if len(bars) > 4 else candle1)
        type2 = self.detect_bar_type(candle2, candle1)
        type3 = self.detect_bar_type(candle3, candle2)
        type4 = self.detect_bar_type(candle4, candle3)

        # Step 1: Must have 1-3-1 pattern
        if not (type1 == 1 and type2 == 3 and type3 == 1):
            return None

        # Step 2: Calculate midpoint of 3rd candle (last 1-bar)
        midpoint = (candle3['h'] + candle3['l']) / 2

        signal = None

        # Step 3: 4th candle determines direction
        # If 4th is 2U (breaks above midpoint) → PUTS (reversal down expected)
        if type4 == 2:
            signal = {
                'pattern': '1-3-1 Miyagi',
                'setup': '1-3-1 2U (Fade)',
                'direction': 'Bearish',  # Take PUTS
                'ticker': ticker,
                'timeframe': '12hour',
                'entry': candle4['c'],
                'target': midpoint,
                'stop': candle4['h']
            }
        # If 4th is 2D (breaks below midpoint) → CALLS (reversal up expected)
        elif type4 == -2:
            signal = {
                'pattern': '1-3-1 Miyagi',
                'setup': '1-3-1 2D (Fade)',
                'direction': 'Bullish',  # Take CALLS
                'ticker': ticker,
                'timeframe': '12hour',
                'entry': candle4['c'],
                'target': midpoint,
                'stop': candle4['l']
            }

        return signal

    async def scan_ticker(self, ticker: str) -> List[Dict]:
        """PRD Enhanced: Scan with time-based pattern scheduling"""
        signals = []
        now = datetime.now(self.est)

        try:
            # 1-3-1 Miyagi - Scan on 12H timeframe at 4am, 4pm
            if now.hour in [4, 16] and now.minute <= 5:
                df_12h = await self.data_fetcher.get_aggregates(
                    ticker, 'hour', 12,
                    (now - timedelta(days=5)).strftime('%Y-%m-%d'),
                    now.strftime('%Y-%m-%d')
                )
                if not df_12h.empty:
                    bars_12h = df_12h.to_dict('records')
                    bars_12h = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                                't': int(b['timestamp'].timestamp() * 1000)} for b in bars_12h]
                    signal = self.check_131_miyagi(bars_12h, ticker)
                    if signal:
                        signal['confidence_score'] = 0.75
                        signals.append(signal)

            # 3-2-2 Reversal - Scan at 8am, 9am, and 10:01am ET
            if now.hour in [8, 9] and 0 <= now.minute <= 5:
                df_60m = await self.data_fetcher.get_aggregates(
                    ticker, 'minute', 60,
                    now.replace(hour=7, minute=0).strftime('%Y-%m-%d'),
                    now.strftime('%Y-%m-%d')
                )
                if not df_60m.empty:
                    bars_60m = df_60m.to_dict('records')
                    bars_60m = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                                 't': int(b['timestamp'].timestamp() * 1000)} for b in bars_60m]
                    signal = self.check_322_reversal(bars_60m, ticker)
                    if signal:
                        signal['confidence_score'] = 0.70
                        signals.append(signal)
            elif now.hour == 10 and now.minute == 1:
                df_60m = await self.data_fetcher.get_aggregates(
                    ticker, 'minute', 60,
                    now.replace(hour=7, minute=0).strftime('%Y-%m-%d'),
                    now.strftime('%Y-%m-%d')
                )
                if not df_60m.empty:
                    bars_60m = df_60m.to_dict('records')
                    bars_60m = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                                 't': int(b['timestamp'].timestamp() * 1000)} for b in bars_60m]
                    signal = self.check_322_reversal(bars_60m, ticker)
                    if signal:
                        signal['confidence_score'] = 0.70
                        signals.append(signal)

            # 2-2 Reversal - Scan at 4am and 8am ET
            if now.hour in [4, 8] and 0 <= now.minute <= 5:
                df_4h = await self.data_fetcher.get_aggregates(
                    ticker, 'hour', 4,
                    (now - timedelta(days=2)).strftime('%Y-%m-%d'),
                    now.strftime('%Y-%m-%d')
                )
                if not df_4h.empty:
                    bars_4h = df_4h.to_dict('records')
                    bars_4h = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                               't': int(b['timestamp'].timestamp() * 1000)} for b in bars_4h]
                    signal = self.check_22_reversal(bars_4h, ticker)
                    if signal:
                        signal['confidence_score'] = 0.68
                        signals.append(signal)

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}")

        return signals

    def send_alert(self, signal: Dict):
        """PRD Enhanced: Send Discord alert with confidence score"""
        try:
            webhook = DiscordWebhook(url=self.webhook_url, rate_limit_retry=True)

            color = 0x00FF00 if signal['direction'] == 'Bullish' else 0xFF0000

            embed = DiscordEmbed(
                title=f"🎯 {signal['pattern']} - {signal['ticker']}",
                description=f"**{signal['direction']}** setup detected",
                color=color
            )

            embed.add_embed_field(name="📊 Timeframe", value=signal['timeframe'], inline=True)
            embed.add_embed_field(name="📍 Entry", value=f"${signal['entry']:.2f}", inline=True)
            embed.add_embed_field(name="🎯 Target", value=f"${signal['target']:.2f}", inline=True)

            if 'stop' in signal:
                embed.add_embed_field(name="🛑 Stop", value=f"${signal['stop']:.2f}", inline=True)

            if 'risk_reward' in signal:
                embed.add_embed_field(name="💰 R:R", value=f"{signal['risk_reward']:.2f}", inline=True)

            # PRD Enhancement: Display confidence score
            if 'confidence_score' in signal:
                embed.add_embed_field(
                    name="🎲 Confidence",
                    value=f"{signal['confidence_score']*100:.0f}%",
                    inline=True
                )

            if 'setup' in signal:
                embed.add_embed_field(name="⚙️ Setup", value=signal['setup'], inline=False)

            # Add disclaimer
            embed.add_embed_field(
                name="",
                value="Please always do your own due diligence on top of these trade ideas.",
                inline=False
            )

            embed.set_footer(text=f"STRAT Pattern Scanner • {datetime.now(self.est).strftime('%Y-%m-%d %H:%M:%S EST')}")
            embed.set_timestamp()

            webhook.add_embed(embed)
            response = webhook.execute()

            if response.status_code == 200:
                logger.info(f"Alert sent for {signal['ticker']} - {signal['pattern']}")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    async def scan(self):
        """PRD Enhanced: Scan with best signal selection"""
        logger.info(f"{self.name} scan started")

        signals_found = []

        for ticker in Config.WATCHLIST:
            try:
                signals = await self.scan_ticker(ticker)

                # PRD Enhancement: Post only highest confidence signal per ticker
                if signals:
                    best_signal = max(signals, key=lambda x: x.get('confidence_score', 0))

                    # Check if already detected today
                    key = f"{ticker}_{best_signal['pattern']}_{datetime.now(self.est).date()}"
                    if key not in self.detected_today:
                        self.send_alert(best_signal)
                        signals_found.append(best_signal)
                        self.detected_today[key] = True

                        logger.info(f"✅ STRAT signal: {ticker} {best_signal['pattern']} - "
                                  f"Confidence:{best_signal.get('confidence_score', 0):.2f}")

            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        if signals_found:
            logger.info(f"Found {len(signals_found)} STRAT patterns")
        else:
            logger.info("No new STRAT patterns detected")

    async def start(self):
        """Start the bot"""
        self.is_running = True
        self.running = True  # Sync with is_running
        logger.info(f"{self.name} started with {self.scan_interval}s interval")

        while self.is_running:
            try:
                # Reset daily tracking at midnight
                now = datetime.now(self.est)
                if now.hour == 0 and now.minute == 0:
                    self.detected_today.clear()
                    logger.info("Daily pattern tracking reset")

                await self.scan()
                await asyncio.sleep(self.scan_interval)

            except Exception as e:
                logger.error(f"{self.name} error: {e}")
                await asyncio.sleep(60)

    async def stop(self):
        """Stop the bot"""
        self.is_running = False
        self.running = False  # Sync with is_running
        logger.info(f"{self.name} stopped")
