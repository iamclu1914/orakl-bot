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
from typing import Any, Deque, Dict, List, Optional

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
        self.max_dte = Config.INDEX_WHALE_MAX_DTE
        self.max_multi_leg_ratio = Config.INDEX_WHALE_MAX_MULTI_LEG_RATIO
        self.cooldown_intraday_seconds = 900  # 15 minutes for 1-3 DTE reversals
        self.cooldown_same_day_seconds = 300  # 5 minutes for 0DTE bursts
        self._flow_stats: Dict[str, Dict[str, Any]] = {}
        self.min_score = Config.INDEX_WHALE_MIN_SCORE

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

                cooldown_key = f"{metrics.underlying}_{metrics.strike}_{metrics.option_type}_{metrics.expiration.strftime('%Y%m%d')}"
                stats_snapshot = self._update_flow_stats(
                    cooldown_key,
                    metrics=metrics,
                    spot_price=spot_price,
                )
                cooldown_seconds = self._get_cooldown_seconds(metrics)

                voi_ratio = flow.get("vol_oi_ratio", 0.0) or metrics.volume_over_oi or 0.0
                whale_score = self._calculate_whale_score(metrics, signal, voi_ratio)

                if whale_score < self.min_score:
                    self._log_skip(symbol, f"score {whale_score} < {self.min_score}")
                    continue

                if self._cooldown_active(cooldown_key, cooldown_seconds=cooldown_seconds):
                    hits = stats_snapshot.get("hits", 1)
                    total_premium = self._format_currency(stats_snapshot.get("total_premium", float(metrics.premium or 0.0)))
                    self._log_skip(
                        symbol,
                        f"cooldown active ({cooldown_seconds // 60}m) - repeat hit x{hits} total {total_premium}",
                    )
                    continue

                signals.append(
                    {
                        "metrics": metrics,
                        "flow": flow,
                        "signal": signal,
                        "spot_price": spot_price,
                        "price_change_pct": price_change_pct,
                        "stats": stats_snapshot,
                        "cooldown_seconds": cooldown_seconds,
                        "cooldown_key": cooldown_key,
                        "score": whale_score,
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

        # Deduplication: Prevent same contract from alerting multiple times in 10 minutes
        stats: Dict[str, Any] = payload.get("stats") or {}
        cooldown_seconds: int = payload.get("cooldown_seconds", self.cooldown_intraday_seconds)
        cooldown_key: str = payload.get("cooldown_key") or f"{metrics.underlying}_{metrics.strike}_{metrics.option_type}_{metrics.expiration.strftime('%Y%m%d')}"

        embed = self._build_embed(
            metrics,
            signal,
            spot_price,
            flow,
            stats=stats,
            cooldown_seconds=cooldown_seconds,
            price_change_pct=payload.get("price_change_pct"),
            score=payload.get("score"),
        )
        success = await self.post_to_discord(embed)
        
        if success:
            self._mark_cooldown(cooldown_key)
            if cooldown_key in self._flow_stats:
                self._flow_stats[cooldown_key]["last_alerted"] = datetime.utcnow()
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
        """
        Filter for intraday reversal plays (1-3 DTE, OTM, ask-side, whale flow).
        Logs rejection reasons for debugging.
        """
        symbol = metrics.underlying
        
        if metrics.size <= 0:
            self._log_skip(symbol, "size <= 0")
            return False
            
        # Premium filter for whale detection
        if metrics.premium < self.min_premium:
            self._log_skip(symbol, f"premium ${metrics.premium:,.0f} < ${self.min_premium:,.0f}")
            return False
            
        # Multi-leg filter: Allow small ratio for complex hedges
        multi_leg_ratio = metrics.multi_leg_ratio if metrics.multi_leg_ratio is not None else 0.0
        if multi_leg_ratio > self.max_multi_leg_ratio:
            self._log_skip(symbol, f"multi-leg ratio {multi_leg_ratio:.2f} > {self.max_multi_leg_ratio:.2f}")
            return False
            
        if metrics.percent_otm > self.max_percent_otm:
            self._log_skip(symbol, f"OTM {metrics.percent_otm*100:.2f}% > {self.max_percent_otm*100:.2f}%")
            return False
            
        if not metrics.is_ask_side:
            self._log_skip(symbol, "not ask-side")
            return False
            
        if metrics.volume_over_oi <= 1.0:
            self._log_skip(symbol, f"VOI {metrics.volume_over_oi:.2f}x <= 1.0x")
            return False
            
        # DTE bounds for intraday reversals (1-3 days)
        if metrics.dte < self.min_dte:
            self._log_skip(symbol, f"DTE {metrics.dte:.2f} < {self.min_dte:.2f}")
            return False
            
        if metrics.dte > self.max_dte:
            self._log_skip(symbol, f"DTE {metrics.dte:.2f} > {self.max_dte:.2f}")
            return False
            
        return True

    def _within_session(self) -> bool:
        now = datetime.now(self.tz)
        if now.weekday() >= 5:
            return False
        start = now.replace(hour=self.open_hour, minute=self.open_minute, second=0, microsecond=0)
        end = now.replace(hour=self.close_hour, minute=self.close_minute, second=0, microsecond=0)
        return start <= now <= end

    def _calculate_whale_score(self, metrics: OptionTradeMetrics, signal: WhaleFlowSignal, voi_ratio: float) -> int:
        """
        Calculate quality score for Index Whale signals (0-100).
        
        Scoring factors:
        - Premium tier (whale size)
        - VOI ratio (speculative heat)
        - Pattern strength
        - Streak length
        """
        score = 0
        
        # Premium tiers (max 40 points)
        if metrics.premium >= 500_000:
            score += 40
        elif metrics.premium >= 250_000:
            score += 30
        elif metrics.premium >= 100_000:
            score += 20
        elif metrics.premium >= 50_000:
            score += 10
        
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
        
        # Pattern strength (max 20 points)
        pattern_scores = {
            "STRONG_FLIP": 20,
            "DIVERGENCE": 18,
            "LADDER": 15,
            "FLIP": 12,
            "CONTINUATION": 10,
            "FLOW": 5,
            "CHOP": 0,
        }
        score += pattern_scores.get(signal.label, 5)
        
        # Streak bonus (max 10 points)
        if signal.streak >= 5:
            score += 10
        elif signal.streak >= 4:
            score += 7
        elif signal.streak >= 3:
            score += 5
        elif signal.streak >= 2:
            score += 3
        
        return min(score, 100)

    def _update_price_history(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
    ) -> Optional[float]:
        """
        Track price changes over PRICE_WINDOW_MINUTES for divergence detection.
        Returns percentage change from earliest price in window.
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=120)  # Fixed: added maxlen

        history = self._price_history[symbol]
        history.append((timestamp, price))

        cutoff = timestamp - timedelta(minutes=PRICE_WINDOW_MINUTES)
        while history and history[0][0] < cutoff:
            history.popleft()

        if len(history) < 2:
            return None

        earliest_price = history[0][1]
        if not earliest_price or earliest_price <= 0:
            return None

        return (price - earliest_price) / earliest_price * 100.0

    def _build_embed(
        self,
        metrics: OptionTradeMetrics,
        signal: WhaleFlowSignal,
        spot_price: float,
        flow: Dict,
        stats: Optional[Dict[str, Any]] = None,
        cooldown_seconds: Optional[int] = None,
        price_change_pct: Optional[float] = None,
        score: Optional[int] = None,
    ) -> Dict:
        expiration_str = metrics.expiration.strftime("%m/%d/%Y")
        
        # Calculate quality score
        voi_ratio = flow.get("vol_oi_ratio", 0.0) or metrics.volume_over_oi or 0.0
        whale_score = score if score is not None else self._calculate_whale_score(metrics, signal, voi_ratio)
        
        title = (
            f"{metrics.underlying} {metrics.strike:.1f} "
            f"{metrics.option_type[0]} {expiration_str} ({int(round(metrics.dte))}D) - Index Whale"
        )
        label_prefix = {
            "STRONG_FLIP": "🚨",  # Strong directional reversal
            "FLIP": "⚠️",
            "LADDER": "🪜",
            "CONTINUATION": "🔥",
            "DIVERGENCE": "🌀",
            "CHOP": "🟡",
            "FLOW": "📈" if metrics.option_type == "CALL" else "📉",
        }.get(signal.label, "🔥")

        volume = flow.get("total_volume")
        open_interest = flow.get("open_interest")
        volume_delta = flow.get("volume_delta")
        ask_price = flow.get("ask")
        bid_price = flow.get("bid")

        hits = stats.get("hits", 1) if stats else 1
        total_premium = stats.get("total_premium", float(metrics.premium or 0.0)) if stats else float(metrics.premium or 0.0)
        first_seen = stats.get("first_seen") if stats else None
        last_seen = stats.get("last_seen") if stats else None
        first_spot = stats.get("first_spot") if stats else None
        last_alerted = stats.get("last_alerted") if stats else None

        flow_lines = [
            f"Premium: **{self._format_currency(metrics.premium)}**",
            f"Size: **{int(volume_delta or metrics.size):,}**",
            f"Price: **${(metrics.price or 0):.2f}**",
        ]
        if hits > 1:
            flow_lines.append(f"Cumulative: **{self._format_currency(total_premium)} ({hits} hits)**")
        flow_lines.append(f"Vol/OI: **{voi_ratio:.2f}x**")
        if ask_price and bid_price:
            flow_lines.append(f"Spread (Ask/Bid): **${ask_price:.2f} / ${bid_price:.2f}**")

        contract_lines = [
            f"DTE: **{metrics.dte:.1f}**",
            f"% OTM: **{metrics.percent_otm * 100:.2f}%**",
            f"Spot: **${spot_price:.2f}**",
            f"Score: **{whale_score}/100**",
        ]
        if volume is not None:
            contract_lines.append(f"Day Vol: **{int(volume):,}**")
        if open_interest is not None:
            contract_lines.append(f"OI: **{int(open_interest):,}**")
        if volume_delta is not None:
            contract_lines.append(f"Volume Δ: **{int(volume_delta):,}**")

        streak_text = f"Streak: **{signal.streak} bursts**" if signal.streak else ""
        notes = signal.notes or []
        notes_text = "\n".join(notes) if notes else "Repeated hits alert"

        context_lines: List[str] = []
        if stats:
            now = datetime.utcnow()
            if hits > 1:
                context_lines.append(f"Hits: **{hits}x**")
                context_lines.append(f"Cumulative premium: **{self._format_currency(total_premium)}**")
            if first_seen:
                minutes_active = max(int((now - first_seen).total_seconds() // 60), 0)
                context_lines.append(f"Active **{minutes_active} min**")
            if last_seen:
                minutes_since = max(int((now - last_seen).total_seconds() // 60), 0)
                context_lines.append(f"Last hit **{minutes_since} min ago**")
            if first_spot:
                try:
                    spot_change_pct = (spot_price - first_spot) / first_spot * 100
                    context_lines.append(f"Spot Δ (since first): **{spot_change_pct:+.2f}%**")
                except ZeroDivisionError:
                    pass
            if cooldown_seconds:
                context_lines.append(f"Cooldown: **{cooldown_seconds // 60} min**")

        if price_change_pct is not None:
            context_lines.append(f"Spot Δ (5m): **{price_change_pct:+.2f}%**")

        fields = [
            {"name": "💥 Flow Snapshot", "value": "\n".join(flow_lines), "inline": True},
            {"name": "📊 Contract Setup", "value": "\n".join(contract_lines), "inline": True},
        ]

        pattern_lines = [f"Pattern: **{signal.label}** ({signal.direction})"]
        if streak_text:
            pattern_lines.append(streak_text)
        pattern_lines.append("")
        pattern_lines.append(notes_text)
        fields.append({"name": "🧭 Pattern Context", "value": "\n".join(pattern_lines), "inline": False})

        if context_lines:
            fields.append({"name": "⌛ Flow Timeline", "value": " • ".join(context_lines), "inline": False})

        description = ""
        return self.create_signal_embed_with_disclaimer(
            title=f"{label_prefix} {title}",
            description=description,
            color=0x00FF7F if metrics.option_type == "CALL" else 0xFF4500,
            fields=fields,
            footer="Index Whale Bot | REST Flow",
        )

    def _get_cooldown_seconds(self, metrics: OptionTradeMetrics) -> int:
        if metrics.dte <= 0.5:
            return self.cooldown_same_day_seconds
        return self.cooldown_intraday_seconds

    def _update_flow_stats(
        self,
        key: str,
        metrics: OptionTradeMetrics,
        spot_price: float,
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        premium = float(metrics.premium or 0.0)
        stats = self._flow_stats.get(key)

        def reset() -> Dict[str, Any]:
            return {
                "first_seen": now,
                "last_seen": now,
                "hits": 1,
                "total_premium": premium,
                "first_spot": spot_price,
                "last_spot": spot_price,
                "last_alerted": None,
            }

        if not stats or not stats.get("first_seen") or stats["first_seen"].date() != now.date():
            stats = reset()
        else:
            stats["hits"] += 1
            stats["total_premium"] += premium
            stats["last_seen"] = now
            stats["last_spot"] = spot_price

        self._flow_stats[key] = stats
        return dict(stats)

    @staticmethod
    def _format_currency(value: float) -> str:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "$0"

        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"${value / 1_000:.0f}K"
        return f"${value:,.0f}"

