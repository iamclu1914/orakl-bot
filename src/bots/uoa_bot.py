"""
Unusual Options Activity (UOA) Bot

Kafka stream consumer that detects and alerts on unusual options flow.
No watchlist - reacts to ANY ticker showing anomalous characteristics.

Key Features:
- Consumes from same Kafka topic as flow bots
- Applies UnusualActivityDetector rules
- Posts to dedicated #unusual-activity Discord channel
- Per-symbol cooldown to prevent spam
- Severity-based formatting (notable, significant, whale)
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Any, List
from collections import defaultdict

from src.config import Config
from src.uoa_detector import UnusualActivityDetector, UOASignal
from src.utils.option_contract_format import (
    format_option_contract_sentence,
)

logger = logging.getLogger(__name__)


class UOABot:
    """
    Unusual Options Activity Bot - Stream filter for Kafka events.
    
    Unlike other bots, UOA has no watchlist. It analyzes every enriched
    trade from Kafka and fires when unusual patterns are detected.
    
    Usage:
        bot = UOABot(webhook_url)
        await bot.process_event(enriched_trade)  # Called by KafkaFlowListener
    """
    
    def __init__(self, webhook_url: str):
        self.name = "UOA Bot"
        self.webhook_url = webhook_url
        self.enabled = Config.UOA_ENABLED and bool(webhook_url)
        
        # Initialize detector
        self.detector = UnusualActivityDetector()
        
        # Cooldown tracking (per-symbol)
        self.cooldowns: Dict[str, float] = {}  # symbol -> last_alert_time
        self.contract_cooldowns: Dict[str, float] = {}  # contract_key -> last_alert_time
        self.alert_counts: Dict[str, List[float]] = defaultdict(list)  # symbol -> [timestamps]
        self.global_alert_timestamps: List[float] = []
        
        # Config
        self.cooldown_seconds = Config.UOA_COOLDOWN_SECONDS
        self.contract_cooldown_seconds = int(getattr(Config, "UOA_CONTRACT_COOLDOWN_SECONDS", 900))
        self.max_alerts_per_minute = int(getattr(Config, "UOA_MAX_ALERTS_PER_MINUTE", 20))
        self.max_alerts_per_symbol = Config.UOA_MAX_ALERTS_PER_SYMBOL
        self.alert_window = Config.UOA_ALERT_WINDOW_SECONDS
        
        # Stats
        self.events_processed = 0
        self.alerts_sent = 0
        self.alerts_suppressed = 0
        
        if self.enabled:
            logger.info(
                f"UOA Bot initialized: "
                f"cooldown={self.cooldown_seconds}s, "
                f"max_per_symbol={self.max_alerts_per_symbol}/hr"
            )
        else:
            logger.warning("UOA Bot DISABLED (missing webhook or UOA_ENABLED=false)")
    
    async def process_event(self, enriched_trade: Dict) -> Optional[Dict]:
        """
        Process an enriched trade event from Kafka.
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, Bid/Ask
            
        Returns:
            Alert dict if posted, None otherwise
        """
        if not self.enabled:
            return None
        
        self.events_processed += 1

        # Global rule: do not alert on index underlyings (SPX/SPXW/VIX/VIXW/NDX/etc).
        # Even though we block these upstream, enforce here as a final safety net.
        if getattr(Config, "BLOCK_INDEX_SYMBOLS", True):
            try:
                symbol = str(enriched_trade.get("symbol") or enriched_trade.get("ticker") or "").strip().upper()
                underlying = str(enriched_trade.get("underlying") or "").strip().upper()
                contract_ticker = str(enriched_trade.get("contract_ticker") or enriched_trade.get("contract") or "").strip().upper()
                blocked = set(getattr(Config, "INDEX_SYMBOLS_BLOCKLIST", []))
                if (
                    symbol in blocked
                    or underlying.startswith("I:")
                    or underlying.replace("I:", "") in blocked
                    or any(contract_ticker.startswith(f"O:{root}") for root in blocked if root)
                ):
                    return None
            except Exception:
                pass
        
        # Analyze for unusual activity
        signal = self.detector.analyze(enriched_trade)
        
        if not signal.is_unusual:
            return None
        
        # Check cooldown
        if not self._can_alert(signal):
            self.alerts_suppressed += 1
            logger.debug(f"UOA suppressed for {signal.symbol} (cooldown/rate limit)")
            return None
        
        # Post alert
        success = await self._post_alert(signal)
        
        if success:
            self._mark_alert(signal)
            self.alerts_sent += 1
            return signal.to_dict()
        
        return None
    
    def _build_contract_key(self, signal: UOASignal) -> str:
        exp = (getattr(signal, "expiration_date", "") or "").strip()
        try:
            strike = float(getattr(signal, "strike", 0) or 0)
        except Exception:
            strike = 0.0
        side = (getattr(signal, "side", "") or "").strip().lower()
        return f"{signal.symbol}_{side}_{strike:.4f}_{exp}"

    def _can_alert(self, signal: UOASignal) -> bool:
        """Check if we can send an alert (global + per-symbol + per-contract)."""
        now = time.time()
        
        # Global throttle (protect Discord + reduce channel spam)
        cutoff_global = now - 60.0
        self.global_alert_timestamps = [t for t in self.global_alert_timestamps if t > cutoff_global]
        if len(self.global_alert_timestamps) >= self.max_alerts_per_minute:
            return False

        # Per-contract cooldown (dedupe repeated prints of same strike/exp)
        contract_key = self._build_contract_key(signal)
        last_contract = self.contract_cooldowns.get(contract_key, 0)
        if now - last_contract < self.contract_cooldown_seconds:
            return False

        # Check cooldown
        symbol = signal.symbol
        last_alert = self.cooldowns.get(symbol, 0)
        if now - last_alert < self.cooldown_seconds:
            return False
        
        # Check rate limit (max alerts per symbol per window)
        timestamps = self.alert_counts[symbol]
        
        # Clean old timestamps
        cutoff = now - self.alert_window
        timestamps = [t for t in timestamps if t > cutoff]
        self.alert_counts[symbol] = timestamps
        
        if len(timestamps) >= self.max_alerts_per_symbol:
            return False
        
        return True
    
    def _mark_alert(self, signal: UOASignal):
        """Mark that an alert was sent (global + symbol + contract)."""
        now = time.time()
        symbol = signal.symbol
        self.cooldowns[symbol] = now
        self.alert_counts[symbol].append(now)
        self.contract_cooldowns[self._build_contract_key(signal)] = now
        self.global_alert_timestamps.append(now)
    
    async def _post_alert(self, signal: UOASignal) -> bool:
        """Post UOA alert to Discord webhook."""
        try:
            import aiohttp

            contract_sentence = format_option_contract_sentence(
                signal.strike,
                signal.side,
                getattr(signal, "expiration_date", ""),
                signal.dte,
            )
            # Contract ID is intentionally hidden from Discord embeds (too noisy for UOA).
            # Keep formatting util import available for future optional toggles.
            
            # Determine color based on severity
            if signal.severity == 'whale':
                color = 0xFFD700  # Gold
                emoji = "🐋"
                title_suffix = "WHALE ACTIVITY"
            elif signal.severity == 'significant':
                color = 0xFF6B00  # Orange
                emoji = "🔥"
                title_suffix = "Significant Flow"
            else:
                color = 0x00CED1  # Cyan
                emoji = "👁️"
                title_suffix = "Unusual Activity"
            
            # Side-specific formatting
            side_emoji = "🟢" if signal.side == 'call' else "🔴"
            side_text = signal.side.upper()
            
            # Format reasons
            reasons_text = "\n".join([f"• {r}" for r in signal.reasons])
            
            # Build embed
            embed = {
                "title": f"{emoji} {signal.symbol} - {title_suffix}",
                "description": f"{side_emoji} **{contract_sentence}**",
                "color": color,
                "fields": [
                    {
                        "name": "Premium",
                        "value": f"${signal.premium:,.0f}",
                        "inline": True
                    },
                    {
                        "name": "Vol/OI",
                        "value": f"{signal.vol_oi_ratio:.1f}x",
                        "inline": True
                    },
                    {
                        "name": "DTE",
                        "value": str(signal.dte),
                        "inline": True
                    },
                    {
                        "name": "Volume",
                        "value": f"{signal.vol:,}",
                        "inline": True
                    },
                    {
                        "name": "Open Interest",
                        "value": f"{signal.oi:,}",
                        "inline": True
                    },
                    {
                        "name": "Trade Size",
                        "value": f"{signal.size:,}",
                        "inline": True
                    },
                    {
                        "name": "Spot Price",
                        "value": f"${signal.underlying_price:.2f}" if float(signal.underlying_price or 0) > 0 else "Unavailable",
                        "inline": True
                    },
                    {
                        "name": "OTM %",
                        "value": f"{signal.otm_pct*100:.1f}%" if float(signal.underlying_price or 0) > 0 else "Unavailable",
                        "inline": True
                    },
                    {
                        "name": "Contract Price",
                        "value": f"${signal.contract_price:.2f}",
                        "inline": True
                    },
                    {
                        "name": "Why Unusual",
                        "value": reasons_text or "Multiple factors",
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "ORAKL UOA Bot • Stream Filter • Not financial advice"
                },
                "timestamp": signal.timestamp
            }
            
            payload = {
                "embeds": [embed],
                "username": "ORAKL UOA Bot"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 204:
                        logger.info(
                            f"UOA ALERT: {signal.symbol} {signal.side.upper()} "
                            f"${signal.premium:,.0f} [{signal.severity}]"
                        )
                        return True
                    elif response.status == 429:
                        logger.warning("UOA webhook rate limited")
                        return False
                    else:
                        logger.error(f"UOA webhook error: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"UOA post error: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bot statistics."""
        return {
            'enabled': self.enabled,
            'events_processed': self.events_processed,
            'alerts_sent': self.alerts_sent,
            'alerts_suppressed': self.alerts_suppressed,
            'alert_rate': self.alerts_sent / max(1, self.events_processed),
            'detector_stats': self.detector.get_stats(),
            'active_cooldowns': len(self.cooldowns),
        }
    
    def reset_cooldowns(self):
        """Clear all cooldowns (for testing/admin)."""
        self.cooldowns.clear()
        self.alert_counts.clear()
        logger.info("UOA cooldowns reset")

