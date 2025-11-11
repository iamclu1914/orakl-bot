"""
99 Cent Store Bot - identifies narrow-spread institutional option flow.
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
    Detects large premium option trades with option bid/ask spreads under a configurable threshold.
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
        self.max_spread = Config.SPREAD_MAX_SPREAD

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

                ask_price = flow.get("ask")
                bid_price = flow.get("bid")
                if ask_price is None or bid_price is None:
                    self._log_skip(symbol, "spread missing quote data")
                    continue

                spread_value = ask_price - bid_price
                if spread_value < 0:
                    self._log_skip(symbol, f"negative spread {spread_value:.2f}")
                    continue

                if spread_value > self.max_spread:
                    self._log_skip(symbol, f"spread {spread_value:.2f} > ${self.max_spread:.2f}")
                    continue

                if metrics.premium < self.min_premium:
                    self._log_skip(symbol, f"premium ${metrics.premium:,.0f} < ${self.min_premium:,.0f}")
                    continue

                total_volume = flow.get("total_volume", 0)
                if total_volume < self.min_volume:
                    self._log_skip(symbol, f"volume {total_volume} < {self.min_volume}")
                    continue

                volume_delta = flow.get("volume_delta", 0)
                if volume_delta < self.min_volume_delta:
                    self._log_skip(symbol, f"volume delta {volume_delta} < {self.min_volume_delta}")
                    continue

                signals.append(
                    {
                        "metrics": metrics,
                        "spread": spread_value,
                        "ask": ask_price,
                        "bid": bid_price,
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
        spread: float = payload["spread"]
        ask_price: float = payload["ask"]
        bid_price: float = payload["bid"]
        flow: Dict = payload["flow"]

        embed = self._build_embed(metrics, spread, ask_price, bid_price, flow)
        return await self.post_to_discord(embed)

    def _build_embed(
        self,
        metrics: OptionTradeMetrics,
        spread_value: float,
        ask_price: float,
        bid_price: float,
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
        voi_ratio = flow.get("vol_oi_ratio", 0.0)

        oi_value = flow.get("open_interest", 0)
        underlying_price = flow.get("underlying_price")

        context_lines = [f"• Open Interest: **{oi_value:,}**"]
        if underlying_price:
            context_lines.append(f"• Underlying: **${underlying_price:.2f}**")

        fields = [
            {
                "name": "🔍 Snapshot",
                "value": (
                    f"• Premium: **{premium_fmt}**\n"
                    f"• Volume: **{total_volume:,}** | Δ **{volume_delta:,}**\n"
                    f"• VOI Ratio: **{voi_ratio:.2f}x**"
                ),
                "inline": False,
            },
            {
                "name": "🎯 Pricing",
                "value": (
                    f"• Ask / Bid: **${ask_price:.2f} / ${bid_price:.2f}**\n"
                    f"• Spread: **${spread_value:.2f}**\n"
                    f"• Last: **${metrics.price:.2f}**"
                ),
                "inline": False,
            },
            {
                "name": "📈 Context",
                "value": "\n".join(context_lines),
                "inline": False,
            },
        ]

        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description=description,
            color=0x6A0DAD,  # violet
            fields=fields,
            footer="99 Cent Store • Narrow Spread Flow Scanner",
        )
        return embed

