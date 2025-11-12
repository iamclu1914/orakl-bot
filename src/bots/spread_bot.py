"""
99 Cent Store Bot - finds contracts under $1.00 with real whale flow and speculative heat.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.flow_metrics import build_metrics_from_flow, OptionTradeMetrics


logger = logging.getLogger(__name__)


class SpreadBot(BaseAutoBot):
    """
    Detects contracts priced under $1.00 with large premium (whale flow) and high VOI ratio (speculative heat).
    """

    def __init__(self, webhook_url: str, watchlist: Optional[List[str]], fetcher: DataFetcher):
        super().__init__(webhook_url, "99 Cent Store", scan_interval=Config.SPREAD_INTERVAL)
        self.fetcher = fetcher

        base_watchlist: Set[str] = set(Config.SWEEPS_WATCHLIST)
        base_watchlist.update(Config.SPREAD_WATCHLIST)
        base_watchlist.update(Config.SPREAD_EXTRA_TICKERS)
        if watchlist:
            base_watchlist.update(watchlist)

        # Remove empty strings and sort for deterministic ordering
        self.watchlist = sorted(ticker for ticker in base_watchlist if ticker)

        # Thresholds
        self.min_premium = Config.SPREAD_MIN_PREMIUM
        self.min_volume = Config.SPREAD_MIN_VOLUME
        self.min_volume_delta = Config.SPREAD_MIN_VOLUME_DELTA
        self.max_price = Config.SPREAD_MAX_PRICE  # Contract price must be < $1.00
        self.min_price = Config.SPREAD_MIN_PRICE  # Avoid illiquid penny options
        self.min_voi_ratio = Config.SPREAD_MIN_VOI_RATIO  # Min VOI for speculative heat
        self.min_dte = Config.SPREAD_MIN_DTE
        self.max_dte = Config.SPREAD_MAX_DTE
        self.max_percent_otm = Config.SPREAD_MAX_PERCENT_OTM

    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        signals: List[Dict] = []

        try:
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.min_premium,
                min_volume_delta=self.min_volume_delta,
                min_volume_ratio=0.0,
            )

            for flow in flows:
                metrics = build_metrics_from_flow(flow)
                if not metrics:
                    continue

                # CRITICAL: Single-leg filter (prevents multi-leg spreads)
                if not metrics.is_single_leg:
                    self._log_skip(symbol, "multi-leg spread detected")
                    continue

                # Filter: Contract price must be under $1.00 but above minimum
                contract_price = metrics.price
                if contract_price is None or contract_price <= 0:
                    self._log_skip(symbol, "missing contract price")
                    continue

                if contract_price < self.min_price:
                    self._log_skip(symbol, f"price ${contract_price:.2f} < ${self.min_price:.2f} (illiquid)")
                    continue

                if contract_price > self.max_price:
                    self._log_skip(symbol, f"price ${contract_price:.2f} > ${self.max_price:.2f}")
                    continue

                # Filter: Premium must meet whale threshold
                if metrics.premium < self.min_premium:
                    self._log_skip(symbol, f"premium ${metrics.premium:,.0f} < ${self.min_premium:,.0f}")
                    continue

                # Filter: Must be OTM (directional speculation, not stock substitute)
                if not metrics.is_otm:
                    self._log_skip(symbol, "not OTM (ITM = stock substitute)")
                    continue

                if metrics.percent_otm > self.max_percent_otm:
                    self._log_skip(symbol, f"OTM {metrics.percent_otm*100:.2f}% > {self.max_percent_otm*100:.2f}%")
                    continue

                # Filter: Ask-side for directional conviction
                if not metrics.is_ask_side:
                    self._log_skip(symbol, "not ask-side (no directional conviction)")
                    continue

                # Filter: DTE bounds (1-7 days for speculative plays)
                if metrics.dte < self.min_dte:
                    self._log_skip(symbol, f"DTE {metrics.dte:.2f} < {self.min_dte:.2f}")
                    continue

                if metrics.dte > self.max_dte:
                    self._log_skip(symbol, f"DTE {metrics.dte:.2f} > {self.max_dte:.2f} (too far out)")
                    continue

                # Filter: Volume must meet threshold
                total_volume = flow.get("total_volume", 0)
                if total_volume < self.min_volume:
                    self._log_skip(symbol, f"volume {total_volume} < {self.min_volume}")
                    continue

                volume_delta = flow.get("volume_delta", 0)
                if volume_delta < self.min_volume_delta:
                    self._log_skip(symbol, f"volume delta {volume_delta} < {self.min_volume_delta}")
                    continue

                # Filter: VOI ratio for speculative heat
                voi_ratio = flow.get("vol_oi_ratio", 0.0) or metrics.volume_over_oi or 0.0
                if voi_ratio < self.min_voi_ratio:
                    self._log_skip(symbol, f"VOI ratio {voi_ratio:.2f}x < {self.min_voi_ratio:.2f}x")
                    continue

                signals.append(
                    {
                        "metrics": metrics,
                        "contract_price": contract_price,
                        "flow": flow,
                    }
                )

        except Exception as exc:
            logger.error(f"{self.name} error scanning {symbol}: {exc}")
            return []

        # Return top 3 signals by premium
        return sorted(signals, key=lambda s: s["metrics"].premium, reverse=True)[:3]

    def _calculate_spread_score(self, metrics: OptionTradeMetrics, voi_ratio: float, contract_price: float) -> int:
        """
        Calculate quality score for 99 Cent Store signals (0-100).
        
        Scoring factors:
        - Premium tier (whale size)
        - VOI ratio (speculative heat)
        - Contract price (cheaper = higher leverage)
        - DTE (shorter = more urgent)
        """
        score = 0
        
        # Premium tiers (max 35 points)
        if metrics.premium >= 500_000:
            score += 35
        elif metrics.premium >= 250_000:
            score += 28
        elif metrics.premium >= 150_000:
            score += 22
        elif metrics.premium >= 100_000:
            score += 15
        
        # VOI urgency (max 30 points)
        if voi_ratio >= 10.0:
            score += 30
        elif voi_ratio >= 5.0:
            score += 25
        elif voi_ratio >= 3.0:
            score += 20
        elif voi_ratio >= 2.0:
            score += 15
        elif voi_ratio >= 1.5:
            score += 10
        
        # Contract price (cheaper = higher leverage, max 20 points)
        if contract_price <= 0.25:
            score += 20
        elif contract_price <= 0.50:
            score += 15
        elif contract_price <= 0.75:
            score += 10
        elif contract_price < 1.0:
            score += 5
        
        # DTE urgency (max 15 points)
        if metrics.dte <= 2.0:
            score += 15
        elif metrics.dte <= 3.0:
            score += 12
        elif metrics.dte <= 5.0:
            score += 8
        elif metrics.dte <= 7.0:
            score += 5
        
        return min(score, 100)

    async def _post_signal(self, payload: Dict) -> bool:
        metrics: OptionTradeMetrics = payload["metrics"]
        contract_price: float = payload["contract_price"]
        flow: Dict = payload["flow"]

        # Deduplication: Prevent same contract from alerting multiple times in 15 minutes
        cooldown_key = f"{metrics.underlying}_{metrics.strike}_{metrics.option_type}_{metrics.expiration.strftime('%Y%m%d')}"
        
        if self._cooldown_active(cooldown_key, cooldown_seconds=900):  # 15 minute cooldown
            logger.debug(f"99 Cent Store skipping duplicate signal: {cooldown_key}")
            return False

        embed = self._build_embed(metrics, contract_price, flow)
        success = await self.post_to_discord(embed)
        
        if success:
            self._mark_cooldown(cooldown_key)
            logger.info(
                "99 Cent Store Alert: %s %.2f %s price $%.2f premium $%s",
                metrics.underlying,
                metrics.strike,
                metrics.option_type,
                contract_price,
                f"{metrics.premium:,.0f}",
            )
        
        return success

    def _build_embed(
        self,
        metrics: OptionTradeMetrics,
        contract_price: float,
        flow: Dict,
    ) -> Dict:
        """Build improved Discord embed with DTE, %OTM, side indicator, and quality score."""
        dte_days = int(round(metrics.dte))
        expiration_fmt = metrics.expiration.strftime("%m/%d/%Y") if isinstance(metrics.expiration, datetime) else str(metrics.expiration)

        # Calculate quality score
        voi_ratio = flow.get("vol_oi_ratio", 0.0) or metrics.volume_over_oi or 0.0
        spread_score = self._calculate_spread_score(metrics, voi_ratio, contract_price)

        # Add contract ticker to title for easy copy-paste
        title = f"🟣 {metrics.ticker} • 99 Cent Store"
        description = (
            f"**{metrics.option_type.title()} ${metrics.strike:.2f}** expiring {expiration_fmt} "
            f"({max(dte_days, 0)}D) • Score: **{spread_score}/100**"
        )

        premium_fmt = f"${metrics.premium/1_000_000:.1f}M" if metrics.premium >= 1_000_000 else f"${metrics.premium/1_000:.0f}K"
        volume_delta = flow.get("volume_delta", 0)
        total_volume = flow.get("total_volume", 0)

        oi_value = flow.get("open_interest", 0)
        underlying_price = flow.get("underlying_price")
        ask_price = flow.get("ask")
        bid_price = flow.get("bid")

        # Determine side indicator
        side_indicator = "ASK" if metrics.is_ask_side else "BID/MID"

        fields = [
            {
                "name": "💰 Whale Flow",
                "value": (
                    f"• Premium: **{premium_fmt}**\n"
                    f"• Volume: **{total_volume:,}** | Δ **{volume_delta:,}**\n"
                    f"• VOI Ratio: **{voi_ratio:.1f}x** 🔥\n"
                    f"• Side: **{side_indicator}**"
                ),
                "inline": False,
            },
            {
                "name": "💵 Contract Details",
                "value": (
                    f"• Price: **${contract_price:.2f}**\n"
                    f"• DTE: **{dte_days}** days\n"
                    f"• % OTM: **{metrics.percent_otm*100:.2f}%**\n"
                    f"{f'• Spread: ${ask_price:.2f} / ${bid_price:.2f}' if ask_price and bid_price else ''}"
                ),
                "inline": False,
            },
            {
                "name": "📊 Context",
                "value": (
                    f"• Open Interest: **{oi_value:,}**\n"
                    f"{f'• Underlying: **${underlying_price:.2f}**' if underlying_price else ''}"
                ),
                "inline": False,
            },
        ]

        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=0x6A0DAD,  # violet
            fields=fields,
            footer="99 Cent Store • Sub-$1 Directional Whale Flow",
        )
        return embed

