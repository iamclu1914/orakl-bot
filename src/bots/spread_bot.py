"""
99 Cent Store Bot - finds swing trade contracts under $1.00 with high conviction whale flow (5-21 DTE).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from .base_bot import BaseAutoBot
from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.flow_metrics import build_metrics_from_flow, OptionTradeMetrics
from src.utils.enhanced_analysis import EnhancedAnalyzer

logger = logging.getLogger(__name__)


class SpreadBot(BaseAutoBot):
    """
    Detects swing trade contracts under $1.00 with high conviction whale flow (5-21 DTE, $250K+ premium, 2.0+ VOI).
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
        
        # Enhanced analysis
        self.enhanced_analyzer = EnhancedAnalyzer(fetcher)

        # Thresholds
        self.min_premium = Config.SPREAD_MIN_PREMIUM
        self.min_volume = Config.SPREAD_MIN_VOLUME
        self.min_volume_delta = Config.SPREAD_MIN_VOLUME_DELTA
        raw_max_price = Config.SPREAD_MAX_PRICE
        self.max_price = min(raw_max_price, 1.00)  # Double-lock sub-$1 requirement
        self.min_price = Config.SPREAD_MIN_PRICE  # Avoid illiquid penny options
        self.min_voi_ratio = Config.SPREAD_MIN_VOI_RATIO  # Min VOI for speculative heat
        self.min_dte = Config.SPREAD_MIN_DTE
        self.max_dte = Config.SPREAD_MAX_DTE
        self.max_percent_otm = Config.SPREAD_MAX_PERCENT_OTM
        self.cooldown_seconds = 1800  # 30 minute cooldown to prevent spam
        self._flow_stats: Dict[str, Dict[str, Any]] = {}

    async def _scan_symbol(self, symbol: str) -> List[Dict]:
        signals: List[Dict] = []
        logged_reasons: Set[str] = set()

        def log_once(reason: str) -> None:
            if reason not in logged_reasons:
                self._log_skip(symbol, reason)
                logged_reasons.add(reason)

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
                    log_once("multi-leg spread detected")
                    continue

                # Filter: Contract price must be under $1.00 but above minimum
                contract_price = metrics.price
                if contract_price is None or contract_price <= 0:
                    log_once("missing contract price")
                    continue

                if contract_price < self.min_price:
                    log_once(f"price ${contract_price:.2f} < ${self.min_price:.2f} (illiquid)")
                    continue

                if contract_price > self.max_price:
                    log_once(f"price ${contract_price:.2f} > ${self.max_price:.2f}")
                    continue

                premium = float(metrics.premium or 0.0)
                voi_ratio = flow.get("vol_oi_ratio")
                if voi_ratio is None:
                    voi_ratio = metrics.volume_over_oi or 0.0
                else:
                    try:
                        voi_ratio = float(voi_ratio)
                    except (TypeError, ValueError):
                        voi_ratio = metrics.volume_over_oi or 0.0

                # Filter: Premium must meet whale threshold
                if premium < self.min_premium:
                    log_once(f"premium ${premium:,.0f} < ${self.min_premium:,.0f}")
                    continue

                # Filter: Must be OTM (directional speculation, not stock substitute)
                if not metrics.is_otm:
                    log_once("not OTM (ITM = stock substitute)")
                    continue

                if metrics.percent_otm > self.max_percent_otm:
                    log_once(f"OTM {metrics.percent_otm*100:.2f}% > {self.max_percent_otm*100:.2f}%")
                    continue

                # Filter: Ask-side for directional conviction
                if not metrics.is_ask_side:
                    bid = float(flow.get("bid") or 0.0)
                    ask = float(flow.get("ask") or 0.0)
                    midpoint = ((bid + ask) / 2) if (bid > 0 and ask > 0) else None
                    trade_price = float(contract_price or flow.get("last_price") or 0.0)
                    spread_pct = None
                    if midpoint:
                        spread_pct = ((ask - bid) / midpoint) * 100 if midpoint else None
                    midprint_ok = (
                        spread_pct is not None
                        and spread_pct <= 5.0
                        and trade_price >= midpoint * 0.97
                    )
                    voi_override = voi_ratio >= (self.min_voi_ratio + 0.3)
                    premium_override = premium >= (self.min_premium * 1.2)
                    if not (midprint_ok or (voi_override and premium_override)):
                        log_once("not ask-side (no directional conviction)")
                        continue

                # Filter: DTE bounds (1-7 days for speculative plays)
                if metrics.dte < self.min_dte:
                    log_once(f"DTE {metrics.dte:.2f} < {self.min_dte:.2f}")
                    continue

                if metrics.dte > self.max_dte:
                    log_once(f"DTE {metrics.dte:.2f} > {self.max_dte:.2f} (too far out)")
                    continue

                # Filter: Volume must meet threshold
                total_volume = flow.get("total_volume", 0)
                if total_volume < self.min_volume:
                    log_once(f"volume {total_volume} < {self.min_volume}")
                    continue

                volume_delta = flow.get("volume_delta", 0)
                if volume_delta < self.min_volume_delta:
                    log_once(f"volume delta {volume_delta} < {self.min_volume_delta}")
                    continue

                # Filter: VOI ratio for speculative heat
                if voi_ratio < self.min_voi_ratio:
                    voi_override = (
                        premium >= (self.min_premium * 1.4)
                        and volume_delta >= (self.min_volume_delta * 2)
                        and voi_ratio >= max(self.min_voi_ratio * 0.8, 1.0)
                    )
                    if not voi_override:
                        log_once(f"VOI ratio {voi_ratio:.2f}x < {self.min_voi_ratio:.2f}x")
                        continue

                # 10-minute Candle Verification (Mirroring Bullseye Logic)
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
                            
                    # Underlying Stock Trend Verification
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
                             log_once("10m stock candle is not green (Call needs green)")
                             continue
                        if metrics.option_type == 'PUT' and not is_red:
                             log_once("10m stock candle is not red (Put needs red)")
                             continue

                except Exception as e:
                    logger.debug(f"{self.name} failed to verify 10m candle for {flow['ticker']}: {e}")

                # Trend Alignment Check (EnhancedAnalyzer)
                try:
                    alignment = await self.enhanced_analyzer.check_price_action_alignment(symbol, metrics.option_type)
                    if alignment:
                        # Momentum Check:
                        # If CALL, want positive momentum. If PUT, want negative.
                        
                        m5 = alignment.get('momentum_5m', 0)
                        m15 = alignment.get('momentum_15m', 0)
                        
                        if metrics.option_type == 'CALL':
                            if m5 < 0 and m15 < 0:
                                log_once(f"fighting trend (5m: {m5:.2f}%, 15m: {m15:.2f}%)")
                                continue
                        elif metrics.option_type == 'PUT':
                            if m5 > 0 and m15 > 0:
                                log_once(f"fighting trend (5m: {m5:.2f}%, 15m: {m15:.2f}%)")
                                continue
                except Exception as e:
                    logger.debug(f"{self.name} trend check failed for {symbol}: {e}")

                # Check cooldown BEFORE adding to signals (prevents duplicates)
                cooldown_key = f"{metrics.underlying}_{metrics.strike}_{metrics.option_type}_{metrics.expiration.strftime('%Y%m%d')}"
                stats_snapshot = self._update_flow_stats(cooldown_key, float(metrics.premium or 0.0))
                if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
                    if stats_snapshot.get("hits", 1) > 1:
                        total_premium = self._format_currency(stats_snapshot.get("total_premium", 0.0))
                        hits = stats_snapshot.get("hits", 1)
                        log_once(
                            f"cooldown ({self.cooldown_seconds // 60}m) active - repeat hit x{hits} total {total_premium}"
                        )
                    else:
                        log_once(f"cooldown active (already alerted in last {self.cooldown_seconds // 60} min)")
                    continue

                signals.append(
                    {
                        "metrics": metrics,
                        "contract_price": contract_price,
                        "flow": flow,
                        "stats": stats_snapshot,
                    }
                )

        except Exception as exc:
            logger.error(f"{self.name} error scanning {symbol}: {exc}")
            return []

        # Return top 3 signals by premium
        return sorted(signals, key=lambda s: s["metrics"].premium, reverse=True)[:3]

    def _update_flow_stats(self, key: str, premium: float) -> Dict[str, Any]:
        """Track repeat flow statistics for cumulative summaries."""
        now = datetime.utcnow()
        stats = self._flow_stats.get(key)

        def _reset() -> Dict[str, Any]:
            return {
                "first_seen": now,
                "last_seen": now,
                "hits": 1,
                "total_premium": premium,
            }

        if not stats or not stats.get("first_seen") or stats["first_seen"].date() != now.date():
            stats = _reset()
        else:
            stats["hits"] += 1
            stats["total_premium"] += premium
            stats["last_seen"] = now

        self._flow_stats[key] = stats
        return dict(stats)

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

    @staticmethod
    def _format_currency(value: float) -> str:
        """Format premium totals into human-readable strings."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "$0"

        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"${value / 1_000:.0f}K"
        return f"${value:,.0f}"

    async def _post_signal(self, payload: Dict) -> bool:
        metrics: OptionTradeMetrics = payload["metrics"]
        contract_price: float = payload["contract_price"]
        flow: Dict = payload["flow"]

        # Build cooldown key
        cooldown_key = f"{metrics.underlying}_{metrics.strike}_{metrics.option_type}_{metrics.expiration.strftime('%Y%m%d')}"
        
        # Post the signal
        stats = payload.get("stats")

        embed = self._build_embed(metrics, contract_price, flow, stats)
        success = await self.post_to_discord(embed)
        
        if success:
            self._mark_cooldown(cooldown_key)  # Mark AFTER successful post
            if cooldown_key in self._flow_stats:
                self._flow_stats[cooldown_key]["last_alerted"] = datetime.utcnow()
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
        stats: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Build enhanced Discord embed with two-column layout and repeat-flow context."""
        dte_days = int(round(metrics.dte))
        expiration_fmt = metrics.expiration.strftime("%m/%d/%Y") if isinstance(metrics.expiration, datetime) else str(metrics.expiration)

        # Build title: TICKER STRIKE TYPE EXPIRY (DTE) - 99 Cent Store
        option_type_short = "C" if metrics.option_type.upper() == "CALL" else "P"
        title = f"{metrics.underlying} {metrics.strike} {option_type_short} {expiration_fmt} ({dte_days}D) - 99 Cent Store"

        # Get flow data
        volume_delta = flow.get("volume_delta", 0)
        total_volume = flow.get("total_volume", 0)
        oi_value = flow.get("open_interest", 0) or 0
        voi_ratio = flow.get("vol_oi_ratio", 0.0) or metrics.volume_over_oi or 0.0
        
        # Get bid/ask prices
        ask_price = flow.get("ask", 0)
        bid_price = flow.get("bid", 0)

        # Premium formatting
        premium_fmt = f"${metrics.premium/1_000_000:.0f}M" if metrics.premium >= 1_000_000 else f"${metrics.premium/1_000:.0f}K"
        
        # Calculate price targets (15%, 20%, 25% above current price)
        target_15 = contract_price * 1.15
        target_20 = contract_price * 1.20
        target_25 = contract_price * 1.25

        hits = stats.get("hits", 1) if stats else 1
        total_premium = stats.get("total_premium", float(metrics.premium or 0.0)) if stats else float(metrics.premium or 0.0)

        flow_lines = [
            f"Price: **${contract_price:.2f}**",
            f"Size: **{volume_delta:,}**",
            f"Premium: **{premium_fmt}**",
        ]
        if hits > 1:
            flow_lines.append(f"Cumulative: **{self._format_currency(total_premium)} ({hits} hits)**")
        flow_lines.append(f"Vol/OI: **{voi_ratio:.2f}x**")
        flow_lines.append(f"Spread (Ask/Bid): **${ask_price:.2f} / ${bid_price:.2f}**")

        contract_lines = [
            f"DTE: **{dte_days} days**",
            f"% OTM: **{metrics.percent_otm*100:.2f}%**",
            f"OI: **{oi_value:,}**",
            f"Day Vol: **{total_volume:,}**",
        ]
        contract_lines.extend(
            [
                "",
                "**Targets**",
                f"15%: **${target_15:.2f}**",
                f"20%: **${target_20:.2f}**",
                f"25%: **${target_25:.2f}**",
            ]
        )

        fields = [
            {
                "name": "💥 Flow Snapshot",
                "value": "\n".join(flow_lines),
                "inline": True,
            },
            {
                "name": "📊 Contract Setup",
                "value": "\n".join(contract_lines),
                "inline": True,
            },
        ]

        context_parts: List[str] = []
        if stats:
            now = datetime.utcnow()
            first_seen = stats.get("first_seen")
            last_seen = stats.get("last_seen")
            if hits > 1:
                context_parts.append(f"Repeat hits: **{hits}x**")
            context_parts.append(f"Cumulative premium: **{self._format_currency(total_premium)}**")
            if first_seen:
                minutes_active = max(int((now - first_seen).total_seconds() // 60), 0)
                context_parts.append(f"Active for **{minutes_active} min**")
            if last_seen:
                minutes_since = max(int((now - last_seen).total_seconds() // 60), 0)
                context_parts.append(f"Last hit **{minutes_since} min ago**")

        if context_parts:
            fields.append(
                {
                    "name": "🧭 Context",
                    "value": " • ".join(context_parts),
                    "inline": False,
                }
            )

        embed = self.create_signal_embed_with_disclaimer(
            title=title,
            description="",
            color=0x6A0DAD,  # violet
            fields=fields,
            footer="99 Cent Store • High Conviction Swing Trades",
        )
        return embed

