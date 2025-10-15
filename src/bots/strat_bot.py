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
from ..utils.exceptions import APIError, DataValidationError

logger = logging.getLogger(__name__)

class STRATPatternBot:
    """Bot for detecting STRAT trading patterns"""

    def __init__(self):
        self.name = "STRAT Pattern Scanner"
        self.data_fetcher = DataFetcher()
        self.webhook_url = Config.STRAT_WEBHOOK
        self.scan_interval = Config.STRAT_INTERVAL
        self.detected_today = {}
        self.is_running = False
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
        Check for 3-2-2 Reversal Pattern (60-minute timeframe)
        Bar 1 (8am): Outside bar, Bar 2 (9am): Directional, Bar 3 (10am): Opposite
        """
        if len(bars) < 4:
            return None

        valid_bars = [b for b in bars if self.validate_bar(b)]
        if len(valid_bars) < 4:
            return None

        bars = valid_bars
        pattern_bars = []
        target_hours = {8: None, 9: None, 10: None}

        for bar in bars:
            if 't' not in bar:
                continue
            bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
            bar['time'] = bar_time
            bar_hour = bar_time.hour
            bar_minute = bar_time.minute

            for target_hour in target_hours:
                if target_hours[target_hour] is None:
                    if bar_hour == target_hour and bar_minute <= 5:
                        target_hours[target_hour] = bar
                        break
                    elif bar_hour == target_hour - 1 and bar_minute >= 55:
                        target_hours[target_hour] = bar
                        break

        for hour in [8, 9, 10]:
            if target_hours[hour] is not None:
                pattern_bars.append(target_hours[hour])

        if len(pattern_bars) < 3:
            return None

        prev_bar = bars[0] if len(bars) > 0 else pattern_bars[0]
        bar1_type = self.detect_bar_type(pattern_bars[0], prev_bar)
        bar2_type = self.detect_bar_type(pattern_bars[1], pattern_bars[0])
        bar3_type = self.detect_bar_type(pattern_bars[2], pattern_bars[1])

        if bar1_type != 3:
            return None

        signal = None
        rr = lambda e, t, s: round(abs(t - e) / abs(e - s), 2) if abs(e - s) > 0 else 0

        if bar2_type == 2 and bar3_type == -2:
            signal = {
                'pattern': '3-2-2 Reversal',
                'direction': 'Bearish',
                'ticker': ticker,
                'timeframe': '60min',
                'entry': pattern_bars[2]['c'],
                'target': pattern_bars[0]['h'],
                'stop': pattern_bars[2]['h'],
                'risk_reward': rr(pattern_bars[2]['c'], pattern_bars[0]['h'], pattern_bars[2]['h'])
            }
        elif bar2_type == -2 and bar3_type == 2:
            signal = {
                'pattern': '3-2-2 Reversal',
                'direction': 'Bullish',
                'ticker': ticker,
                'timeframe': '60min',
                'entry': pattern_bars[2]['c'],
                'target': pattern_bars[0]['l'],
                'stop': pattern_bars[2]['l'],
                'risk_reward': rr(pattern_bars[2]['c'], pattern_bars[0]['l'], pattern_bars[2]['l'])
            }

        return signal

    def check_22_reversal(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        Check for 2-2 Reversal Retrigger (4-hour timeframe)
        Bar 1 (4am): Directional, Bar 2 (8am): Opens inside, moves opposite
        """
        if len(bars) < 3:
            return None

        bar_4am = None
        bar_8am = None

        for i, bar in enumerate(bars):
            if 't' not in bar:
                continue
            bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)
            bar['time'] = bar_time
            bar_hour = bar_time.hour
            bar_minute = bar_time.minute

            if not bar_4am:
                if (bar_hour == 4 and bar_minute <= 5) or (bar_hour == 3 and bar_minute >= 55):
                    bar_4am = (i, bar)
            if not bar_8am:
                if (bar_hour == 8 and bar_minute <= 5) or (bar_hour == 7 and bar_minute >= 55):
                    bar_8am = (i, bar)

        if not bar_4am or not bar_8am:
            return None

        idx_4am, data_4am = bar_4am
        idx_8am, data_8am = bar_8am

        prev_bar = bars[idx_4am - 1] if idx_4am > 0 else data_4am
        bar1_type = self.detect_bar_type(data_4am, prev_bar)
        bar2_type = self.detect_bar_type(data_8am, data_4am)

        opened_inside = (data_8am['o'] <= data_4am['h'] and data_8am['o'] >= data_4am['l'])

        if not opened_inside:
            return None

        signal = None

        if bar1_type == -2 and bar2_type == 2:
            signal = {
                'pattern': '2-2 Reversal Retrigger',
                'direction': 'Bullish',
                'ticker': ticker,
                'timeframe': '4hour',
                'entry': data_8am['c'],
                'target': prev_bar['h'],
                'stop': data_4am['l']
            }
        elif bar1_type == 2 and bar2_type == -2:
            signal = {
                'pattern': '2-2 Reversal Retrigger',
                'direction': 'Bearish',
                'ticker': ticker,
                'timeframe': '4hour',
                'entry': data_8am['c'],
                'target': prev_bar['l'],
                'stop': data_4am['h']
            }

        return signal

    def check_131_miyagi(self, bars: List[Dict], ticker: str) -> Optional[Dict]:
        """
        Check for 1-3-1 Miyagi Pattern (12-hour timeframe)
        Pattern: Inside-Outside-Inside, 4th bar breaks midpoint
        """
        if len(bars) < 5:
            return None

        # Add time to bars
        for bar in bars:
            if 't' in bar:
                bar['time'] = datetime.fromtimestamp(bar['t'] / 1000, tz=self.est)

        bar1_type = self.detect_bar_type(bars[1], bars[0])
        bar2_type = self.detect_bar_type(bars[2], bars[1])
        bar3_type = self.detect_bar_type(bars[3], bars[2])

        if not (bar1_type == 1 and bar2_type == 3 and bar3_type == 1):
            return None

        midpoint = (bars[3]['h'] + bars[3]['l']) / 2
        bar4 = bars[4]
        bar4_type = self.detect_bar_type(bar4, bars[3])

        signal = None

        if bar4['c'] > midpoint:
            if bar4_type == 2:
                signal = {
                    'pattern': '1-3-1 Miyagi',
                    'setup': '1-3-1 2U (Fade)',
                    'direction': 'Bearish',
                    'ticker': ticker,
                    'timeframe': '12hour',
                    'entry': bar4['c'],
                    'target': midpoint,
                    'stop': bar4['h']
                }
            else:
                signal = {
                    'pattern': '1-3-1 Miyagi',
                    'setup': '1-3-1 Continuation',
                    'direction': 'Bullish',
                    'ticker': ticker,
                    'timeframe': '12hour',
                    'entry': bar4['c'],
                    'target': bars[2]['h'],
                    'stop': midpoint
                }
        elif bar4['c'] < midpoint:
            if bar4_type == -2:
                signal = {
                    'pattern': '1-3-1 Miyagi',
                    'setup': '1-3-1 2D (Fade)',
                    'direction': 'Bullish',
                    'ticker': ticker,
                    'timeframe': '12hour',
                    'entry': bar4['c'],
                    'target': midpoint,
                    'stop': bar4['l']
                }
            else:
                signal = {
                    'pattern': '1-3-1 Miyagi',
                    'setup': '1-3-1 Continuation',
                    'direction': 'Bearish',
                    'ticker': ticker,
                    'timeframe': '12hour',
                    'entry': bar4['c'],
                    'target': bars[2]['l'],
                    'stop': midpoint
                }

        return signal

    async def scan_ticker(self, ticker: str) -> List[Dict]:
        """Scan a single ticker for all STRAT patterns"""
        signals = []
        now = datetime.now(self.est)

        try:
            # 3-2-2 pattern (60-minute bars)
            if 10 <= now.hour <= 15:
                df_60m = await self.data_fetcher.get_aggregates(
                    ticker, 'minute', 60,
                    (now - timedelta(hours=6)).strftime('%Y-%m-%d'),
                    now.strftime('%Y-%m-%d')
                )
                if not df_60m.empty:
                    bars_60m = df_60m.to_dict('records')
                    # Convert to expected format
                    bars_60m = [{'h': b['high'], 'l': b['low'], 'o': b['open'], 'c': b['close'],
                                 't': int(b['timestamp'].timestamp() * 1000)} for b in bars_60m]
                    signal = self.check_322_reversal(bars_60m, ticker)
                    if signal:
                        signals.append(signal)

            # 2-2 pattern (4-hour bars)
            if 8 <= now.hour <= 9:
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
                        signals.append(signal)

            # 1-3-1 pattern (12-hour bars)
            if now.hour in [0, 4, 8, 12, 16, 20]:
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
                        signals.append(signal)

        except Exception as e:
            logger.error(f"Error scanning {ticker}: {e}")

        return signals

    def send_alert(self, signal: Dict):
        """Send Discord alert for pattern detection"""
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

            if 'setup' in signal:
                embed.add_embed_field(name="⚙️ Setup", value=signal['setup'], inline=False)

            embed.set_footer(text=f"STRAT Pattern Scanner • {datetime.now(self.est).strftime('%Y-%m-%d %H:%M:%S EST')}")
            embed.set_timestamp()

            webhook.add_embed(embed)
            response = webhook.execute()

            if response.status_code == 200:
                logger.info(f"Alert sent for {signal['ticker']} - {signal['pattern']}")

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    async def scan(self):
        """Main scan loop"""
        logger.info(f"{self.name} scan started")

        signals_found = []

        for ticker in Config.WATCHLIST:
            try:
                signals = await self.scan_ticker(ticker)
                for signal in signals:
                    # Check if already detected today
                    key = f"{ticker}_{signal['pattern']}_{datetime.now(self.est).date()}"
                    if key not in self.detected_today:
                        self.send_alert(signal)
                        signals_found.append(signal)
                        self.detected_today[key] = True

            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        if signals_found:
            logger.info(f"Found {len(signals_found)} STRAT patterns")
        else:
            logger.info("No new STRAT patterns detected")

    async def start(self):
        """Start the bot"""
        self.is_running = True
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
        logger.info(f"{self.name} stopped")
