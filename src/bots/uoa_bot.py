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
        self.alert_counts: Dict[str, List[float]] = defaultdict(list)  # symbol -> [timestamps]
        
        # Config
        self.cooldown_seconds = Config.UOA_COOLDOWN_SECONDS
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
        
        # Analyze for unusual activity
        signal = self.detector.analyze(enriched_trade)
        
        if not signal.is_unusual:
            return None
        
        # Check cooldown
        if not self._can_alert(signal.symbol):
            self.alerts_suppressed += 1
            logger.debug(f"UOA suppressed for {signal.symbol} (cooldown/rate limit)")
            return None
        
        # Post alert
        success = await self._post_alert(signal)
        
        if success:
            self._mark_alert(signal.symbol)
            self.alerts_sent += 1
            return signal.to_dict()
        
        return None
    
    def _can_alert(self, symbol: str) -> bool:
        """Check if we can send an alert for this symbol."""
        now = time.time()
        
        # Check cooldown
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
    
    def _mark_alert(self, symbol: str):
        """Mark that an alert was sent for this symbol."""
        now = time.time()
        self.cooldowns[symbol] = now
        self.alert_counts[symbol].append(now)
    
    async def _post_alert(self, signal: UOASignal) -> bool:
        """Post UOA alert to Discord webhook."""
        try:
            import aiohttp
            
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
                "description": f"**{side_emoji} {side_text}** @ ${signal.strike:.2f}",
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
                        "value": f"${signal.underlying_price:.2f}",
                        "inline": True
                    },
                    {
                        "name": "OTM %",
                        "value": f"{signal.otm_pct*100:.1f}%",
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

