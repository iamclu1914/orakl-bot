"""Bullseye Bot - Massive institutional block scanner."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.flow_metrics import OptionTradeMetrics, build_metrics_from_flow
from src.utils.market_hours import MarketHours
from src.utils.enhanced_analysis import EnhancedAnalyzer

logger = logging.getLogger(__name__)


class BullseyeBot(BaseAutoBot):
    """
    Bullseye Bot surfaces massive institutional block trades (1–5 DTE).

    Contract price may exceed $1.00 – filters focus on conviction:
    - $1M+ premium blocks
    - 400+ contract prints (single leg, ask-side)
    - Fresh positioning (Vol/OI ≥ 1.0)
    """

    def __init__(self, webhook_url: str, watchlist: List[str], fetcher: DataFetcher):
        super().__init__(webhook_url, "Bullseye Bot", scan_interval=Config.BULLSEYE_INTERVAL)
        self.watchlist = watchlist
        self.fetcher = fetcher
        
        # Enhanced analysis
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)
        
        # Thresholds tuned for hidden institutional blocks
        self.min_premium = Config.BULLSEYE_MIN_PREMIUM
        self.min_volume = Config.BULLSEYE_MIN_VOLUME
        self.min_volume_delta = Config.BULLSEYE_MIN_VOLUME_DELTA
        self.min_block_contracts = Config.BULLSEYE_MIN_BLOCK_CONTRACTS
        self.min_voi_ratio = Config.BULLSEYE_MIN_VOI_RATIO
        self.min_price = Config.BULLSEYE_MIN_PRICE
        self.min_dte = Config.BULLSEYE_MIN_DTE
        self.max_dte = Config.BULLSEYE_MAX_DTE
        self.max_percent_otm = Config.BULLSEYE_MAX_STRIKE_DISTANCE
        self.max_spread_pct = Config.BULLSEYE_MAX_SPREAD_PCT
        self.cooldown_seconds = Config.BULLSEYE_COOLDOWN_SECONDS
        self.max_alerts_per_scan = Config.BULLSEYE_MAX_ALERTS_PER_SCAN
        self.required_intensity = {"STRONG", "AGGRESSIVE"}

    async def scan_and_post(self):
        logger.info("%s scanning for institutional block flow", self.name)

        if not MarketHours.is_market_open(include_extended=False):
            logger.debug("%s skipping scan: market closed", self.name)
            return
        
        semaphore = asyncio.Semaphore(max(1, Config.MAX_CONCURRENT_REQUESTS))

        async def run_symbol(symbol: str):
            async with semaphore:
                return await self._scan_symbol(symbol)
        
        tasks = [run_symbol(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("%s error during scan: %s", self.name, result)
                continue
            signals.extend(result)

        if not signals:
            logger.debug("%s found no qualifying block trades", self.name)
            return

        signals.sort(key=lambda s: (s["score"], s["metrics"].premium), reverse=True)

        posted_symbols = set()
        alerts_posted = 0
        
        for signal in signals:
            symbol = signal["metrics"].underlying
            if symbol in posted_symbols:
                continue

            success = await self._post_signal(signal)
            if success:
                posted_symbols.add(symbol)
                alerts_posted += 1
                if alerts_posted >= self.max_alerts_per_scan:
                    break

    async def _scan_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []

        try:
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.min_premium,
                min_volume_delta=self.min_volume_delta,
                min_volume_ratio=0.0,
            )
        except Exception as exc:
            logger.error("%s failed to load flow for %s: %s", self.name, symbol, exc)
                return signals

            for flow in flows:
            metrics = build_metrics_from_flow(flow)
            if not metrics:
                continue

            if not metrics.is_single_leg:
                self._log_skip(symbol, "multi-leg structure (spread)")
                    continue

            if not metrics.is_ask_side:
                self._log_skip(symbol, "not ask-side (no aggressive buyer)")
                    continue

            contract_price = metrics.price or 0.0
            if contract_price <= 0:
                self._log_skip(symbol, "missing contract price")
                continue

            if contract_price < self.min_price:
                self._log_skip(symbol, f"price ${contract_price:.2f} < ${self.min_price:.2f}")
                    continue

            dte = metrics.dte
            if dte < self.min_dte or dte > self.max_dte:
                self._log_skip(symbol, f"DTE {dte:.2f} outside {self.min_dte}-{self.max_dte}")
                    continue

            percent_otm = abs(metrics.percent_otm)
            if percent_otm > self.max_percent_otm:
                self._log_skip(symbol, f"%OTM {percent_otm*100:.2f}% > {self.max_percent_otm*100:.2f}%")
                    continue

            volume_delta = int(flow.get("volume_delta") or 0)
            total_volume = int(flow.get("total_volume") or 0)

            if volume_delta < self.min_block_contracts:
                self._log_skip(symbol, f"block size {volume_delta} < {self.min_block_contracts}")
                        continue

            if total_volume < self.min_volume:
                self._log_skip(symbol, f"day volume {total_volume} < {self.min_volume}")
                    continue

            premium = float(metrics.premium or 0.0)
            if premium < self.min_premium:
                self._log_skip(symbol, f"premium ${premium:,.0f} < ${self.min_premium:,.0f}")
                    continue

            voi_ratio = flow.get("vol_oi_ratio") or metrics.volume_over_oi or 0.0
            if voi_ratio < self.min_voi_ratio:
                self._log_skip(symbol, f"VOI {voi_ratio:.2f}x < {self.min_voi_ratio:.2f}x")
                    continue

            flow_intensity = (flow.get("flow_intensity") or "NORMAL").upper()
            if self.required_intensity and flow_intensity not in self.required_intensity:
                self._log_skip(symbol, f"intensity {flow_intensity} below STRONG")
                    continue

            bid = float(flow.get("bid") or 0.0)
            ask = float(flow.get("ask") or 0.0)
            spread_pct = self._calculate_spread_pct(bid, ask)
            if spread_pct is not None and spread_pct > self.max_spread_pct:
                self._log_skip(symbol, f"spread {spread_pct:.2f}% > {self.max_spread_pct:.2f}%")
                    continue

            if int(flow.get("open_interest") or 0) < Config.BULLSEYE_MIN_OPEN_INTEREST:
                self._log_skip(symbol, f"OI {flow.get('open_interest', 0)} < {Config.BULLSEYE_MIN_OPEN_INTEREST}")
                    continue
                
            # 10-minute Candle Verification
            # Ensure the option contract itself traded > $100k in the last 10 minutes
            # and shows aggressive buying pressure (green candle)
            try:
                bars_10m = await self.fetcher.get_aggregates(
                    flow['ticker'],
                    timespan='minute',
                    multiplier=10,
                    limit=1
                )
                
                if not bars_10m.empty:
                    last_bar = bars_10m.iloc[-1]
                    # Calculate total premium for this 10m candle
                    candle_premium = last_bar['volume'] * last_bar['close'] * 100
                    
                    if candle_premium < 100_000:
                        self._log_skip(symbol, f"10m option candle premium ${candle_premium:,.0f} < $100k")
                        continue

                # Stock Candle Logic (Proxy for "rising red candle" description)
                # We need to verify the UNDERLYING direction matches the trade
                # Calls -> Stock Green Candle
                # Puts -> Stock Red Candle ("rising red candle" = rising put value on red stock candle)
                bars_stock = await self.fetcher.get_aggregates(
                    symbol,
                    timespan='minute',
                    multiplier=10,
                    limit=1
                )
                if not bars_stock.empty:
                    stock_bar = bars_stock.iloc[-1]
                    is_green = stock_bar['close'] > stock_bar['open']
                    is_red = stock_bar['close'] < stock_bar['open']
                    
                    if metrics.option_type == 'CALL' and not is_green:
                         self._log_skip(symbol, "10m stock candle is not green (Call needs green)")
                         continue
                    if metrics.option_type == 'PUT' and not is_red:
                         self._log_skip(symbol, "10m stock candle is not red (Put needs red)")
                         continue
            except Exception as e:
                logger.debug(f"{self.name} failed to verify 10m candle for {flow['ticker']}: {e}")

            # Trend Alignment Check
            try:
                alignment = await self.enhanced_analyzer.check_price_action_alignment(symbol, metrics.option_type)
                if alignment:
                    # Momentum Check:
                    # If CALL, want positive momentum. If PUT, want negative.
                    # momentum_5m and momentum_15m are percentages (e.g., 0.5 for 0.5%)
                    
                    m5 = alignment.get('momentum_5m', 0)
                    m15 = alignment.get('momentum_15m', 0)
                    
                    if metrics.option_type == 'CALL':
                        if m5 < 0 and m15 < 0:
                            self._log_skip(symbol, f"fighting trend (5m: {m5:.2f}%, 15m: {m15:.2f}%)")
                            continue
                    elif metrics.option_type == 'PUT':
                        if m5 > 0 and m15 > 0:
                            self._log_skip(symbol, f"fighting trend (5m: {m5:.2f}%, 15m: {m15:.2f}%)")
                            continue
        except Exception as e:
                logger.debug(f"{self.name} trend check failed for {symbol}: {e}")

            cooldown_key = self._build_cooldown_key(metrics)
            if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
                self._log_skip(symbol, f"cooldown active ({cooldown_key})")
                continue

            score = self._calculate_block_score(
                metrics=metrics,
                voi_ratio=voi_ratio,
                block_size=volume_delta,
                intensity=flow_intensity,
                spread_pct=spread_pct,
            )

            signals.append(
                {
                    "metrics": metrics,
                    "flow": flow,
                    "contract_price": contract_price,
                    "score": score,
                    "cooldown_key": cooldown_key,
                    "spread_pct": spread_pct,
                }
            )

        return signals[:5]

    def _calculate_block_score(
        self,
        metrics: OptionTradeMetrics,
        voi_ratio: float,
        block_size: int,
        intensity: str,
        spread_pct: Optional[float],
    ) -> int:
        score = 0

        if metrics.premium >= 5_000_000:
            score += 40
        elif metrics.premium >= 3_000_000:
            score += 35
        elif metrics.premium >= 1_500_000:
            score += 32
        else:
            score += 28

        block_ratio = block_size / max(self.min_block_contracts, 1)
        if block_ratio >= 3.0:
            score += 20
        elif block_ratio >= 2.0:
            score += 15
        elif block_ratio >= 1.25:
            score += 10
        else:
            score += 5

        if voi_ratio >= 3.0:
            score += 15
        elif voi_ratio >= 2.0:
            score += 12
        elif voi_ratio >= 1.5:
            score += 8
            else:
            score += 5

        score += {
            "AGGRESSIVE": 18,
            "STRONG": 14,
            "MODERATE": 6,
        }.get(intensity, 0)

        if metrics.dte <= 2.0:
            score += 12
        elif metrics.dte <= 3.0:
            score += 9
        else:
            score += 6

        if spread_pct is not None:
            if spread_pct <= 2.0:
                score += 10
            elif spread_pct <= 4.0:
                score += 7
            elif spread_pct <= 6.0:
                score += 4

        return min(score, 100)

    async def _post_signal(self, payload: Dict[str, Any]) -> bool:
        metrics: OptionTradeMetrics = payload["metrics"]
        flow: Dict[str, Any] = payload["flow"]
        contract_price: float = payload["contract_price"]
        score: int = payload["score"]

        embed = self._build_embed(metrics, contract_price, flow, score, payload.get("spread_pct"))
        success = await self.post_to_discord(embed)

        if success:
            cooldown_key = payload["cooldown_key"]
            self._mark_cooldown(cooldown_key)
            logger.info(
                "%s alert: %s %s %s premium $%s score %d",
                self.name,
                metrics.underlying,
                metrics.strike,
                metrics.option_type,
                f"{metrics.premium:,.0f}",
                score,
            )

        return success

    def _build_embed(
        self,
        metrics: OptionTradeMetrics,
        contract_price: float,
        flow: Dict[str, Any],
        score: int,
        spread_pct: Optional[float],
    ) -> Dict[str, Any]:
        dte_days = int(round(metrics.dte))
        expiration_fmt = (
            metrics.expiration.strftime("%m/%d/%Y")
            if isinstance(metrics.expiration, datetime)
            else str(metrics.expiration)
        )
        option_type_short = "C" if metrics.option_type.upper() == "CALL" else "P"

        volume_delta = int(flow.get("volume_delta") or 0)
        total_volume = int(flow.get("total_volume") or 0)
        oi_value = int(flow.get("open_interest") or 0)
        voi_ratio = flow.get("vol_oi_ratio") or metrics.volume_over_oi or 0.0
        bid_price = float(flow.get("bid") or 0.0)
        ask_price = float(flow.get("ask") or 0.0)
        flow_intensity = (flow.get("flow_intensity") or "NORMAL").upper()

        premium_fmt = (
            f"${metrics.premium / 1_000_000:.1f}M"
            if metrics.premium >= 1_000_000
            else f"${metrics.premium / 1_000:.0f}K"
        )

        target_30 = contract_price * 1.30
        target_50 = contract_price * 1.50
        target_80 = contract_price * 1.80

        spread_text = (
            f"${bid_price:.2f} / ${ask_price:.2f}"
            if bid_price > 0 and ask_price > 0
            else "n/a"
        )
        spread_label = f"{spread_pct:.2f}%" if spread_pct is not None else "n/a"

        last_trade = flow.get("last_trade_timestamp")
        if isinstance(last_trade, datetime):
            reference = datetime.now(last_trade.tzinfo or timezone.utc)
            minutes_ago = max((reference - last_trade).total_seconds() / 60, 0.0)
            recency_text = f"{minutes_ago:.0f} min ago"
        else:
            recency_text = "recent"

        description = (
            "**Institutional Block Print**\n\n"
            f"Fill: **${contract_price:.2f}** @ ask ({option_type_short})\n"
            f"Block Size: **{volume_delta:,} contracts**\n"
            f"Premium: **{premium_fmt}**\n"
            f"Intensity: **{flow_intensity}** ({recency_text})\n\n"
            "**Market Context**\n\n"
            f"DTE: **{dte_days}** | % OTM: **{metrics.percent_otm * 100:.2f}%**\n"
            f"Vol/OI: **{voi_ratio:.2f}x** | Day Vol: **{total_volume:,}** | OI: **{oi_value:,}**\n"
            f"Spread: **{spread_text}** ({spread_label})\n\n"
            "**Targets**\n"
            f"30%: **${target_30:.2f}**\n"
            f"50%: **${target_50:.2f}**\n"
            f"80%: **${target_80:.2f}**"
        )

        narrative = (
            f"{metrics.underlying} drew a {flow_intensity.lower()} block with only {dte_days}D to expiry. "
            f"Institution put ${metrics.premium:,.0f} to work expecting a move soon."
        )

        fields = [
            {
                "name": "Block Score",
                "value": f"**{score} / 100** conviction score",
                "inline": True,
            },
            {
                "name": "Why it matters",
                "value": narrative,
                "inline": False,
            },
        ]

        title = (
            f"{metrics.underlying} {metrics.strike} {option_type_short} "
            f"{expiration_fmt} ({dte_days}D) • Bullseye Block"
        )

        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=0x1F8B4C,
            fields=fields,
            footer="Bullseye Bot • Massive institutional conviction",
        )
        return embed

    @staticmethod
    def _calculate_spread_pct(bid: float, ask: float) -> Optional[float]:
        if bid <= 0 or ask <= 0:
            return None
        midpoint = (bid + ask) / 2
        if midpoint <= 0:
            return None
        return ((ask - bid) / midpoint) * 100

    @staticmethod
    def _build_cooldown_key(metrics: OptionTradeMetrics) -> str:
        expiry_part = metrics.expiration.strftime("%Y%m%d") if isinstance(metrics.expiration, datetime) else str(metrics.expiration)
        return f"{metrics.underlying}_{metrics.option_type}_{metrics.strike}_{expiry_part}"

    async def stop(self):
        await super().stop()

