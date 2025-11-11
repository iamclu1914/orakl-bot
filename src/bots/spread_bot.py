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
        self.min_voi_ratio = Config.SPREAD_MIN_VOI_RATIO  # Min VOI for speculative heat

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

                # Filter: Contract price must be under $1.00
                contract_price = metrics.price
                if contract_price is None or contract_price <= 0:
                    self._log_skip(symbol, "missing contract price")
                    continue

                if contract_price >= self.max_price:
                    self._log_skip(symbol, f"price ${contract_price:.2f} >= ${self.max_price:.2f}")
                    continue

                # Filter: Premium must meet whale threshold
                if metrics.premium < self.min_premium:
                    self._log_skip(symbol, f"premium ${metrics.premium:,.0f} < ${self.min_premium:,.0f}")
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

    async def _post_signal(self, payload: Dict) -> bool:
        metrics: OptionTradeMetrics = payload["metrics"]
        contract_price: float = payload["contract_price"]
        flow: Dict = payload["flow"]

        embed = self._build_embed(metrics, contract_price, flow)
        return await self.post_to_discord(embed)

    def _build_embed(
        self,
        metrics: OptionTradeMetrics,
        contract_price: float,
        flow: Dict,
    ) -> Dict:
        dte_days = int(round(metrics.dte))
        expiration_fmt = metrics.expiration.strftime("%Y-%m-%d") if isinstance(metrics.expiration, datetime) else str(metrics.expiration)

        title = f"🟣 99 Cent Store Alert • {metrics.underlying}"
        description = (
            f"{metrics.option_type.title()} ${metrics.strike:.2f} expiring {expiration_fmt} "
            f"({max(dte_days, 0)} DTE)"
        )

        premium_fmt = f"${metrics.premium/1_000_000:.1f}M" if metrics.premium >= 1_000_000 else f"${metrics.premium/1_000:.0f}K"
        volume_delta = flow.get("volume_delta", 0)
        total_volume = flow.get("total_volume", 0)
        voi_ratio = flow.get("vol_oi_ratio", 0.0) or metrics.volume_over_oi or 0.0

        oi_value = flow.get("open_interest", 0)
        underlying_price = flow.get("underlying_price")
        ask_price = flow.get("ask")
        bid_price = flow.get("bid")

        fields = [
            {
                "name": "💰 Whale Flow",
                "value": (
                    f"• Premium: **{premium_fmt}**\n"
                    f"• Volume: **{total_volume:,}** | Δ **{volume_delta:,}**\n"
                    f"• VOI Ratio: **{voi_ratio:.2f}x** 🔥"
                ),
                "inline": False,
            },
            {
                "name": "💵 Contract Price",
                "value": (
                    f"• **${contract_price:.2f}**\n"
                    f"{f'• Ask / Bid: ${ask_price:.2f} / ${bid_price:.2f}' if ask_price and bid_price else ''}"
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
            footer="99 Cent Store • Under $1.00 Whale Flow Scanner",
        )
        return embed

