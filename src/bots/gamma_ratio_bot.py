import logging
from datetime import datetime
from typing import Dict, List, Optional

from .base_bot import BaseAutoBot
from src.data_fetcher import DataFetcher
from src.config import Config
from src.utils.monitoring import timed
from src.utils.market_hours import MarketHours
from src.utils.gamma_ratio import (
    compute_gamma_ratio,
    transform_polygon_snapshot,
    classify_gamma_regime,
    get_regime_color,
    get_regime_emoji,
    GAMMA_THRESHOLDS,
)
from src.utils.plotly_charts import ProfessionalCharts


logger = logging.getLogger(__name__)


class GammaAlertManager:
    """
    Manages gamma ratio alert state and threshold detection.
    
    Tracks regime changes and implements cooldown logic to prevent
    alert spam while catching meaningful market regime shifts.
    
    Alert Tiers:
    - DRIVEN: G > 0.65 (call) or G < 0.35 (put) - medium priority
    - EXTREME: G > 0.75 (call) or G < 0.25 (put) - high priority
    - ULTRA EXTREME: G > 0.85 (call) or G < 0.15 (put) - escalation alert (bypasses cooldown)
    """
    
    # Ultra extreme thresholds for escalation alerts
    ULTRA_EXTREME_CALL = 0.85
    ULTRA_EXTREME_PUT = 0.15
    
    def __init__(self, cooldown_minutes: int = 30):
        self.cooldown_minutes = cooldown_minutes
        self.last_alert_time: Dict[str, Dict[str, datetime]] = {}  # symbol -> {alert_type: timestamp}
        self.last_G: Dict[str, float] = {}  # symbol -> last G value
        self.last_alerted_G: Dict[str, float] = {}  # symbol -> G value when last alerted (for escalation)
    
    def check_alerts(self, symbol: str, G: float, data: Dict) -> List[Dict]:
        """
        Check if any alerts should be triggered for this symbol.
        
        Alert Tiers:
        - DRIVEN: G > 0.65 (call) or G < 0.35 (put) - medium priority
        - EXTREME: G > 0.75 (call) or G < 0.25 (put) - high priority
        - ULTRA EXTREME: G > 0.85 (call) or G < 0.15 (put) - bypasses cooldown
        
        Args:
            symbol: Ticker symbol
            G: Current gamma ratio
            data: Full gamma ratio data from compute_gamma_ratio
        
        Returns:
            List of alert dictionaries to send
        """
        alerts = []
        now = datetime.now()
        
        # Get previous state for this symbol
        prev_G = self.last_G.get(symbol, 0.5)
        last_alerted = self.last_alerted_G.get(symbol)
        
        # Determine current regime
        current_regime, priority = classify_gamma_regime(G)
        
        # Check for regime change alerts
        thresholds = GAMMA_THRESHOLDS
        
        # === CALL SIDE ===
        # Check for ULTRA EXTREME CALL (escalation - bypasses cooldown)
        if G > self.ULTRA_EXTREME_CALL:
            # Only alert if we haven't already alerted at ultra level
            if last_alerted is None or last_alerted <= self.ULTRA_EXTREME_CALL:
                alerts.append({
                    'type': 'ULTRA_EXTREME_CALL',
                    'symbol': symbol,
                    'G': G,
                    'data': data,
                    'message': f"🟢🟢 **{symbol} ULTRA EXTREME CALL**\nG = {G:.2f}\nMassive upside convexity - potential gamma squeeze",
                    'priority': 'critical',
                    'regime': 'ULTRA_EXTREME_CALL',
                    'bypass_cooldown': True
                })
        # Check for EXTREME CALL (high threshold)
        elif G > thresholds['extreme_call'] and prev_G <= thresholds['extreme_call']:
            alerts.append({
                'type': 'EXTREME_CALL',
                'symbol': symbol,
                'G': G,
                'data': data,
                'message': f"🟢 **{symbol} EXTREME CALL-DRIVEN**\nG = {G:.2f}\nUpside convexity dominating",
                'priority': 'high',
                'regime': current_regime
            })
        # Check for CALL DRIVEN (medium threshold)
        elif G > thresholds['call_driven'] and prev_G <= thresholds['call_driven']:
            alerts.append({
                'type': 'CALL_DRIVEN',
                'symbol': symbol,
                'G': G,
                'data': data,
                'message': f"🔵 **{symbol} CALL-DRIVEN**\nG = {G:.2f}\nCall gamma exceeds put gamma",
                'priority': 'medium',
                'regime': 'CALL_DRIVEN'
            })
        
        # === PUT SIDE ===
        # Check for ULTRA EXTREME PUT (escalation - bypasses cooldown)
        if G < self.ULTRA_EXTREME_PUT:
            # Only alert if we haven't already alerted at ultra level
            if last_alerted is None or last_alerted >= self.ULTRA_EXTREME_PUT:
                alerts.append({
                    'type': 'ULTRA_EXTREME_PUT',
                    'symbol': symbol,
                    'G': G,
                    'data': data,
                    'message': f"🔴🔴 **{symbol} ULTRA EXTREME PUT**\nG = {G:.2f}\nMassive downside convexity - potential crash acceleration",
                    'priority': 'critical',
                    'regime': 'ULTRA_EXTREME_PUT',
                    'bypass_cooldown': True
                })
        # Check for EXTREME PUT (high threshold)
        elif G < thresholds['extreme_put'] and prev_G >= thresholds['extreme_put']:
            alerts.append({
                'type': 'EXTREME_PUT',
                'symbol': symbol,
                'G': G,
                'data': data,
                'message': f"🔴 **{symbol} EXTREME PUT-DRIVEN**\nG = {G:.2f}\nDownside convexity dominating",
                'priority': 'high',
                'regime': current_regime
            })
        # Check for PUT DRIVEN (medium threshold)
        elif G < thresholds['put_driven'] and prev_G >= thresholds['put_driven']:
            alerts.append({
                'type': 'PUT_DRIVEN',
                'symbol': symbol,
                'G': G,
                'data': data,
                'message': f"🟠 **{symbol} PUT-DRIVEN**\nG = {G:.2f}\nPut gamma exceeds call gamma",
                'priority': 'medium',
                'regime': 'PUT_DRIVEN'
            })
        
        # Apply cooldown filter (unless bypass_cooldown is set)
        filtered_alerts = []
        for alert in alerts:
            if alert.get('bypass_cooldown') or self._check_cooldown(symbol, alert['type'], now):
                filtered_alerts.append(alert)
                # Update last alerted G for escalation tracking
                self.last_alerted_G[symbol] = G
        
        # Update state
        self.last_G[symbol] = G
        
        return filtered_alerts
    
    def _check_cooldown(self, symbol: str, alert_type: str, now: datetime) -> bool:
        """
        Check if alert is within cooldown period.
        
        Returns True if alert should be sent (not in cooldown).
        """
        if symbol not in self.last_alert_time:
            self.last_alert_time[symbol] = {}
        
        last = self.last_alert_time[symbol].get(alert_type)
        if last and (now - last).total_seconds() < self.cooldown_minutes * 60:
            return False
        
        # Record this alert time
        self.last_alert_time[symbol][alert_type] = now
        return True
    
    def get_symbol_state(self, symbol: str) -> Dict:
        """Get current state for a symbol."""
        return {
            'last_G': self.last_G.get(symbol, 0.5),
            'last_bias': self.last_bias.get(symbol, 'NEUTRAL'),
            'last_alerts': self.last_alert_time.get(symbol, {})
        }


class GammaRatioBot(BaseAutoBot):
    """
    Gamma Ratio Bot
    
    Monitors gamma ratio (G) for all watchlist tickers and posts alerts
    when regime changes occur (call-driven <-> put-driven transitions).
    
    Uses constant-volatility BSM to calculate percent gamma, then aggregates
    by call/put side to produce the ratio.
    """
    
    def __init__(
        self,
        webhook_url: str,
        watchlist: List[str],
        fetcher: DataFetcher
    ):
        scan_interval = getattr(Config, 'GAMMA_RATIO_INTERVAL', 300)
        super().__init__(webhook_url, "Gamma Ratio Bot", scan_interval=scan_interval)
        
        self.watchlist = watchlist
        self.fetcher = fetcher
        
        # Configuration
        self.constant_vol = getattr(Config, 'GAMMA_RATIO_CONSTANT_VOL', 0.20)
        self.risk_free_rate = getattr(Config, 'GAMMA_RATIO_RISK_FREE_RATE', 0.0)
        self.min_open_interest = getattr(Config, 'GAMMA_RATIO_MIN_OI', 100)
        self.max_otm_pct = getattr(Config, 'GAMMA_RATIO_MAX_OTM_PCT', 0.20)
        
        # Alert thresholds (can be overridden via config)
        self.thresholds = {
            'extreme_put': getattr(Config, 'GAMMA_RATIO_EXTREME_PUT', 0.25),
            'put_driven': getattr(Config, 'GAMMA_RATIO_PUT_DRIVEN', 0.35),
            'call_driven': getattr(Config, 'GAMMA_RATIO_CALL_DRIVEN', 0.65),
            'extreme_call': getattr(Config, 'GAMMA_RATIO_EXTREME_CALL', 0.75),
        }
        
        # Initialize alert manager
        cooldown_minutes = getattr(Config, 'GAMMA_RATIO_COOLDOWN_MINUTES', 30)
        self.alert_manager = GammaAlertManager(cooldown_minutes=cooldown_minutes)
        
        # No batching - scan ALL tickers every cycle to catch regime changes
        # The calculation is lightweight (just math on fetched data)
        # Concurrency handles the API calls efficiently
        self.scan_batch_size = 0  # 0 = no batching, scan full watchlist
        
        logger.info(
            f"{self.name} initialized with {len(watchlist)} symbols, "
            f"interval={scan_interval}s, vol={self.constant_vol}"
        )
    
    @timed()
    async def scan_and_post(self):
        """Scan all watchlist symbols for gamma ratio changes."""
        logger.info(f"{self.name} starting gamma ratio scan")
        
        # Only scan during market hours
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """
        Scan a single symbol for gamma ratio and check for alerts.
        
        Returns list of alert signals to post.
        """
        try:
            # Get options chain snapshot
            contracts = await self.fetcher.get_option_chain_snapshot(symbol)
            if not contracts:
                logger.debug(f"{self.name} - No options data for {symbol}")
                return []
            
            # Get current spot price
            spot_price = None
            
            # Try to get spot from contract data first
            for contract in contracts:
                asset = contract.get('underlying_asset') or {}
                price = asset.get('price') or asset.get('close') or asset.get('prev_close')
                if price and float(price) > 0:
                    spot_price = float(price)
                    break
            
            # Fallback to fetcher
            if not spot_price:
                spot_price = await self.fetcher.get_stock_price(symbol)
            
            if not spot_price or spot_price <= 0:
                logger.debug(f"{self.name} - No spot price for {symbol}")
                return []
            
            # Transform Polygon snapshot to standard format
            standardized = transform_polygon_snapshot(contracts)
            
            if not standardized:
                logger.debug(f"{self.name} - No valid contracts for {symbol}")
                return []
            
            # Compute gamma ratio
            gamma_data = compute_gamma_ratio(
                options_chain=standardized,
                spot=spot_price,
                r=self.risk_free_rate,
                v=self.constant_vol,
                min_open_interest=self.min_open_interest,
                max_otm_pct=self.max_otm_pct
            )
            
            G = gamma_data['G']
            
            logger.debug(
                f"{self.name} - {symbol}: G={G:.3f}, bias={gamma_data['bias']}, "
                f"contracts={gamma_data['contracts_analyzed']}"
            )
            
            # Check for alerts
            alerts = self.alert_manager.check_alerts(symbol, G, gamma_data)
            
            # Add spot price to alert data
            for alert in alerts:
                alert['spot_price'] = spot_price
            
            return alerts
            
        except Exception as e:
            logger.error(f"{self.name} - Error scanning {symbol}: {e}")
            return []

    async def _post_signal(self, alert: Dict):
        """Post gamma ratio alert to Discord."""
        try:
            symbol = alert['symbol']
            G = alert['G']
            data = alert['data']
            regime = alert['regime']
            spot_price = alert.get('spot_price', 0)
            
            # Get color
            color = get_regime_color(regime)
            
            # Format gamma values
            call_gamma = data['call_gamma']
            put_gamma = data['put_gamma']
            
            def fmt_gamma(val):
                if abs(val) >= 1_000_000:
                    return f"{val/1_000_000:.2f}M"
                elif abs(val) >= 1_000:
                    return f"{val/1_000:.1f}K"
                else:
                    return f"{val:.2f}"

            # Generate gamma chart
            chart_image = ProfessionalCharts.create_gamma_chart(G, symbol, regime)
            
            # Regime-specific styling
            if 'ULTRA_EXTREME_PUT' in regime:
                title_emoji = "🔴🔴"
                regime_label = "ULTRA EXTREME PUT"
                bias_arrow = "⬇️⬇️ Massive downside convexity - CRASH RISK"
            elif 'EXTREME_PUT' in regime:
                title_emoji = "🔴"
                regime_label = "EXTREME PUT-DRIVEN"
                bias_arrow = "⬇️ Downside convexity dominating"
            elif 'ULTRA_EXTREME_CALL' in regime:
                title_emoji = "🟢🟢"
                regime_label = "ULTRA EXTREME CALL"
                bias_arrow = "⬆️⬆️ Massive upside convexity - SQUEEZE POTENTIAL"
            elif 'EXTREME_CALL' in regime:
                title_emoji = "🟢"
                regime_label = "EXTREME CALL-DRIVEN"
                bias_arrow = "⬆️ Upside convexity dominating"
            elif 'PUT_DRIVEN' in regime:
                title_emoji = "🟠"
                regime_label = "PUT-DRIVEN"
                bias_arrow = "↘️ Put gamma exceeds call gamma"
            elif 'CALL_DRIVEN' in regime:
                title_emoji = "🔵"
                regime_label = "CALL-DRIVEN"
                bias_arrow = "↗️ Call gamma exceeds put gamma"
            else:
                title_emoji = "⚪"
                regime_label = "NEUTRAL"
                bias_arrow = "↔️ Call/put gamma balanced"
            
            # Build title
            title = f"{title_emoji} {symbol} | {regime_label}"
            
            # Build description with key info
            description = (
                f"**G-Ratio: {G:.3f}**\n"
                f"{bias_arrow}"
            )
            
            # Build fields
            fields = [
                {
                    "name": "Call Γ",
                    "value": f"**{fmt_gamma(call_gamma)}**",
                    "inline": True
                },
                {
                    "name": "Put Γ",
                    "value": f"**{fmt_gamma(put_gamma)}**",
                    "inline": True
                },
                {
                    "name": "Spot Price",
                    "value": f"**${spot_price:.2f}**",
                    "inline": True
                }
            ]
            
            # Create embed with timestamp
            from datetime import datetime, timezone
            embed = self.create_embed(
                title=title,
                description=description,
                color=color,
                fields=fields,
                footer=f"G=0 Put-Driven | G=0.5 Neutral | G=1 Call-Driven"
            )
            embed['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            files = None
            if chart_image:
                embed['image'] = {'url': 'attachment://gamma_chart.png'}
                files = {'gamma_chart.png': chart_image}

            # Post to Discord
            success = await self.post_to_discord(embed, files=files)
            
            if success:
                logger.info(
                    f"🎯 GAMMA ALERT: {symbol} G={G:.2f} ({regime}) - "
                    f"Call:{fmt_gamma(call_gamma)} Put:{fmt_gamma(put_gamma)}"
                )
            
            return success
            
        except Exception as e:
            logger.error(f"{self.name} - Error posting alert: {e}")
            return False
    
    def get_symbol_gamma(self, symbol: str) -> Optional[Dict]:
        """
        Get cached gamma state for a symbol.
        
        Useful for query commands to get current G without triggering alerts.
        """
        state = self.alert_manager.get_symbol_state(symbol)
        if state['last_G'] != 0.5 or state['last_bias'] != 'NEUTRAL':
            return state
        return None
