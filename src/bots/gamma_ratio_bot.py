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
from src.utils.enhanced_analysis import EnhancedAnalyzer


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
    
    # Ultra extreme thresholds - escalation alerts that bypass cooldown
    ULTRA_EXTREME_CALL = 0.85  # G > 0.85 = massive call-driven
    ULTRA_EXTREME_PUT = 0.15   # G < 0.15 = massive put-driven
    
    def __init__(self, cooldown_minutes: int = 30):
        self.cooldown_minutes = cooldown_minutes
        self.last_alert_time: Dict[str, Dict[str, datetime]] = {}  # symbol -> {alert_type: timestamp}
        self.last_G: Dict[str, float] = {}  # symbol -> last G value
        self.last_alerted_G: Dict[str, float] = {}  # symbol -> G value when last alerted (for escalation)
        self.last_bias: Dict[str, str] = {}  # symbol -> last bias classification
    
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
        # #region agent log
        import logging; logging.getLogger(__name__).info(f"[DEBUG_ALERT] {symbol} | AlertMgr_State | G={G:.4f} | Prev_G={prev_G:.4f} | Last_Alerted={last_alerted if last_alerted else 'None'} | Extreme_Call_Thresh={self.ULTRA_EXTREME_CALL} | Extreme_Put_Thresh={self.ULTRA_EXTREME_PUT}")
        # #endregion
        
        # Determine current regime
        current_regime, priority = classify_gamma_regime(G)
        
        # Check for regime change alerts
        thresholds = GAMMA_THRESHOLDS
        
        # === CALL SIDE ===
        # MIDDLE GROUND: Only alert on EXTREME+ levels (G > 0.75)
        # This filters out low-conviction CALL_DRIVEN (0.65-0.75) alerts
        
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
        # Check for EXTREME CALL (high threshold) - G > 0.75
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
        # REMOVED: CALL_DRIVEN (0.65) alerts - too noisy, keep only EXTREME+
        
        # === PUT SIDE ===
        # MIDDLE GROUND: Only alert on EXTREME+ levels (G < 0.25)
        # This filters out low-conviction PUT_DRIVEN (0.25-0.35) alerts
        
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
        # Check for EXTREME PUT (high threshold) - G < 0.25
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
        # REMOVED: PUT_DRIVEN (0.35) alerts - too noisy, keep only EXTREME+
        
        # Apply cooldown filter (unless bypass_cooldown is set)
        filtered_alerts = []
        for alert in alerts:
            if alert.get('bypass_cooldown') or self._check_cooldown(symbol, alert['type'], now):
                filtered_alerts.append(alert)
                # Update last alerted G for escalation tracking
                self.last_alerted_G[symbol] = G
        
        # Update state
        self.last_G[symbol] = G
        self.last_bias[symbol] = current_regime
        
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
        
        self.fetcher = fetcher
        self.watchlist = watchlist
        
        # Enhanced analyzer for P and V calculations (Four Axes)
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        
        # Configuration
        self.constant_vol = getattr(Config, 'GAMMA_RATIO_CONSTANT_VOL', 0.20)
        self.risk_free_rate = getattr(Config, 'GAMMA_RATIO_RISK_FREE_RATE', 0.0)
        self.min_open_interest = getattr(Config, 'GAMMA_RATIO_MIN_OI', 100)
        self.max_otm_pct = getattr(Config, 'GAMMA_RATIO_MAX_OTM_PCT', 0.20)
        # Liquidity filter - min total gamma to avoid illiquid names
        self.min_total_gamma = getattr(Config, 'GAMMA_RATIO_MIN_TOTAL_GAMMA', 5000)
        
        # Alert thresholds - only EXTREME+ alerts (G > 0.75 or G < 0.25)
        self.thresholds = {
            'extreme_put': getattr(Config, 'GAMMA_RATIO_EXTREME_PUT', 0.25),
            'put_driven': getattr(Config, 'GAMMA_RATIO_PUT_DRIVEN', 0.35),
            'call_driven': getattr(Config, 'GAMMA_RATIO_CALL_DRIVEN', 0.65),
            'extreme_call': getattr(Config, 'GAMMA_RATIO_EXTREME_CALL', 0.75),
        }
        
        # Initialize alert manager with cooldown to prevent spam
        cooldown_minutes = getattr(Config, 'GAMMA_RATIO_COOLDOWN_MINUTES', 30)
        self.alert_manager = GammaAlertManager(cooldown_minutes=cooldown_minutes)
        
        # Scan ALL tickers every cycle - no batching
        # High concurrency to complete fast: 396 symbols / 30 concurrent ≈ 30-60 seconds
        self.scan_batch_size = 0  # 0 = no batching, scan full watchlist
        self.concurrency_limit = 30  # High concurrency for speed
        
        logger.info(
            f"{self.name} initialized with {len(watchlist)} symbols, "
            f"interval={scan_interval}s, vol={self.constant_vol}"
        )
        # #region agent log
        logger.info(f"[DEBUG_SCAN] >>> {self.name} webhook_url={webhook_url[:50]}... | thresholds={self.thresholds}")
        # #endregion
    
    @timed()
    async def scan_and_post(self):
        """Scan all watchlist symbols for gamma ratio changes."""
        logger.info(f"[DEBUG_SCAN] >>> {self.name} scan_and_post() CALLED - watchlist={len(self.watchlist)} symbols")
        logger.info(f"{self.name} starting gamma ratio scan")
        
        # Only scan during market hours
        if not MarketHours.is_market_open(include_extended=False):
            logger.info(f"[DEBUG_SCAN] >>> {self.name} SKIPPED - Market closed")
            return
        
        # Skip first 15 minutes after open to avoid opening noise
        # Market opens at 9:30 AM ET, so skip until 9:45 AM ET
        from datetime import datetime
        import pytz
        et_tz = pytz.timezone('US/Eastern')
        now_et = datetime.now(et_tz)
        market_open_time = now_et.replace(hour=9, minute=45, second=0, microsecond=0)
        
        if now_et < market_open_time:
            logger.info(f"[DEBUG_SCAN] >>> {self.name} SKIPPED - Before 9:45 AM ET ({now_et.strftime('%H:%M:%S')})")
            return
        
        logger.info(f"[DEBUG_SCAN] >>> {self.name} PROCEEDING with scan at {now_et.strftime('%H:%M:%S')} ET")
        # Use base class concurrent implementation
        await super().scan_and_post()
    
    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        """
        Scan a single symbol for gamma ratio and check for alerts.
        
        Returns list of alert signals to post.
        """
        # #region agent log - ENTRY POINT
        logger.info(f"[DEBUG_SCAN] >>> ENTERING _scan_symbol for {symbol}")
        # #endregion
        try:
            # Get options chain snapshot - OPTIMIZED for gamma calculation:
            # 1. Limit contracts (default 750, ~3 pages) - enough for accurate G ratio
            # 2. Only near-term expiries (default 45 days) - where gamma impact is highest
            from datetime import datetime, timedelta
            max_contracts = getattr(Config, 'GAMMA_RATIO_MAX_CONTRACTS', 750)
            expiry_days = getattr(Config, 'GAMMA_RATIO_EXPIRY_DAYS', 45)
            expiry_cutoff = (datetime.now() + timedelta(days=expiry_days)).strftime('%Y-%m-%d')
            
            contracts = await self.fetcher.get_option_chain_snapshot(
                symbol,
                max_contracts=max_contracts,
                expiration_date_lte=expiry_cutoff
            )
            # #region agent log
            logger.info(f"[DEBUG_SCAN] {symbol} | Contracts_Fetched={len(contracts) if contracts else 0} | Has_Data={bool(contracts)}")
            # #endregion
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
            # #region agent log
            logger.info(f"[DEBUG_SCAN] {symbol} | Standardized={len(standardized) if standardized else 0} | Raw={len(contracts)}")
            # #endregion
            
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
            call_gamma = gamma_data.get('call_gamma', 0)
            put_gamma = gamma_data.get('put_gamma', 0)
            total_gamma = call_gamma + put_gamma
            # #region agent log
            logger.info(f"[DEBUG_SCAN] {symbol} | G={G:.4f} | CallGamma={call_gamma:.0f} | PutGamma={put_gamma:.0f} | TotalGamma={total_gamma:.0f} | Contracts_Analyzed={gamma_data.get('contracts_analyzed',0)} | Bias={gamma_data.get('bias','')}")
            # #endregion
            
            logger.debug(
                f"{self.name} - {symbol}: G={G:.3f}, bias={gamma_data['bias']}, "
                f"contracts={gamma_data['contracts_analyzed']}, total_gamma={total_gamma:.0f}"
            )
            
            # Filter: Minimum total gamma (filter out illiquid/low-volume names)
            # #region agent log
            logger.info(f"[DEBUG_SCAN] {symbol} | Gamma_Filter_Check | TotalGamma={total_gamma:.0f} | Min_Required={self.min_total_gamma} | Will_Filter={total_gamma < self.min_total_gamma}")
            # #endregion
            if total_gamma < self.min_total_gamma:
                logger.info(f"[DEBUG_SCAN] {symbol} | **FILTERED** | Reason=Low_TotalGamma | {total_gamma:.0f} < {self.min_total_gamma}")
                return []
            
            # Check for alerts
            alerts = self.alert_manager.check_alerts(symbol, G, gamma_data)
            # #region agent log
            logger.info(f"[DEBUG_SCAN] {symbol} | Alert_Check_Result | G={G:.4f} | Alert_Count={len(alerts)} | Has_Alerts={bool(alerts)}")
            # #endregion
            
            # Log when we find alertable conditions
            if alerts:
                logger.info(f"{self.name} - {symbol} triggered {len(alerts)} alerts: G={G:.4f}")
                
                # Fetch P and V for Four Axes context (only when we have alerts to reduce API calls)
                market_context = None
                try:
                    market_context = await self.enhanced_analyzer.get_market_context(symbol, G=G)
                except Exception as ctx_err:
                    logger.debug(f"{self.name} - Could not fetch market context for {symbol}: {ctx_err}")
                
                for alert in alerts:
                    alert['spot_price'] = spot_price
                    alert['market_context'] = market_context.to_dict() if market_context else None
                    try:
                        await self._post_signal(alert)
                    except Exception as post_err:
                        logger.error(f"{self.name} - Failed to post alert for {symbol}: {post_err}")
            elif G > 0.75 or G < 0.25:
                logger.debug(f"{self.name} - {symbol} in extreme zone (G={G:.4f}) but no new alert (prev already crossed)")
            
            # Alerts already posted (if any)
            return []
            
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
            
            # Four Axes: Add P (price trend) and V (volatility trend) context
            market_context = alert.get('market_context')
            if market_context:
                P = market_context.get("P", 0)
                V = market_context.get("V", 0)
                ctx_regime = market_context.get("regime", "NEUTRAL")
                
                # Determine alignment between G regime and P/V context
                alignment_note = ""
                if 'CALL' in regime and P > 0.2:
                    alignment_note = "✅ Aligned with uptrend"
                elif 'PUT' in regime and P < -0.2:
                    alignment_note = "✅ Aligned with downtrend"
                elif 'CALL' in regime and P < -0.2:
                    alignment_note = "⚠️ G bullish but P bearish"
                elif 'PUT' in regime and P > 0.2:
                    alignment_note = "⚠️ G bearish but P bullish"
                
                vol_note = ""
                if V > 0.015:
                    vol_note = "📈 Vol expanding"
                elif V < -0.015:
                    vol_note = "📉 Vol contracting"
                
                context_parts = [f"**P={P:+.2f}** | **V={V:+.3f}**"]
                if alignment_note:
                    context_parts.append(alignment_note)
                if vol_note:
                    context_parts.append(vol_note)
                
                fields.append({
                    "name": "📐 Four Axes Context",
                    "value": "\n".join(context_parts),
                    "inline": False
                })
            
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
            
            # Note: Chart image disabled for now - base_bot doesn't support file uploads
            # TODO: Add multipart form support to base_bot for chart images
            
            # Post to Discord
            logger.info(f"{self.name} posting alert for {symbol} G={G:.2f} ({regime})...")
            success = await self.post_to_discord(embed)
            
            if success:
                logger.info(
                    f"🎯 GAMMA ALERT POSTED: {symbol} G={G:.2f} ({regime}) - "
                    f"Call:{fmt_gamma(call_gamma)} Put:{fmt_gamma(put_gamma)}"
                )
            else:
                logger.warning(f"{self.name} - Discord post failed for {symbol}")
            
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
