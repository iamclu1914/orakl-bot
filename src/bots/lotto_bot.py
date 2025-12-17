"""
Lotto Bot - Unusual OTM Flow Hunter

Scans for 'Lotto' flows - cheap, far OTM contracts with explosive volume.
These find the 100x baggers before the news drops.

The Logic:
- Price < $0.15 (Cheap lottery tickets)
- Volume > 50x OI (Explosive new interest)
- OTM > 10% (Far from money - speculative moonshot)

Why this matters:
Insiders don't care about Greeks or time decay. They care about leverage.
A $0.05 option going to $5.00 is a 100x return. These trades often
precede major news events, acquisitions, or earnings surprises.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.market_hours import MarketHours
from src.utils.option_contract_format import (
    format_option_contract_pretty,
    format_option_contract_sentence,
    normalize_option_ticker,
)

logger = logging.getLogger(__name__)


@dataclass
class LottoCandidate:
    """Represents a potential lotto play"""
    symbol: str
    option_ticker: str
    strike: float
    expiration: str
    contract_type: str
    price: float
    volume: int
    open_interest: int
    vol_oi_ratio: float
    otm_pct: float
    premium: float


class LottoBot(BaseAutoBot):
    """
    Scans for 'Lotto' flows:
    - Price < $0.15 (Cheap)
    - Vol > OI * 50 (Explosive Interest)
    - OTM > 10% (Moonshot)
    
    These are high-risk/high-reward speculative plays that often
    precede major news events.
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
            "Lotto Bot",
            scan_interval=Config.LOTTO_BOT_INTERVAL,
            hedge_hunter=hedge_hunter,
            context_manager=context_manager
        )
        
        self.watchlist = watchlist
        self.fetcher = fetcher
        
        # Lotto Bot specific settings
        self.max_price = getattr(Config, 'LOTTO_MAX_PRICE', 0.15)  # Max $0.15
        self.min_vol_oi_ratio = getattr(Config, 'LOTTO_MIN_VOL_OI_RATIO', 50.0)  # 50x
        self.min_otm_pct = getattr(Config, 'LOTTO_MIN_OTM_PCT', 0.10)  # 10% OTM
        self.min_volume = getattr(Config, 'LOTTO_MIN_VOLUME', 500)  # Min 500 contracts
        self.min_premium = getattr(Config, 'LOTTO_MIN_PREMIUM', 10000)  # Min $10K total
        self.cooldown_seconds = getattr(Config, 'LOTTO_COOLDOWN_SECONDS', 1800)  # 30 min
        self.max_alerts_per_scan = getattr(Config, 'LOTTO_MAX_ALERTS_PER_SCAN', 3)
        
        # Scan settings
        self.scan_batch_size = 0
        self.concurrency_limit = 20
        
        logger.info(
            f"Lotto Bot initialized: "
            f"max_price=${self.max_price}, "
            f"min_vol_oi={self.min_vol_oi_ratio}x, "
            f"min_otm={self.min_otm_pct*100:.0f}%"
        )
    
    # =========================================================================
    # ORAKL v2.0: Kafka Event Processing
    # =========================================================================
    
    async def process_event(self, enriched_trade: Dict) -> Optional[Dict]:
        """
        Process a single enriched trade event from Kafka for Lotto plays.
        
        Evaluates if the trade qualifies as a Lotto alert based on:
        - Price < $0.15 (cheap lottery ticket)
        - Vol/OI > 50x (explosive interest)
        - OTM > 10% (speculative moonshot)
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, Bid/Ask
            
        Returns:
            Alert payload dict if trade qualifies, None otherwise
        """
        try:
            symbol = enriched_trade.get('symbol', '')
            
            # Extract key fields
            contract_price = float(enriched_trade.get('trade_price', 0))
            strike = float(enriched_trade.get('strike_price') or enriched_trade.get('strike') or 0)
            underlying_price = float(enriched_trade.get('underlying_price') or enriched_trade.get('current_price') or 0)
            contract_type = str(enriched_trade.get('contract_type') or enriched_trade.get('type') or '').upper()
            open_interest = int(enriched_trade.get('open_interest', 0))
            day_volume = int(enriched_trade.get('day_volume', 0))
            trade_size = int(enriched_trade.get('trade_size', 0))
            premium = float(enriched_trade.get('premium', 0))
            
            # Use mid price if trade_price not available
            if contract_price <= 0:
                bid = float(enriched_trade.get('current_bid', 0))
                ask = float(enriched_trade.get('current_ask', 0))
                if bid > 0 and ask > 0:
                    contract_price = (bid + ask) / 2
                else:
                    self._count_filter("missing_contract_price")
                    return None
            
            # Validate required fields
            if not symbol:
                self._count_filter("missing_symbol")
                return None
            if strike <= 0:
                self._count_filter("missing_strike")
                return None
            if underlying_price <= 0:
                # Snapshot enrichment occasionally times out; try a fast cached spot fetch
                # for non-index symbols so we can still compute OTM/distance.
                try:
                    if isinstance(symbol, str) and not symbol.startswith("I:"):
                        underlying_price = await asyncio.wait_for(
                            self.fetcher.get_stock_price(symbol),
                            timeout=0.75,
                        ) or 0.0
                except Exception:
                    underlying_price = 0.0

                if underlying_price <= 0:
                    self._count_filter("missing_underlying_price")
                    return None
            if not contract_type:
                self._count_filter("missing_contract_type")
                return None
            
            # Check price threshold (must be cheap)
            if contract_price > self.max_price:
                self._count_filter("price_above_max")
                return None  # Too expensive for lotto play
            
            # Calculate OTM percentage
            if underlying_price > 0:
                if contract_type == 'CALL':
                    otm_pct = max(0, (strike - underlying_price) / underlying_price)
                else:
                    otm_pct = max(0, (underlying_price - strike) / underlying_price)
            else:
                return None
            
            # Check OTM threshold (must be far OTM)
            if otm_pct < self.min_otm_pct:
                self._count_filter("otm_below_min")
                return None  # Not far enough OTM
            
            # Calculate Vol/OI ratio
            effective_volume = trade_size if trade_size > 0 else day_volume
            if open_interest > 0:
                vol_oi_ratio = effective_volume / open_interest
            else:
                vol_oi_ratio = float(effective_volume)  # No OI = likely new contract
            
            # Check Vol/OI ratio (must be explosive)
            if vol_oi_ratio < self.min_vol_oi_ratio:
                self._count_filter("voi_below_min")
                return None  # Not enough explosive interest
            
            # Check minimum volume
            if effective_volume < self.min_volume:
                self._count_filter("volume_below_min")
                return None
            
            # Check minimum premium
            if premium < self.min_premium:
                self._count_filter("premium_below_min")
                return None
            
            # Check cooldown
            cooldown_key = f"{symbol}_{contract_type}_{strike}"
            if self._cooldown_active(cooldown_key, self.cooldown_seconds):
                self._count_filter("cooldown_active")
                return None
            
            # Build candidate
            candidate = LottoCandidate(
                symbol=symbol,
                option_ticker=enriched_trade.get('contract_ticker', ''),
                strike=strike,
                expiration=enriched_trade.get('expiration_date', ''),
                contract_type=contract_type,
                price=contract_price,
                volume=effective_volume,
                open_interest=open_interest,
                vol_oi_ratio=vol_oi_ratio,
                otm_pct=otm_pct,
                premium=premium
            )
            
            # Mark cooldown
            self._mark_cooldown(cooldown_key)
            
            # Post the signal
            await self._post_lotto_alert(candidate, underlying_price)
            
            logger.info(
                f"{self.name} ALERT: {symbol} {contract_type} "
                f"${contract_price:.2f} vol/OI={vol_oi_ratio:.0f}x OTM={otm_pct*100:.0f}%"
            )
            
            return {
                'symbol': symbol,
                'type': contract_type,
                'strike': strike,
                'price': contract_price,
                'vol_oi_ratio': vol_oi_ratio,
                'otm_pct': otm_pct,
                'premium': premium,
                'kafka_event': True
            }
            
        except Exception as e:
            logger.error(f"{self.name} error processing event: {e}")
            return None
    
    async def _post_lotto_alert(self, candidate: LottoCandidate, underlying_price: float) -> None:
        """Send a Lotto alert to Discord (restores missing method to stop crashes)."""
        # Format contract and fields
        contract_line = format_option_contract_sentence(
            strike=candidate.strike,
            contract_type=candidate.contract_type,
            expiration_date=candidate.expiration,
            dte=None,
        )
        
        fields = [
            {"name": "Contract", "value": contract_line, "inline": False},
            {"name": "Price", "value": f"${candidate.price:.2f}", "inline": True},
            {"name": "Premium", "value": f"${candidate.premium:,.0f}", "inline": True},
            {"name": "Volume", "value": f"{candidate.volume:,}", "inline": True},
            {"name": "Open Interest", "value": f"{candidate.open_interest:,}", "inline": True},
            {"name": "Vol/OI", "value": f"{candidate.vol_oi_ratio:.1f}x", "inline": True},
            {"name": "OTM %", "value": f"{candidate.otm_pct*100:.1f}%", "inline": True},
            {"name": "Spot", "value": f"${underlying_price:.2f}", "inline": True},
        ]
        
        footer = f"ORAKL Bot - Lotto • {datetime.utcnow().strftime('%-m/%-d/%Y %-I:%M %p')} UTC"
        embed = self.create_signal_embed_with_disclaimer(
            title=f"{candidate.symbol} - Lotto Flow",
            description=contract_line,
            color=0x7B68EE,  # soft purple
            fields=fields,
            footer=footer,
        )
        await self.post_to_discord(embed)
    
    async def scan_and_post(self):
        """
        Main scan loop - finds lotto plays across watchlist.
        """
        if not MarketHours.is_market_open(include_extended=False):
            logger.debug(f"{self.name} - Market closed, skipping scan")
            return
        
        logger.info(f"{self.name} scanning {len(self.watchlist)} symbols for lottos...")
        
        all_lottos: List[LottoCandidate] = []
        
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def scan_symbol(symbol: str) -> List[LottoCandidate]:
            async with semaphore:
                try:
                    return await self._find_lottos_for_symbol(symbol)
                except Exception as e:
                    logger.debug(f"{self.name} error scanning {symbol}: {e}")
                    return []
        
        tasks = [scan_symbol(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_lottos.extend(result)
        
        if not all_lottos:
            return
        
        # Sort by vol/OI ratio (most unusual first)
        all_lottos.sort(key=lambda x: x.vol_oi_ratio, reverse=True)
        
        # Alert top candidates
        alerts_sent = 0
        for lotto in all_lottos[:self.max_alerts_per_scan]:
            success = await self._fire_lotto_alert(lotto)
            if success:
                alerts_sent += 1
        
        if alerts_sent > 0:
            logger.info(f"🎰 {self.name} sent {alerts_sent} lotto alert(s)")
    
    async def _find_lottos_for_symbol(self, symbol: str) -> List[LottoCandidate]:
        """
        Find lotto candidates for a single symbol.
        
        Returns:
            List of LottoCandidate objects
        """
        # IMPORTANT: Use get_option_chain_snapshot (1 API call) NOT get_options_snapshot (52+ calls)
        # Limit contracts and expiry to keep scan fast
        from datetime import datetime, timedelta
        expiry_cutoff = (datetime.now() + timedelta(days=45)).strftime('%Y-%m-%d')
        contracts = await self.fetcher.get_option_chain_snapshot(
            symbol,
            max_contracts=getattr(Config, "LOTTO_MAX_CONTRACTS", 400),
            expiration_date_lte=expiry_cutoff,
        )
        if not contracts:
            return []
        
        # Get underlying price
        underlying_price = await self._get_underlying_price(symbol, contracts)
        if not underlying_price:
            return []
        
        lottos = []
        
        for contract in contracts:
            details = contract.get('details', {}) or {}
            day_data = contract.get('day', {}) or {}
            last_quote = contract.get('last_quote', {}) or {}
            
            ticker = contract.get('ticker', '')
            strike = details.get('strike_price', 0)
            expiration = details.get('expiration_date', '')
            contract_type = details.get('contract_type', '').lower()
            
            if not strike or not expiration or not ticker:
                continue
            
            # Get price (prefer ask for cheap contracts)
            ask = last_quote.get('ask', 0)
            bid = last_quote.get('bid', 0)
            price = ask if ask and ask > 0 else (bid if bid else 0)
            
            if not price or price <= 0:
                continue
            
            # Filter 1: Cheap contracts only
            if price > self.max_price:
                continue
            
            # Get volume and OI
            volume = day_data.get('volume', 0)
            oi = contract.get('open_interest', 0) or 1  # Avoid division by zero
            
            # Filter 2: Volume explosion
            if volume < self.min_volume:
                continue
            
            vol_oi_ratio = volume / max(oi, 1)
            if vol_oi_ratio < self.min_vol_oi_ratio:
                continue
            
            # Filter 3: OTM (moonshot territory)
            if contract_type == 'call':
                otm_pct = (strike - underlying_price) / underlying_price
            else:
                otm_pct = (underlying_price - strike) / underlying_price
            
            if otm_pct < self.min_otm_pct:
                continue  # Too close to money
            
            # Filter 4: Minimum premium
            premium = price * volume * 100
            if premium < self.min_premium:
                continue
            
            # FOUND A LOTTO!
            lottos.append(LottoCandidate(
                symbol=symbol,
                option_ticker=ticker,
                strike=strike,
                expiration=expiration,
                contract_type=contract_type,
                price=price,
                volume=volume,
                open_interest=oi,
                vol_oi_ratio=vol_oi_ratio,
                otm_pct=otm_pct,
                premium=premium
            ))
        
        return lottos
    
    async def _get_underlying_price(self, symbol: str, contracts: List[Dict]) -> Optional[float]:
        """Get underlying price"""
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
    
    async def _fire_lotto_alert(self, lotto: LottoCandidate) -> bool:
        """
        Send lotto alert to Discord.
        """
        # Check cooldown
        cooldown_key = f"{lotto.symbol}_{lotto.strike}_{lotto.contract_type}_{lotto.expiration}"
        if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
            return False
        
        # Format values
        premium_fmt = f"${lotto.premium/1000:.0f}K" if lotto.premium < 1_000_000 else f"${lotto.premium/1_000_000:.1f}M"
        type_emoji = "📈" if lotto.contract_type == 'call' else "📉"
        
        # Calculate DTE
        try:
            exp_dt = datetime.fromisoformat(lotto.expiration)
            dte = (exp_dt - datetime.now()).days
        except:
            dte = 0
        
        # Conviction indicator based on vol/OI
        if lotto.vol_oi_ratio >= 200:
            conviction = "🔥🔥🔥 EXTREME"
        elif lotto.vol_oi_ratio >= 100:
            conviction = "🔥🔥 VERY HIGH"
        else:
            conviction = "🔥 HIGH"
        
        contract_pretty = format_option_contract_pretty(
            lotto.symbol,
            lotto.expiration,
            lotto.strike,
            lotto.contract_type,
        )
        contract_id = normalize_option_ticker(getattr(lotto, "option_ticker", "") or "")

        description = (
            f"**Contract:** {contract_pretty} ({dte}d)\n"
            f"**Contract ID:** `{contract_id}`\n"
            f"**Price:** ${lotto.price:.2f}\n"
            f"**Volume:** {lotto.volume:,}\n"
            f"**Open Interest:** {lotto.open_interest:,}\n"
            f"**Vol/OI Ratio:** {lotto.vol_oi_ratio:.1f}x {conviction}\n"
            f"**OTM:** {lotto.otm_pct*100:.1f}%\n"
            f"**Total Premium:** {premium_fmt}\n\n"
            f"*⚠️ SPECULATIVE: Cheap contract with massive new interest.*\n"
            f"*Could indicate insider knowledge or event speculation.*"
        )
        
        fields = [
            {"name": "Symbol", "value": lotto.symbol, "inline": True},
            {"name": "Type", "value": f"{type_emoji} {lotto.contract_type.upper()}", "inline": True},
            {"name": "Unusual Activity", "value": f"{lotto.vol_oi_ratio:.0f}x Normal", "inline": True},
        ]
        
        embed = self.create_signal_embed_with_disclaimer(
            title=f"🎰 LOTTO FLOW: {lotto.symbol} {int(lotto.otm_pct*100)}% OTM",
            description=description,
            color=0xF1C40F,  # Gold
            fields=fields,
            footer="Lotto Bot • High-risk speculation detector"
        )
        
        success = await self.post_to_discord(embed)
        
        if success:
            self._mark_cooldown(cooldown_key)
            logger.info(
                f"🎰 LOTTO: {lotto.symbol} ${lotto.strike} {lotto.contract_type.upper()} "
                f"@ ${lotto.price:.2f} (Vol/OI: {lotto.vol_oi_ratio:.0f}x, "
                f"OTM: {lotto.otm_pct*100:.0f}%)"
            )
        
        return success

