"""
Index Whale Bot - REST polling version.

Scans SPY/QQQ/IWM using Polygon REST data for ask-side, out-of-the-money flow
where volume exceeds open interest, allowing small multi-leg participation,
then classifies
patterns (continuations, flips, laddering, divergence) before posting to Discord.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional

import pytz

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.flow_metrics import OptionTradeMetrics, build_metrics_from_flow
from src.utils.whale_flow_tracker import WhaleFlowSignal, WhaleFlowTracker


logger = logging.getLogger(__name__)
PRICE_WINDOW_MINUTES = 5


class IndexWhaleBot(BaseAutoBot):
    """REST-based whale pressure tracker for index ETFs."""

    def __init__(
        self,
        webhook_url: str,
        fetcher: DataFetcher,
        watchlist: Optional[List[str]] = None,
    ):
        super().__init__(webhook_url, "Index Whale Bot", scan_interval=Config.INDEX_WHALE_INTERVAL)
        self.fetcher = fetcher
        self.watchlist = watchlist or list(Config.INDEX_WHALE_WATCHLIST)
        self.whale_tracker = WhaleFlowTracker()
        self._price_history: Dict[str, Deque[tuple[datetime, float]]] = {
            symbol: deque(maxlen=120) for symbol in self.watchlist
        }

        self.min_premium = Config.INDEX_WHALE_MIN_PREMIUM
        self.min_volume_delta = Config.INDEX_WHALE_MIN_VOLUME_DELTA
        self.max_percent_otm = Config.INDEX_WHALE_MAX_PERCENT_OTM
        self.min_dte = Config.INDEX_WHALE_MIN_DTE
        self.max_multi_leg_ratio = Config.INDEX_WHALE_MAX_MULTI_LEG_RATIO

        self.open_hour = Config.INDEX_WHALE_OPEN_HOUR
        self.open_minute = Config.INDEX_WHALE_OPEN_MINUTE
        self.close_hour = Config.INDEX_WHALE_CLOSE_HOUR
        self.close_minute = Config.INDEX_WHALE_CLOSE_MINUTE
        self.tz = pytz.timezone("America/New_York")

    async def scan_and_post(self):
        if not self._within_session():
            logger.debug("Index Whale Bot outside session window, skipping scan.")
            return
        await super().scan_and_post()

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

                if not self._passes_filters(metrics):
                    continue

                spot_price = flow.get("underlying_price")
                if not spot_price or spot_price <= 0:
                    spot_price = await self.fetcher.get_stock_price(symbol)
                    if not spot_price:
                        continue

                price_change_pct = self._update_price_history(symbol, spot_price, metrics.timestamp)
                signal = self.whale_tracker.process_trade(metrics, price_change_pct)

                signals.append(
                    {
                        "metrics": metrics,
                        "flow": flow,
                        "signal": signal,
                        "spot_price": spot_price,
                        "price_change_pct": price_change_pct,
                    }
                )

        except Exception as exc:
            logger.error(f"Index Whale Bot error scanning {symbol}: {exc}")
            return []

        signals.sort(key=lambda item: item["metrics"].premium, reverse=True)
        return signals[:3]

    async def _post_signal(self, payload: Dict) -> bool:
        metrics: OptionTradeMetrics = payload["metrics"]
        signal: WhaleFlowSignal = payload["signal"]
        spot_price: float = payload["spot_price"]
        flow: Dict = payload["flow"]

        embed = self._build_embed(metrics, signal, spot_price, flow)
        success = await self.post_to_discord(embed)
        if success:
            logger.info(
                "IndexWhale Alert: %s %.2f %s premium $%s [%s]",
                metrics.underlying,
                metrics.strike,
                metrics.option_type,
                f"{metrics.premium:,.0f}",
                signal.label,
            )
        return success

    def _passes_filters(self, metrics: OptionTradeMetrics) -> bool:
        if metrics.size <= 0:
            return False
        if not metrics.is_single_leg:
            return False
        if not metrics.is_otm:
            return False
        if metrics.percent_otm > self.max_percent_otm:
            return False
        if not metrics.is_ask_side:
            return False
        if metrics.volume_over_oi <= 1.0:
            return False
        if metrics.dte < self.min_dte:
            return False
        multi_leg_ratio = metrics.multi_leg_ratio if metrics.multi_leg_ratio is not None else 0.0
        if multi_leg_ratio > self.max_multi_leg_ratio:
            return False
        return True

    def _within_session(self) -> bool:
        now = datetime.now(self.tz)
        if now.weekday() >= 5:
            return False
        start = now.replace(hour=self.open_hour, minute=self.open_minute, second=0, microsecond=0)
        end = now.replace(hour=self.close_hour, minute=self.close_minute, second=0, microsecond=0)
        return start <= now <= end

    def _update_price_history(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
    ) -> Optional[float]:
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=120)

        history = self._price_history[symbol]
        history.append((timestamp, price))

        cutoff = timestamp - timedelta(minutes=PRICE_WINDOW_MINUTES)
        while history and history[0][0] < cutoff:
            history.popleft()

        if len(history) < 2:
            return None

        earliest_price = history[0][1]
        if not earliest_price:
            return None

        return (price - earliest_price) / earliest_price * 100.0

    def _build_embed(
        self,
        metrics: OptionTradeMetrics,
        signal: WhaleFlowSignal,
        spot_price: float,
        flow: Dict,
    ) -> Dict:
        expiration_str = metrics.expiration.strftime("%m/%d/%Y")
        title = (
            f"{metrics.underlying} {metrics.strike:.1f} "
            f"{metrics.option_type[0]} {expiration_str} ({int(round(metrics.dte))}D) - Index Whale"
        )
        label_prefix = {
            "FLIP": "⚠️",
            "LADDER": "🪜",
            "CONTINUATION": "🔥",
            "DIVERGENCE": "🌀",
            "CHOP": "🟡",
            "FLOW": "📈" if metrics.option_type == "CALL" else "📉",
        }.get(signal.label, "🔥")

        volume = flow.get("total_volume")
        open_interest = flow.get("open_interest")
        ask_size = flow.get("ask_size") or flow.get("askSize")
        bid_size = flow.get("bid_size") or flow.get("bidSize")

        fields = [
            {"name": "💰 Premium", "value": f"${metrics.premium:,.0f}", "inline": True},
            {"name": "💵 Price", "value": f"${metrics.price:.2f}", "inline": True},
            {"name": "⚖️ Volume/OI", "value": f"{metrics.volume_over_oi:.2f}x", "inline": True},
            {"name": "🚀 % OTM", "value": f"{metrics.percent_otm * 100:.2f}%", "inline": True},
            {"name": "⏳ DTE", "value": f"{metrics.dte:.2f}", "inline": True},
            {"name": "📉 Spot", "value": f"${spot_price:.2f}", "inline": True},
        ]

        if volume is not None:
            fields.append({"name": "🔁 Day Volume", "value": f"{int(volume):,}", "inline": True})
        if open_interest is not None:
            fields.append({"name": "📊 Open Interest", "value": f"{int(open_interest):,}", "inline": True})
        if ask_size or bid_size:
            fields.append(
                {"name": "🪙 Quote Size", "value": f"Ask {ask_size or 0:,} | Bid {bid_size or 0:,}", "inline": True}
            )

        if flow.get("volume_delta") is not None:
            fields.append({"name": "🔨 Volume Delta", "value": f"{int(flow['volume_delta']):,}", "inline": True})

        notes = "\n".join(signal.notes) if signal.notes else "Repeated hits alert • Happy Hunting!"

        description = f"**{signal.direction}** • {signal.label}"
        return self.create_signal_embed_with_disclaimer(
            title=f"{label_prefix} {title}",
            description=description,
            color=0x00FF7F if metrics.option_type == "CALL" else 0xFF4500,
            fields=fields + [{"name": "Pattern Notes", "value": notes, "inline": False}],
            footer="Index Whale Bot | REST Flow",
        )

