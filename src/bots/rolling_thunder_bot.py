"""
Rolling Thunder Bot - Detects Whale Position Rolls

SAFE INTEGRATION VERSION: Works with existing BotManager polling model.

The Signal: A Whale sells a winning position (taking profit) and immediately
(within seconds) buys a larger, further-out position.

The Meaning: "I am not leaving. I am doubling down."

The Alpha: These are the highest conviction signals in the market because
they require active management and capital commitment.

Logic:
1. Scan watchlist every 60 seconds
2. For each symbol, get recent options trades (last 60s window)
3. Identify SELLs (at Bid) on < 14 DTE contracts
4. Identify BUYs (at Ask) on > 21 DTE contracts  
5. If a BUY matches a SELL within 5 seconds, trigger "Rolling Thunder" alert
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.market_hours import MarketHours

logger = logging.getLogger(__name__)


@dataclass
class TradeLeg:
    """Represents one leg of a potential roll"""
    symbol: str
    option_ticker: str
    strike: float
    expiration: str
    contract_type: str  # 'call' or 'put'
    dte: float
    price: float
    size: int
    premium: float
    timestamp_ns: int
    side: str  # 'buy' or 'sell'
    

class RollingThunderBot(BaseAutoBot):
    """
    Detects 'Rolls': When a Whale closes a near-term position and
    immediately opens a further-out position.
    
    SAFE INTEGRATION: Uses polling model, no WebSocket required.
    Inherits from BaseAutoBot for full compatibility with BotManager.
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
            "Rolling Thunder Bot",
            scan_interval=Config.ROLLING_THUNDER_INTERVAL,
            hedge_hunter=hedge_hunter,
            context_manager=context_manager
        )
        
        self.watchlist = watchlist
        self.fetcher = fetcher
        
        # Rolling Thunder specific settings
        self.lookback_seconds = getattr(Config, 'ROLL_LOOKBACK_SECONDS', 60)
        self.min_roll_premium = getattr(Config, 'ROLL_MIN_PREMIUM', 150000)
        self.max_gap_seconds = getattr(Config, 'ROLL_MAX_GAP_SECONDS', 5)
        self.near_term_dte = getattr(Config, 'ROLL_NEAR_DTE', 14)
        self.far_term_dte = getattr(Config, 'ROLL_FAR_DTE', 21)
        self.cooldown_seconds = getattr(Config, 'ROLL_COOLDOWN_SECONDS', 1800)
        
        # Track recent rolls to prevent duplicates
        self._recent_rolls: Dict[str, float] = {}  # key -> timestamp
        
        # Full scan mode
        self.scan_batch_size = 0
        self.concurrency_limit = 20
        
        # ORAKL v2.0: Sliding window buffer for Kafka event sequence matching
        # Stores recent trades to match Sell + Buy sequences across events
        self.trade_history: deque = deque(maxlen=1000)  # Last 1000 trades
        
        logger.info(
            f"Rolling Thunder Bot initialized: "
            f"min_premium=${self.min_roll_premium:,}, "
            f"near_dte<{self.near_term_dte}, "
            f"far_dte>{self.far_term_dte}"
        )

    # =========================================================================
    # ORAKL v2.0: Kafka Event Processing with Sliding Window Buffer
    # =========================================================================
    
    async def process_event(self, enriched_trade: Dict) -> Optional[Dict]:
        """
        Process a single enriched trade event from Kafka for roll detection.
        
        CRITICAL: Rolling Thunder needs to match Sell + Buy sequences.
        Since Kafka delivers events one at a time, we use a sliding window
        buffer (deque) to track recent trades and look for matches.
        
        Flow:
        1. Add current trade to history
        2. If this is a BUY (far-term), look back for matching SELLs (near-term)
        3. If found, create roll alert
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, Bid/Ask
            
        Returns:
            Alert payload dict if roll detected, None otherwise
        """
        try:
            symbol = enriched_trade.get('symbol', '')
            premium = float(enriched_trade.get('premium', 0))
            
            # Skip if below minimum premium
            if premium < self.min_roll_premium:
                return None
            
            # Extract key fields
            strike = float(enriched_trade.get('strike_price', 0))
            contract_type = enriched_trade.get('contract_type', '').lower()
            dte = int(enriched_trade.get('dte', 0))
            trade_size = int(enriched_trade.get('trade_size', 0))
            contract_price = float(enriched_trade.get('trade_price', 0))
            
            # Determine trade side from enriched data
            # 'side' = 'ask' means aggressive buy, 'side' = 'bid' means aggressive sell
            side = enriched_trade.get('side', '').lower()
            if side == 'ask':
                trade_side = 'buy'
            elif side == 'bid':
                trade_side = 'sell'
            else:
                # Try to infer from bid/ask proximity
                bid = float(enriched_trade.get('current_bid', 0))
                ask = float(enriched_trade.get('current_ask', 0))
                if contract_price > 0 and bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    trade_side = 'buy' if contract_price >= mid else 'sell'
                else:
                    return None  # Can't determine side
            
            # Get timestamp (use event timestamp or current time in nanoseconds)
            event_ts = enriched_trade.get('event_timestamp') or enriched_trade.get('timestamp')
            if isinstance(event_ts, str):
                try:
                    dt = datetime.fromisoformat(event_ts.replace('Z', '+00:00'))
                    timestamp_ns = int(dt.timestamp() * 1e9)
                except:
                    timestamp_ns = int(time.time() * 1e9)
            elif isinstance(event_ts, (int, float)):
                timestamp_ns = int(event_ts * 1e9) if event_ts < 1e12 else int(event_ts)
            else:
                timestamp_ns = int(time.time() * 1e9)
            
            # Create trade record
            trade_record = {
                'symbol': symbol,
                'option_ticker': enriched_trade.get('contract_ticker', ''),
                'strike': strike,
                'expiration': enriched_trade.get('expiration_date', ''),
                'contract_type': contract_type,
                'dte': dte,
                'price': contract_price,
                'size': trade_size,
                'premium': premium,
                'timestamp': timestamp_ns,
                'side': trade_side
            }
            
            # Add to sliding window buffer
            self.trade_history.append(trade_record)
            
            # ROLL DETECTION: If this is a BUY (far-term), look back for matching SELLs
            if trade_side == 'buy' and dte > self.far_term_dte:
                # Look for matching SELL in the buffer
                max_age_ns = self.max_gap_seconds * 1e9
                
                for past_trade in self.trade_history:
                    # Must be same symbol
                    if past_trade['symbol'] != symbol:
                        continue
                    
                    # Must be same contract type
                    if past_trade['contract_type'] != contract_type:
                        continue
                    
                    # Must be a SELL (near-term position closing)
                    if past_trade['side'] != 'sell':
                        continue
                    
                    # Must be near-term DTE (closing leg)
                    if past_trade['dte'] > self.near_term_dte:
                        continue
                    
                    # Must be within time window
                    time_diff = timestamp_ns - past_trade['timestamp']
                    if time_diff < 0 or time_diff > max_age_ns:
                        continue
                    
                    # Found a match! Create roll alert
                    roll_alert = await self._create_roll_alert_from_kafka(
                        past_trade,  # Sell leg (closing)
                        trade_record  # Buy leg (opening)
                    )
                    
                    if roll_alert:
                        return roll_alert
            
            return None
            
        except Exception as e:
            logger.error(f"{self.name} error processing event: {e}")
            return None
    
    async def _create_roll_alert_from_kafka(
        self,
        sell_leg: Dict,
        buy_leg: Dict
    ) -> Optional[Dict]:
        """
        Create a roll alert from matched Kafka events.
        
        Args:
            sell_leg: The closing (sell) trade
            buy_leg: The opening (buy) trade
            
        Returns:
            Alert dict if successful, None if cooldown active
        """
        symbol = buy_leg['symbol']
        
        # Check cooldown
        cooldown_key = f"roll_{symbol}_{sell_leg['strike']}_{buy_leg['strike']}"
        if self._is_in_cooldown(cooldown_key):
            return None
        
        # Mark cooldown
        self._mark_cooldown_roll(cooldown_key)
        
        # Calculate combined premium
        total_premium = sell_leg['premium'] + buy_leg['premium']
        
        # Build roll data
        roll = {
            'symbol': symbol,
            'contract_type': buy_leg['contract_type'].upper(),
            'sell_strike': sell_leg['strike'],
            'sell_exp': sell_leg['expiration'],
            'sell_dte': sell_leg['dte'],
            'sell_premium': sell_leg['premium'],
            'sell_size': sell_leg['size'],
            'buy_strike': buy_leg['strike'],
            'buy_exp': buy_leg['expiration'],
            'buy_dte': buy_leg['dte'],
            'buy_premium': buy_leg['premium'],
            'buy_size': buy_leg['size'],
            'total_premium': total_premium,
            'dte_extension': buy_leg['dte'] - sell_leg['dte'],
            'time_gap_seconds': (buy_leg['timestamp'] - sell_leg['timestamp']) / 1e9,
            'kafka_event': True
        }
        
        # Post the alert
        await self._post_roll_alert(roll)
        
        logger.info(
            f"{self.name} ROLL ALERT: {symbol} "
            f"${sell_leg['strike']:.0f}→${buy_leg['strike']:.0f} "
            f"DTE {sell_leg['dte']}→{buy_leg['dte']} "
            f"premium=${total_premium:,.0f}"
        )
        
        return roll
    
    def _is_in_cooldown(self, key: str) -> bool:
        """Check if a roll pattern is in cooldown."""
        if key not in self._recent_rolls:
            return False
        
        last_time = self._recent_rolls[key]
        return (time.time() - last_time) < self.cooldown_seconds
    
    def _mark_cooldown_roll(self, key: str):
        """Mark a roll pattern as recently alerted."""
        self._recent_rolls[key] = time.time()
    
    async def scan_and_post(self):
        """
        Main scan loop - called by BaseAutoBot every scan_interval seconds.
        Scans watchlist for roll patterns in recent trades.
        """
        # Only scan during market hours
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        logger.info(f"{self.name} scanning {len(self.watchlist)} symbols for rolls...")
        
        # Clean up old cooldowns
        self._cleanup_cooldowns()
        
        rolls_found = 0
        
        # Scan symbols concurrently
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def scan_symbol(symbol: str) -> int:
            async with semaphore:
                try:
                    return await self._detect_rolls_for_symbol(symbol)
                except Exception as e:
                    logger.debug(f"{self.name} error scanning {symbol}: {e}")
                    return 0
        
        tasks = [scan_symbol(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, int):
                rolls_found += result
        
        if rolls_found > 0:
            logger.info(f"🔄 {self.name} found {rolls_found} roll(s) this scan")
    
    async def _detect_rolls_for_symbol(self, symbol: str) -> int:
        """
        Detect roll patterns for a single underlying symbol.
        
        Returns:
            Number of rolls detected and alerted
        """
        # Get options chain snapshot with limits to avoid heavy pagination
        from datetime import datetime, timedelta
        expiry_cutoff = (datetime.now() + timedelta(days=45)).strftime('%Y-%m-%d')
        contracts = await self.fetcher.get_option_chain_snapshot(
            symbol,
            max_contracts=getattr(Config, "ROLLING_MAX_CONTRACTS", 400),
            expiration_date_lte=expiry_cutoff,
        )
        if not contracts:
            return 0
        
        # Get current time window
        now_ns = time.time_ns()
        lookback_ns = self.lookback_seconds * 1_000_000_000
        start_ns = now_ns - lookback_ns
        
        # Collect all recent trades across contracts
        all_trades: List[TradeLeg] = []
        
        # Get spot price for determining trade side
        spot_price = await self._get_spot_price(symbol, contracts)
        
        for contract in contracts:
            details = contract.get('details', {}) or {}
            ticker = contract.get('ticker', '')
            
            if not ticker:
                continue
            
            strike = details.get('strike_price', 0)
            expiration = details.get('expiration_date', '')
            contract_type = details.get('contract_type', '').lower()
            
            if not strike or not expiration:
                continue
            
            # Calculate DTE
            try:
                exp_dt = datetime.fromisoformat(expiration)
                dte = (exp_dt - datetime.now()).days
            except:
                continue
            
            # Only process contracts in our DTE windows
            if not (dte <= self.near_term_dte or dte >= self.far_term_dte):
                continue
            
            # Get recent trades for this contract
            trades = await self.fetcher.get_option_trades(
                ticker,
                timestamp_gte=start_ns,
                limit=100
            )
            
            if not trades:
                continue
            
            # Get bid/ask for determining trade side
            last_quote = contract.get('last_quote', {}) or {}
            bid = last_quote.get('bid', 0)
            ask = last_quote.get('ask', 0)
            
            for trade in trades:
                price = trade.get('price', 0)
                size = trade.get('size', 0)
                ts = trade.get('sip_timestamp', 0)
                
                if not price or not size or not ts:
                    continue
                
                premium = price * size * 100
                
                # Filter by minimum premium
                if premium < self.min_roll_premium:
                    continue
                
                # Determine trade side (buy vs sell)
                side = self._determine_trade_side(price, bid, ask)
                
                trade_leg = TradeLeg(
                    symbol=symbol,
                    option_ticker=ticker,
                    strike=strike,
                    expiration=expiration,
                    contract_type=contract_type,
                    dte=dte,
                    price=price,
                    size=size,
                    premium=premium,
                    timestamp_ns=ts,
                    side=side
                )
                
                all_trades.append(trade_leg)
        
        if not all_trades:
            return 0
        
        # Sort by timestamp
        all_trades.sort(key=lambda t: t.timestamp_ns)
        
        # Find roll patterns
        return await self._find_roll_patterns(all_trades)
    
    def _determine_trade_side(self, price: float, bid: float, ask: float) -> str:
        """
        Determine if trade was a buy (at ask) or sell (at bid).
        
        Logic:
        - If price >= ask: Buy (buyer was aggressor)
        - If price <= bid: Sell (seller was aggressor)
        - If in between: Use midpoint heuristic
        """
        if not bid or not ask or ask <= bid:
            return 'unknown'
        
        midpoint = (bid + ask) / 2
        
        if price >= ask * 0.98:  # At or near ask
            return 'buy'
        elif price <= bid * 1.02:  # At or near bid
            return 'sell'
        elif price >= midpoint:
            return 'buy'
        else:
            return 'sell'
    
    async def _get_spot_price(self, symbol: str, contracts: List[Dict]) -> Optional[float]:
        """Get underlying spot price"""
        for contract in contracts:
            underlying = contract.get('underlying_asset', {}) or {}
            price = underlying.get('price')
            if price and price > 0:
                return float(price)
        
        try:
            price = await self.fetcher.get_current_price(symbol)
            return float(price) if price else None
        except:
            return None
    
    async def _find_roll_patterns(self, trades: List[TradeLeg]) -> int:
        """
        Find SELL (near-term) -> BUY (far-term) patterns.
        
        Returns:
            Number of rolls alerted
        """
        rolls_found = 0
        
        # Separate sells and buys
        near_term_sells = [t for t in trades if t.side == 'sell' and t.dte <= self.near_term_dte]
        far_term_buys = [t for t in trades if t.side == 'buy' and t.dte >= self.far_term_dte]
        
        if not near_term_sells or not far_term_buys:
            return 0
        
        # Match sells with subsequent buys
        for sell in near_term_sells:
            for buy in far_term_buys:
                # Must be same underlying and contract type
                if sell.symbol != buy.symbol or sell.contract_type != buy.contract_type:
                    continue
                
                # Buy must happen AFTER sell
                time_diff_seconds = (buy.timestamp_ns - sell.timestamp_ns) / 1e9
                
                if time_diff_seconds <= 0 or time_diff_seconds > self.max_gap_seconds:
                    continue
                
                # Check for notional alignment (reinvesting at least 50% of proceeds)
                if buy.premium < (sell.premium * 0.5):
                    continue
                
                # Check cooldown
                roll_key = f"{sell.symbol}_{sell.contract_type}_{sell.expiration}_{buy.expiration}"
                if self._cooldown_active(roll_key, cooldown_seconds=self.cooldown_seconds):
                    continue
                
                # ROLL FOUND!
                success = await self._fire_roll_alert(sell, buy, time_diff_seconds)
                if success:
                    self._mark_cooldown(roll_key)
                    rolls_found += 1
                
                # Only alert once per sell leg
                break
        
        return rolls_found
    
    async def _fire_roll_alert(self, sell_leg: TradeLeg, buy_leg: TradeLeg, time_gap: float) -> bool:
        """
        Format and send the Rolling Thunder alert to Discord.
        """
        # Determine conviction level
        net_flow = buy_leg.premium - sell_leg.premium
        if net_flow > 0:
            action = "DOUBLING DOWN ⏫"
            action_emoji = "🚀"
        else:
            action = "ROLLING OUT ➡️"
            action_emoji = "🔄"
        
        # Format premiums
        sell_premium_fmt = f"${sell_leg.premium/1000:.0f}K" if sell_leg.premium < 1_000_000 else f"${sell_leg.premium/1_000_000:.1f}M"
        buy_premium_fmt = f"${buy_leg.premium/1000:.0f}K" if buy_leg.premium < 1_000_000 else f"${buy_leg.premium/1_000_000:.1f}M"
        net_fmt = f"${abs(net_flow)/1000:.0f}K" if abs(net_flow) < 1_000_000 else f"${abs(net_flow)/1_000_000:.1f}M"
        
        type_emoji = "📈" if buy_leg.contract_type == 'call' else "📉"
        
        description = (
            f"**Strategy:** {action}\n\n"
            f"🔴 **CLOSED:** ${sell_leg.strike:.0f} {sell_leg.contract_type.upper()} "
            f"exp {sell_leg.expiration} ({sell_leg.dte}d)\n"
            f"💰 Premium: {sell_premium_fmt} ({sell_leg.size} contracts)\n\n"
            f"🟢 **OPENED:** ${buy_leg.strike:.0f} {buy_leg.contract_type.upper()} "
            f"exp {buy_leg.expiration} ({buy_leg.dte}d)\n"
            f"💰 Premium: {buy_premium_fmt} ({buy_leg.size} contracts)\n\n"
            f"⏱️ **Time Gap:** {time_gap:.1f}s\n"
            f"💵 **Net Flow:** {'+' if net_flow > 0 else '-'}{net_fmt}"
        )
        
        # Get GEX context if available
        gex_field = None
        if self.context_manager:
            try:
                context = self.context_manager.get_context(buy_leg.symbol)
                regime = context.get('regime', 'NEUTRAL')
                if regime != 'NEUTRAL':
                    gex_emoji = "🟢" if regime == "POSITIVE_GAMMA" else "🔴"
                    gex_field = {
                        "name": "GEX Regime",
                        "value": f"{gex_emoji} {regime.replace('_', ' ').title()}",
                        "inline": True
                    }
            except:
                pass
        
        fields = [
            {"name": "Symbol", "value": buy_leg.symbol, "inline": True},
            {"name": "Type", "value": f"{type_emoji} {buy_leg.contract_type.upper()}", "inline": True},
            {"name": "Conviction", "value": action, "inline": True},
        ]
        
        if gex_field:
            fields.append(gex_field)
        
        embed = self.create_signal_embed_with_disclaimer(
            title=f"🔄 ROLLING THUNDER: {buy_leg.symbol} {action_emoji}",
            description=description,
            color=0x9B59B6,  # Purple for royalty/rolls
            fields=fields,
            footer="Rolling Thunder Bot • Whale conviction detector"
        )
        
        success = await self.post_to_discord(embed)
        
        if success:
            logger.info(
                f"🔄 ROLL: {buy_leg.symbol} {buy_leg.contract_type.upper()} "
                f"closed {sell_leg.expiration} -> opened {buy_leg.expiration} "
                f"({sell_premium_fmt} -> {buy_premium_fmt})"
            )
        
        return success
    
    def _cleanup_cooldowns(self):
        """Remove expired entries from recent rolls cache"""
        now = time.time()
        expired = [k for k, v in self._recent_rolls.items() if now - v > self.cooldown_seconds]
        for k in expired:
            del self._recent_rolls[k]

