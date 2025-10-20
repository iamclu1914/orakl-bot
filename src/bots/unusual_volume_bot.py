"""Unusual Volume Bot - Detects stocks with unusually high volume"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.options_analyzer import OptionsAnalyzer
from src.config import Config
from src.utils.monitoring import signals_generated, timed
from src.utils.exceptions import DataException, handle_exception
from src.utils.validation import SafeCalculations
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

class UnusualVolumeBot(BaseAutoBot):
    """
    Unusual Volume Bot
    Detects stocks trading at 3x+ their average volume
    Early warning system for institutional activity and major moves
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher, analyzer: OptionsAnalyzer):
        super().__init__(webhook_url, "Unusual Volume Bot", scan_interval=Config.UNUSUAL_VOLUME_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.signal_history = {}
        self.volume_cache = {}  # Cache historical averages
        self.MIN_VOLUME_RATIO = Config.MIN_VOLUME_RATIO
        self.MIN_SCORE = Config.MIN_UNUSUAL_VOLUME_SCORE
        self.MIN_ABSOLUTE_VOLUME = Config.MIN_ABSOLUTE_VOLUME

    @timed()
    async def scan_and_post(self):
        """Scan for unusual volume activity"""
        logger.info(f"{self.name} scanning for unusual volume")

        # Only scan during market hours (9:30 AM - 4:00 PM EST, Monday-Friday)
        if not MarketHours.is_market_open():
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        signals_posted = 0
        
        for symbol in self.watchlist:
            try:
                volume_signals = await self._scan_symbol_volume(symbol)
                for signal in volume_signals:
                    success = await self._post_signal(signal)
                    if success:
                        signals_posted += 1
            except Exception as e:
                error_info = handle_exception(e, logger)
                logger.error(f"{self.name} error scanning {symbol}: {error_info['message']}")
        
        if signals_posted > 0:
            signals_generated.inc(
                value=signals_posted,
                labels={'bot': self.name, 'signal_type': 'unusual_volume'}
            )
            logger.info(f"✓ {self.name} posted {signals_posted} signal(s) this scan")

    async def _scan_symbol_volume(self, symbol: str) -> List[Dict]:
        """Scan a single symbol for unusual volume"""
        signals = []

        try:
            # Get current price
            current_price = await self.fetcher.get_stock_price(symbol)
            if not current_price:
                return signals

            # Get intraday volume data (today)
            today = datetime.now().strftime('%Y-%m-%d')
            intraday_data = await self.fetcher.get_aggregates(
                symbol,
                timespan='minute',
                multiplier=1,
                from_date=today,
                to_date=today
            )

            if intraday_data.empty or len(intraday_data) < 30:  # Need at least 30 minutes
                return signals

            # Calculate current cumulative volume
            current_volume = intraday_data['volume'].sum()
            
            # Skip if below absolute minimum
            if current_volume < self.MIN_ABSOLUTE_VOLUME:
                return signals

            # Get historical average volume (use cache if available)
            avg_volume = await self._get_average_volume(symbol)
            if not avg_volume or avg_volume == 0:
                return signals

            # Calculate volume ratio
            volume_ratio = SafeCalculations.safe_divide(current_volume, avg_volume, default=1.0)

            # Check if unusual (3x+ average)
            if volume_ratio < self.MIN_VOLUME_RATIO:
                return signals

            # Calculate time elapsed in trading day
            market_open = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
            now = datetime.now()
            
            if now < market_open:
                return signals
            
            time_elapsed_hours = (now - market_open).total_seconds() / 3600
            market_hours_total = 6.5  # 9:30 AM to 4:00 PM
            time_fraction = min(time_elapsed_hours / market_hours_total, 1.0)

            # Calculate projected end-of-day volume
            if time_fraction > 0.1:  # After first 40 minutes
                projected_volume = SafeCalculations.safe_divide(
                    current_volume,
                    time_fraction,
                    default=current_volume
                )
                pace_ratio = SafeCalculations.safe_divide(projected_volume, avg_volume, default=1.0)
            else:
                pace_ratio = volume_ratio

            # Get price change
            prev_close = intraday_data['open'].iloc[0] if not intraday_data.empty else current_price
            price_change_pct = SafeCalculations.safe_percentage(
                current_price - prev_close,
                prev_close
            )

            # Calculate volume consistency (how sustained is the volume)
            time_consistency = self._calculate_volume_consistency(intraday_data)

            # Calculate volume score
            volume_score = self._calculate_volume_score(
                volume_ratio,
                pace_ratio,
                price_change_pct,
                time_consistency
            )

            # Only signal if score meets threshold (minimum 50%)
            if volume_score < max(50, self.MIN_SCORE):
                return signals

            # Determine volume pattern
            pattern = self._determine_volume_pattern(
                intraday_data,
                price_change_pct,
                volume_ratio
            )

            # Create signal
            signal = {
                'ticker': symbol,
                'symbol': symbol,
                'current_price': current_price,
                'current_volume': current_volume,
                'avg_volume': avg_volume,
                'volume_ratio': volume_ratio,
                'projected_volume': projected_volume if time_fraction > 0.1 else current_volume,
                'pace_ratio': pace_ratio,
                'price_change_pct': price_change_pct,
                'time_fraction': time_fraction,
                'time_elapsed_hours': time_elapsed_hours,
                'volume_score': volume_score,
                'pattern': pattern,
                'consistency': time_consistency,
                'timestamp': now
            }

            # Check if already posted (once per symbol per day)
            signal_key = f"{symbol}_{today}_{int(volume_ratio)}"
            if signal_key not in self.signal_history:
                signals.append(signal)
                self.signal_history[signal_key] = now
                
                # Clean old history (>24 hours)
                self._cleanup_signal_history()

        except Exception as e:
            logger.error(f"Error scanning volume for {symbol}: {e}")

        return signals

    async def _get_average_volume(self, symbol: str) -> float:
        """Get average volume with caching"""
        # Check cache (valid for 1 hour)
        if symbol in self.volume_cache:
            cache_entry = self.volume_cache[symbol]
            if (datetime.now() - cache_entry['timestamp']).total_seconds() < 3600:
                return cache_entry['avg_volume']

        try:
            # Get historical data (20 trading days)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)  # 30 calendar days = ~20 trading days

            historical = await self.fetcher.get_aggregates(
                symbol,
                timespan='day',
                multiplier=1,
                from_date=start_date.strftime('%Y-%m-%d'),
                to_date=end_date.strftime('%Y-%m-%d')
            )

            if historical.empty or len(historical) < 10:
                return 0

            # Calculate average volume
            avg_volume = historical['volume'].mean()

            # Cache the result
            self.volume_cache[symbol] = {
                'avg_volume': avg_volume,
                'timestamp': datetime.now()
            }

            return avg_volume

        except Exception as e:
            logger.debug(f"Error getting average volume for {symbol}: {e}")
            return 0

    def _calculate_volume_score(
        self,
        volume_ratio: float,
        pace_ratio: float,
        price_change: float,
        time_factor: float
    ) -> int:
        """Calculate unusual volume score (0-100)"""
        score = 0

        # Volume multiple (40 points)
        if volume_ratio >= 10:
            score += 40
        elif volume_ratio >= 7:
            score += 37
        elif volume_ratio >= 5:
            score += 35
        elif volume_ratio >= 4:
            score += 32
        elif volume_ratio >= 3:
            score += 30

        # Intraday pace (25 points)
        if pace_ratio >= 10:
            score += 25
        elif pace_ratio >= 7:
            score += 22
        elif pace_ratio >= 5:
            score += 20
        elif pace_ratio >= 3:
            score += 15

        # Price correlation (20 points)
        if abs(price_change) >= 5:
            score += 20
        elif abs(price_change) >= 3:
            score += 15
        elif abs(price_change) >= 2:
            score += 12
        elif abs(price_change) >= 1:
            score += 10
        else:
            score += 5  # Volume without price movement can still be significant

        # Time consistency (15 points)
        if time_factor >= 0.8:
            score += 15  # Very sustained
        elif time_factor >= 0.6:
            score += 12
        elif time_factor >= 0.4:
            score += 8

        return min(score, 100)

    def _calculate_volume_consistency(self, intraday_data) -> float:
        """Calculate how consistent volume is throughout the period"""
        try:
            if intraday_data.empty or len(intraday_data) < 10:
                return 0.5

            volumes = intraday_data['volume'].values
            
            # Calculate coefficient of variation (lower = more consistent)
            mean_vol = volumes.mean()
            std_vol = volumes.std()
            
            if mean_vol == 0:
                return 0.5
            
            cv = std_vol / mean_vol
            
            # Convert to consistency score (0-1)
            # Lower CV = higher consistency
            if cv < 0.5:
                consistency = 1.0
            elif cv < 1.0:
                consistency = 0.8
            elif cv < 2.0:
                consistency = 0.5
            else:
                consistency = 0.3
            
            return consistency

        except Exception:
            return 0.5

    def _determine_volume_pattern(
        self,
        intraday_data,
        price_change: float,
        volume_ratio: float
    ) -> str:
        """Determine the volume pattern type"""
        try:
            if intraday_data.empty:
                return "Unknown"

            # Analyze volume distribution
            first_half = intraday_data.head(len(intraday_data) // 2)['volume'].sum()
            second_half = intraday_data.tail(len(intraday_data) // 2)['volume'].sum()
            
            # Determine pattern based on volume distribution and price
            if second_half > first_half * 1.5:
                if price_change > 1:
                    return "Accelerating Accumulation"
                elif price_change < -1:
                    return "Accelerating Distribution"
                else:
                    return "Accelerating"
            elif first_half > second_half * 1.5:
                if price_change > 1:
                    return "Early Accumulation"
                elif price_change < -1:
                    return "Early Distribution"
                else:
                    return "Frontloaded"
            else:
                # Sustained throughout
                if price_change > 1:
                    return "Sustained Accumulation"
                elif price_change < -1:
                    return "Sustained Distribution"
                elif volume_ratio >= 5:
                    return "Institutional Activity"
                else:
                    return "Sustained Interest"

        except Exception:
            return "Active Trading"

    def _cleanup_signal_history(self):
        """Remove old signals from history"""
        cutoff = datetime.now() - timedelta(hours=24)
        keys_to_remove = [
            key for key, timestamp in self.signal_history.items()
            if timestamp < cutoff
        ]
        for key in keys_to_remove:
            del self.signal_history[key]

    async def _post_signal(self, signal: Dict) -> bool:
        """Post unusual volume signal to Discord"""
        color = 0x0099FF  # Blue color for volume signals
        emoji = "📊" if signal['price_change_pct'] >= 0 else "📉"

        # Determine urgency emoji
        if signal['volume_ratio'] >= 10:
            urgency = "🚨"
        elif signal['volume_ratio'] >= 7:
            urgency = "⚠️"
        elif signal['volume_ratio'] >= 5:
            urgency = "🔔"
        else:
            urgency = "📢"

        # Format volume numbers
        current_vol_str = self._format_volume(signal['current_volume'])
        avg_vol_str = self._format_volume(signal['avg_volume'])
        projected_vol_str = self._format_volume(signal['projected_volume'])

        # Determine pace
        if signal['pace_ratio'] >= 7:
            pace = "🔥 EXTREME"
        elif signal['pace_ratio'] >= 5:
            pace = "⚡ VERY HIGH"
        elif signal['pace_ratio'] >= 3:
            pace = "📈 HIGH"
        else:
            pace = "→ ELEVATED"

        # Build description
        description = f"**Volume Surge: {signal['volume_ratio']:.1f}x Average** | Score: {signal['volume_score']}/100"
        if signal['price_change_pct'] != 0:
            description += f" | Price: {signal['price_change_pct']:+.2f}%"

        embed = self.create_embed(
            title=f"{urgency} {emoji} UNUSUAL VOLUME: {signal['ticker']}",
            description=description,
            color=color,
            fields=[
                {
                    "name": "📊 Current Volume",
                    "value": f"**{current_vol_str} shares**",
                    "inline": True
                },
                {
                    "name": "📈 Average Volume",
                    "value": f"{avg_vol_str} shares",
                    "inline": True
                },
                {
                    "name": "🔢 Volume Ratio",
                    "value": f"**{signal['volume_ratio']:.2f}x**",
                    "inline": True
                },
                {
                    "name": "💵 Current Price",
                    "value": f"${signal['current_price']:.2f}",
                    "inline": True
                },
                {
                    "name": "📈 Price Change",
                    "value": f"{signal['price_change_pct']:+.2f}%",
                    "inline": True
                },
                {
                    "name": "💪 Volume Score",
                    "value": f"**{signal['volume_score']}/100**",
                    "inline": True
                },
                {
                    "name": "🎯 Projected EOD Volume",
                    "value": f"{projected_vol_str} ({signal['pace_ratio']:.1f}x avg)",
                    "inline": False
                },
                {
                    "name": "⏰ Time of Day",
                    "value": f"{signal['time_elapsed_hours']:.1f} hours ({signal['time_fraction']*100:.1f}% of day)",
                    "inline": True
                },
                {
                    "name": "⚡ Pace",
                    "value": pace,
                    "inline": True
                },
                {
                    "name": "📍 Pattern",
                    "value": signal['pattern'],
                    "inline": True
                },
                {
                    "name": "🔄 Consistency",
                    "value": f"{signal['consistency']*100:.0f}%",
                    "inline": True
                },
                {
                    "name": "🕐 Timestamp",
                    "value": signal['timestamp'].strftime("%I:%M %p ET"),
                    "inline": True
                },
                {
                    "name": "💡 Analysis",
                    "value": self._generate_analysis(signal),
                    "inline": False
                },
                {
                    "name": "",
                    "value": "Please always do your own due diligence on top of these trade ideas.",
                    "inline": False
                }
            ],
            footer="Unusual Volume Bot | Institutional Activity Detector"
        )

        success = await self.post_to_discord(embed)
        if success:
            logger.info(
                f"✓ Posted Unusual Volume: {signal['ticker']} "
                f"{signal['volume_ratio']:.1f}x @ ${signal['current_price']:.2f} "
                f"Score:{signal['volume_score']}"
            )
        else:
            logger.error(f"✗ Failed to post volume signal for {signal['ticker']}")

        return success

    def _format_volume(self, volume: float) -> str:
        """Format volume with appropriate suffix"""
        if volume >= 1_000_000_000:
            return f"{volume / 1_000_000_000:.2f}B"
        elif volume >= 1_000_000:
            return f"{volume / 1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"{volume / 1_000:.1f}K"
        else:
            return f"{volume:,.0f}"

    def _generate_analysis(self, signal: Dict) -> str:
        """Generate analysis text for the signal"""
        parts = []

        # Volume analysis
        if signal['volume_ratio'] >= 7:
            parts.append("🚨 EXTREME institutional activity")
        elif signal['volume_ratio'] >= 5:
            parts.append("⚡ Very strong institutional interest")
        elif signal['volume_ratio'] >= 3:
            parts.append("📊 Significant volume surge detected")

        # Price correlation
        if abs(signal['price_change_pct']) >= 3:
            direction = "upward" if signal['price_change_pct'] > 0 else "downward"
            parts.append(f"Strong {direction} momentum with volume confirmation")
        elif abs(signal['price_change_pct']) >= 1:
            parts.append("Volume and price moving together")
        else:
            parts.append("Volume surge without major price move - potential setup")

        # Pattern insight
        if "Accumulation" in signal['pattern']:
            parts.append("→ Bullish accumulation pattern")
        elif "Distribution" in signal['pattern']:
            parts.append("→ Bearish distribution pattern")
        elif "Institutional" in signal['pattern']:
            parts.append("→ Large institutional positioning")

        # Pace insight
        if signal['pace_ratio'] >= 7:
            parts.append("⚠️ On pace for MASSIVE volume day")
        elif signal['pace_ratio'] >= 5:
            parts.append("Projected to significantly exceed normal volume")

        return "\n".join(parts) if parts else "Unusual volume activity detected"

