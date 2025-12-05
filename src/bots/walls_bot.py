"""
Walls Bot - Support/Resistance Level Detector

Scans the Option Chain to find 'Walls' (Max Open Interest strikes).
Alerts when price approaches these magnetic levels.

The Logic:
- Finds strikes with highest Call OI and highest Put OI
- Labels based on PRICE POSITION relative to the wall:
  - Price BELOW wall = RESISTANCE (must break through going up)
  - Price ABOVE wall = SUPPORT (floor that catches you falling)

These levels act as magnets AND barriers. Price is drawn to them,
then often reverses when it hits them.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)


@dataclass
class WallLevel:
    """Represents a support/resistance wall"""
    strike: float
    oi: int
    wall_type: str  # 'CALL_WALL' (resistance) or 'PUT_WALL' (support)
    strength: str   # 'MODERATE', 'STRONG', 'MASSIVE'


class WallsBot(BaseAutoBot):
    """
    Scans the Option Chain to find 'Walls' (Max Open Interest).
    Alerts when price touches these levels (Magnet/Repel effect).
    
    Uses polling model - scans every 5 minutes to update walls
    and check for price proximity.
    """
    
    def __init__(
        self,
        webhook_url: str,
        watchlist: List[str],
        fetcher: DataFetcher,
        hedge_hunter: Optional[Any] = None,
        context_manager: Optional[Any] = None
    ):
        super().__init__(
            webhook_url,
            "Walls Bot",
            scan_interval=Config.WALLS_BOT_INTERVAL,
            hedge_hunter=hedge_hunter,
            context_manager=context_manager
        )
        
        self.watchlist = watchlist
        self.fetcher = fetcher
        
        # Walls Bot specific settings
        self.min_wall_oi = getattr(Config, 'WALLS_MIN_OI', 5000)
        self.proximity_pct = getattr(Config, 'WALLS_PROXIMITY_PCT', 0.005)  # 0.5% from wall
        self.max_dte_days = getattr(Config, 'WALLS_MAX_DTE_DAYS', 30)  # Only near-term
        self.cooldown_seconds = getattr(Config, 'WALLS_COOLDOWN_SECONDS', 3600)  # 1 hour per level
        
        # Cache walls to track changes
        self.walls_cache: Dict[str, Dict] = {}  # {symbol: {'call_wall': strike, 'put_wall': strike}}
        
        # Scan settings
        self.scan_batch_size = 0
        self.concurrency_limit = 15
        
        logger.info(
            f"Walls Bot initialized: "
            f"min_oi={self.min_wall_oi:,}, "
            f"proximity={self.proximity_pct*100:.1f}%"
        )
    
    async def scan_and_post(self):
        """
        Main scan loop - finds walls and checks for price proximity.
        """
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        logger.info(f"{self.name} scanning {len(self.watchlist)} symbols for walls...")
        
        alerts_sent = 0
        
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def scan_symbol(symbol: str) -> int:
            async with semaphore:
                try:
                    return await self._find_and_check_walls(symbol)
                except Exception as e:
                    logger.debug(f"{self.name} error scanning {symbol}: {e}")
                    return 0
        
        tasks = [scan_symbol(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, int):
                alerts_sent += result
        
        if alerts_sent > 0:
            logger.info(f"🧱 {self.name} sent {alerts_sent} wall alert(s)")
    
    async def _find_and_check_walls(self, symbol: str) -> int:
        """
        Find walls for a symbol and check if price is near them.
        
        Returns:
            Number of alerts sent
        """
        # Get options chain snapshot (1 API call - efficient)
        # IMPORTANT: Use get_option_chain_snapshot NOT get_options_snapshot (52+ calls)
        contracts = await self.fetcher.get_option_chain_snapshot(symbol)
        if not contracts:
            return 0
        
        # Get current price
        price = await self._get_current_price(symbol, contracts)
        if not price:
            return 0
        
        # Calculate expiry cutoff
        expiry_cutoff = (datetime.now() + timedelta(days=self.max_dte_days)).strftime('%Y-%m-%d')
        
        # Map OI by strike
        call_oi: Dict[float, int] = {}
        put_oi: Dict[float, int] = {}
        
        for contract in contracts:
            details = contract.get('details', {}) or {}
            oi = contract.get('open_interest', 0)
            
            if not oi or oi < 100:
                continue
            
            strike = details.get('strike_price', 0)
            expiration = details.get('expiration_date', '')
            contract_type = details.get('contract_type', '').lower()
            
            if not strike or not expiration:
                continue
            
            # Only include near-term contracts (where gamma/pinning matters)
            if expiration > expiry_cutoff:
                continue
            
            if contract_type == 'call':
                call_oi[strike] = call_oi.get(strike, 0) + oi
            elif contract_type == 'put':
                put_oi[strike] = put_oi.get(strike, 0) + oi
        
        if not call_oi or not put_oi:
            return 0
        
        # Find walls (max OI strikes)
        call_wall_strike = max(call_oi.keys(), key=lambda k: call_oi[k])
        call_wall_oi = call_oi[call_wall_strike]
        
        put_wall_strike = max(put_oi.keys(), key=lambda k: put_oi[k])
        put_wall_oi = put_oi[put_wall_strike]
        
        # Update cache
        self.walls_cache[symbol] = {
            'call_wall': call_wall_strike,
            'call_oi': call_wall_oi,
            'put_wall': put_wall_strike,
            'put_oi': put_wall_oi,
            'price': price,
            'updated': time.time()
        }
        
        alerts = 0
        
        # Check proximity to call wall
        if call_wall_oi >= self.min_wall_oi:
            call_distance_pct = abs(price - call_wall_strike) / price
            if call_distance_pct <= self.proximity_pct:
                # Determine wall type based on PRICE POSITION, not put/call
                # Price BELOW wall = RESISTANCE (must break through going up)
                # Price ABOVE wall = SUPPORT (floor that catches you)
                wall_type = "RESISTANCE" if price < call_wall_strike else "SUPPORT"
                success = await self._fire_wall_alert(
                    symbol, price, wall_type, 
                    call_wall_strike, call_wall_oi
                )
                if success:
                    alerts += 1
        
        # Check proximity to put wall
        if put_wall_oi >= self.min_wall_oi:
            put_distance_pct = abs(price - put_wall_strike) / price
            if put_distance_pct <= self.proximity_pct:
                # Same logic: position relative to wall determines type
                wall_type = "RESISTANCE" if price < put_wall_strike else "SUPPORT"
                success = await self._fire_wall_alert(
                    symbol, price, wall_type,
                    put_wall_strike, put_wall_oi
                )
                if success:
                    alerts += 1
        
        return alerts
    
    async def _get_current_price(self, symbol: str, contracts: List[Dict]) -> Optional[float]:
        """Get current underlying price"""
        # Try from snapshot first
        for contract in contracts:
            underlying = contract.get('underlying_asset', {}) or {}
            price = underlying.get('price')
            if price and price > 0:
                return float(price)
        
        # Fallback to direct quote
        try:
            price = await self.fetcher.get_current_price(symbol)
            return float(price) if price else None
        except:
            return None
    
    def _get_strength_label(self, oi: int) -> str:
        """Classify wall strength based on OI"""
        if oi >= 100000:
            return "MASSIVE 🔥🔥🔥"
        elif oi >= 50000:
            return "STRONG 🔥🔥"
        elif oi >= 20000:
            return "MODERATE 🔥"
        else:
            return "LIGHT"
    
    async def _fire_wall_alert(
        self, 
        symbol: str, 
        price: float, 
        wall_type: str,
        level: float, 
        oi: int
    ) -> bool:
        """
        Send wall proximity alert to Discord.
        """
        # Check cooldown (1 hour per symbol+level)
        cooldown_key = f"{symbol}_{wall_type}_{level:.0f}"
        if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
            return False
        
        is_resistance = wall_type == "RESISTANCE"
        emoji = "🧱" if is_resistance else "🛡️"
        color = 0xE74C3C if is_resistance else 0x2ECC71  # Red or Green
        
        strength = self._get_strength_label(oi)
        
        distance_pct = abs(price - level) / price * 100
        position = "above" if price > level else "below" if price < level else "at"
        
        description = (
            f"**Current Price:** ${price:.2f} ({position} wall)\n"
            f"**{wall_type} Level:** ${level:.2f}\n"
            f"**Distance:** {distance_pct:.2f}%\n"
            f"**Wall Strength:** {strength}\n"
            f"**Open Interest:** {oi:,} contracts\n\n"
        )
        
        if is_resistance:
            description += "*⚠️ Expect rejection or choppiness at this level*"
        else:
            description += "*✅ Expect bounce or defense at this level*"
        
        # Get GEX context if available
        gex_field = None
        if self.context_manager:
            try:
                context = self.context_manager.get_context(symbol)
                regime = context.get('regime', 'NEUTRAL')
                if regime != 'NEUTRAL':
                    gex_emoji = "🟢" if regime == "POSITIVE_GAMMA" else "🔴"
                    gex_text = f"{gex_emoji} {regime.replace('_', ' ').title()}"
                    flip = context.get('flip_level', 0)
                    if flip > 0:
                        gex_text += f"\nFlip: ${flip:.0f}"
                    gex_field = {"name": "GEX Regime", "value": gex_text, "inline": True}
            except:
                pass
        
        fields = [
            {"name": "Symbol", "value": symbol, "inline": True},
            {"name": "Wall Type", "value": f"{emoji} {wall_type}", "inline": True},
            {"name": "Strength", "value": strength, "inline": True},
        ]
        
        if gex_field:
            fields.append(gex_field)
        
        embed = self.create_signal_embed_with_disclaimer(
            title=f"{emoji} {symbol} Approaching {wall_type} Wall",
            description=description,
            color=color,
            fields=fields,
            footer="Walls Bot • Support/Resistance detector"
        )
        
        success = await self.post_to_discord(embed)
        
        if success:
            self._mark_cooldown(cooldown_key)
            logger.info(
                f"{emoji} WALL: {symbol} at ${price:.2f} near "
                f"{wall_type} ${level:.2f} (OI: {oi:,})"
            )
        
        return success
    
    def get_walls_for_symbol(self, symbol: str) -> Optional[Dict]:
        """Get cached wall data for a symbol (for other bots to use)"""
        return self.walls_cache.get(symbol)

