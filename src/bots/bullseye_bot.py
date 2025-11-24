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
from src.utils.event_bus import event_bus

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
        self.min_volume = min(Config.BULLSEYE_MIN_VOLUME, 2500)
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

        # High-conviction overrides / mid-print allowances
        self.midprint_spread_pct_cap = 6.5  # allow wider mid-prints through
        self.midprint_midpoint_factor = 0.96  # trade must print at/above 96% of midpoint
        self.midprint_voi_override = 1.5
        self.midprint_premium_override = max(self.min_premium * 1.25, 1_250_000)
        self.high_conviction_premium = max(self.min_premium * 1.5, 1_500_000)
        self.low_price_floor = max(0.15, self.min_price * 0.6)
        self.low_volume_override = max(self.min_block_contracts * 2, 1000)
        self.percent_otm_extension = 0.05  # allow +5% OTM when premium is massive
        self._subscription_registered = False
        self._subscription_lock = asyncio.Lock()
        self._golden_scan_lock = asyncio.Lock()
        self.trigger_min_volume = getattr(
            Config, "BULLSEYE_TRIGGER_MIN_VOLUME", max(self.min_block_contracts, 750)
        )

    async def start(self):
        await self._ensure_subscription()
        await super().start()

    async def _ensure_subscription(self) -> None:
        if self._subscription_registered:
            return

        async with self._subscription_lock:
            if self._subscription_registered:
                return
            await event_bus.subscribe("golden_sweep_detected", self._handle_golden_sweep_event)
            self._subscription_registered = True

    async def _handle_golden_sweep_event(self, **payload: Any) -> None:
        if not self.running:
            return

        symbol = payload.get("symbol")
        option_type = (payload.get("option_type") or payload.get("direction") or "").upper()

        if not symbol or option_type not in {"CALL", "PUT"}:
            return

        try:
            async with self._golden_scan_lock:
                await self._scan_golden_triggered(symbol, option_type, payload)
        except Exception as exc:
            logger.exception("%s golden sweep processing failed for %s: %s", self.name, symbol, exc)

    @staticmethod
    def _extract_numeric(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        if isinstance(value, dict):
            for key in ("price", "p", "value", "midpoint", "bid", "ask", "close", "last"):
                extracted = BullseyeBot._extract_numeric(value.get(key))
                if extracted is not None:
                    return extracted
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_trade_price(self, contract: Dict[str, Any]) -> Optional[float]:
        day_data = contract.get("day", {}) or {}
        last_trade = contract.get("last_trade") or {}
        last_quote = contract.get("last_quote") or {}

        candidates = [
            day_data.get("close"),
            day_data.get("last"),
            last_trade.get("price"),
            last_trade.get("p"),
        ]

        quote_last = last_quote.get("last")
        candidates.append(quote_last)
        if isinstance(quote_last, dict):
            candidates.extend([quote_last.get("price"), quote_last.get("p")])

        candidates.extend(
            [
                last_quote.get("midpoint"),
                last_quote.get("ask"),
                last_quote.get("bid"),
                day_data.get("open"),
                day_data.get("high"),
                day_data.get("low"),
            ]
        )

        for candidate in candidates:
            value = self._extract_numeric(candidate)
            if value and value > 0:
                return value
        return None

    def _resolve_underlying_price(self, contract: Dict[str, Any]) -> Optional[float]:
        asset = contract.get("underlying_asset") or {}
        for key in ("price", "close", "prev_close"):
            value = self._extract_numeric(asset.get(key))
            if value and value > 0:
                return value
        return None

    async def _scan_golden_triggered(self, symbol: str, option_type: str, event_payload: Dict[str, Any]) -> None:
        contracts = await self.fetcher.get_option_chain_snapshot(
            symbol, contract_type="call" if option_type == "CALL" else "put"
        )

        if not contracts:
            logger.debug("%s golden trigger: no contracts for %s", self.name, symbol)
            return

        best_candidate: Optional[Dict[str, Any]] = None
        underlying_price = None
        now = datetime.utcnow()

        for contract in contracts:
            details = contract.get("details") or {}
            strike = self._extract_numeric(details.get("strike_price"))
            expiration_str = details.get("expiration_date")

            if strike is None or not expiration_str:
                continue

            try:
                expiration_dt = datetime.fromisoformat(expiration_str)
            except ValueError:
                continue

            dte = max((expiration_dt - now).total_seconds() / 86400.0, 0.0)
            if dte < self.min_dte or dte > self.max_dte:
                continue

            day_data = contract.get("day", {}) or {}
            volume = int(day_data.get("volume") or 0)
            if volume < self.trigger_min_volume:
                continue

            last_quote = contract.get("last_quote") or {}
            ask = self._extract_numeric(last_quote.get("ask"))
            bid = self._extract_numeric(last_quote.get("bid"))
            midpoint = self._extract_numeric(last_quote.get("midpoint"))

            trade_price = ask or self._resolve_trade_price(contract)
            if not trade_price or trade_price <= 0:
                continue

            contract_price = float(trade_price)

            spread_pct = None
            if ask and bid and ask > 0 and bid > 0:
                spread_pct = self._calculate_spread_pct(bid, ask)
                if spread_pct is not None and spread_pct > self.max_spread_pct:
                    continue

            if midpoint is None and ask and bid:
                midpoint = (ask + bid) / 2.0

            candidate_underlying = self._resolve_underlying_price(contract)
            if candidate_underlying:
                underlying_price = candidate_underlying
            candidate_underlying_value = candidate_underlying or underlying_price

            open_interest = int(contract.get("open_interest") or 0)
            voi_ratio = (volume / open_interest) if open_interest > 0 else 100.0
            premium = contract_price * volume * 100.0

            if premium < self.min_premium * 0.75:
                continue

            if open_interest > 0 and volume <= open_interest:
                continue

            intensity = (
                "AGGRESSIVE"
                if premium >= self.high_conviction_premium or volume >= self.min_block_contracts * 2
                else "STRONG"
            )

            candidate = {
                "ticker": contract.get("ticker"),
                "strike": float(strike),
                "expiration": expiration_str,
                "price": contract_price,
                "ask": ask or contract_price,
                "bid": bid,
                "midpoint": midpoint,
                "volume": volume,
                "open_interest": open_interest,
                "premium": premium,
                "dte": dte,
                "underlying_price": candidate_underlying_value,
                "spread_pct": spread_pct,
                "voi_ratio": voi_ratio,
                "intensity": intensity,
            }

            if not candidate["ticker"]:
                continue

            if not best_candidate or candidate["volume"] > best_candidate["volume"]:
                best_candidate = candidate
            elif best_candidate and candidate["volume"] == best_candidate["volume"]:
                if candidate["premium"] > best_candidate.get("premium", 0):
                    best_candidate = candidate

        if not best_candidate:
            logger.info("%s golden trigger: no qualifying contracts for %s", self.name, symbol)
            return

        if not underlying_price:
            underlying_price = await self.fetcher.get_stock_price(symbol)

        if not best_candidate.get("underlying_price"):
            best_candidate["underlying_price"] = underlying_price

        flow_payload: Dict[str, Any] = {
            "ticker": best_candidate["ticker"],
            "underlying": symbol,
            "type": option_type,
            "strike": best_candidate["strike"],
            "expiration": best_candidate["expiration"],
            "volume_delta": best_candidate["volume"],
            "total_volume": best_candidate["volume"],
            "open_interest": best_candidate["open_interest"],
            "last_price": best_candidate["price"],
            "ask": best_candidate["ask"],
            "bid": best_candidate["bid"],
            "midpoint": best_candidate["midpoint"],
            "premium": best_candidate["premium"],
            "underlying_price": best_candidate.get("underlying_price") or underlying_price,
            "timestamp": datetime.now(timezone.utc),
            "multi_leg_ratio": 0.0,
            "vol_oi_ratio": best_candidate["voi_ratio"],
            "flow_intensity": best_candidate["intensity"],
            "last_trade_timestamp": datetime.now(timezone.utc),
        }

        metrics = build_metrics_from_flow(flow_payload)
        if not metrics:
            logger.info("%s golden trigger: failed to build metrics for %s", self.name, symbol)
            return

        cooldown_key = self._build_cooldown_key(metrics)
        if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
            logger.debug("%s golden trigger: cooldown active for %s", self.name, cooldown_key)
            return

        score = self._calculate_block_score(
            metrics=metrics,
            voi_ratio=best_candidate["voi_ratio"],
            block_size=best_candidate["volume"],
            intensity=best_candidate["intensity"],
            spread_pct=best_candidate["spread_pct"],
        )

        if score < Config.BULLSEYE_MIN_SCORE:
            logger.debug("%s golden trigger: score %d below threshold for %s", self.name, score, symbol)
            return

        payload = {
            "metrics": metrics,
            "flow": flow_payload,
            "contract_price": metrics.price,
            "score": score,
            "cooldown_key": cooldown_key,
            "spread_pct": best_candidate["spread_pct"],
            "origin_event": event_payload,
            "triggered_by_golden": True,
        }

        posted = await self._post_signal(payload)
        if posted:
            logger.info(
                "%s golden trigger alert %s %.2f %s volume %s premium %s",
                self.name,
                metrics.underlying,
                metrics.strike,
                metrics.option_type,
                best_candidate["volume"],
                f"{metrics.premium:,.0f}",
            )

    async def scan_and_post(self):
        await self._ensure_subscription()
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

            premium = float(metrics.premium or 0.0)
            volume_delta = int(flow.get("volume_delta") or 0)
            total_volume = int(flow.get("total_volume") or 0)
            voi_ratio = flow.get("vol_oi_ratio")
            if voi_ratio is None:
                voi_ratio = metrics.volume_over_oi or 0.0
            else:
                try:
                    voi_ratio = float(voi_ratio)
                except (TypeError, ValueError):
                    voi_ratio = metrics.volume_over_oi or 0.0

            bid = float(flow.get("bid") or 0.0)
            ask = float(flow.get("ask") or 0.0)
            spread_pct = self._calculate_spread_pct(bid, ask)

            if not metrics.is_single_leg:
                self._log_skip(symbol, "multi-leg structure (spread)")
                continue

            if not metrics.is_ask_side:
                midpoint = ((bid + ask) / 2) if (bid > 0 and ask > 0) else None
                trade_price = metrics.price or flow.get("last_price")
                midprint_ok = (
                    spread_pct is not None
                    and spread_pct <= self.midprint_spread_pct_cap
                    and midpoint
                    and trade_price is not None
                    and trade_price >= midpoint * self.midprint_midpoint_factor
                )
                voi_override = voi_ratio >= self.midprint_voi_override
                premium_override = premium >= self.midprint_premium_override
                if not (midprint_ok or (voi_override and premium_override)):
                    self._log_skip(symbol, "not ask-side (no aggressive buyer)")
                    continue

            contract_price = metrics.price or 0.0
            if contract_price <= 0:
                self._log_skip(symbol, "missing contract price")
                continue

            if contract_price < self.min_price:
                if not (
                    premium >= self.high_conviction_premium
                    and contract_price >= self.low_price_floor
                ):
                    self._log_skip(symbol, f"price ${contract_price:.2f} < ${self.min_price:.2f}")
                    continue

            dte = metrics.dte
            if dte < self.min_dte or dte > self.max_dte:
                allow_short_dte = (
                    dte >= -0.05
                    and premium >= self.high_conviction_premium
                    and volume_delta >= self.min_block_contracts
                )
                allow_far_dte = (
                    dte > self.max_dte
                    and premium >= self.high_conviction_premium
                    and (dte - self.max_dte) <= 5.0
                )
                if not (allow_short_dte or allow_far_dte):
                    self._log_skip(symbol, f"DTE {dte:.2f} outside {self.min_dte}-{self.max_dte}")
                    continue

            percent_otm = abs(metrics.percent_otm)
            if percent_otm > self.max_percent_otm:
                if not (
                    premium >= self.high_conviction_premium
                    and percent_otm <= self.max_percent_otm + self.percent_otm_extension
                ):
                    self._log_skip(symbol, f"%OTM {percent_otm*100:.2f}% > {self.max_percent_otm*100:.2f}%")
                    continue

            if volume_delta < self.min_block_contracts:
                self._log_skip(symbol, f"block size {volume_delta} < {self.min_block_contracts}")
                continue

            if total_volume < self.min_volume:
                if not (
                    premium >= self.high_conviction_premium
                    and volume_delta >= self.low_volume_override
                ):
                    self._log_skip(symbol, f"day volume {total_volume} < {self.min_volume}")
                    continue

            if premium < self.min_premium:
                self._log_skip(symbol, f"premium ${premium:,.0f} < ${self.min_premium:,.0f}")
                continue

            if voi_ratio < self.min_voi_ratio:
                if not (
                    premium >= self.high_conviction_premium
                    and voi_ratio >= max(self.min_voi_ratio * 0.8, 0.8)
                ):
                    self._log_skip(symbol, f"VOI {voi_ratio:.2f}x < {self.min_voi_ratio:.2f}x")
                    continue

            flow_intensity = (flow.get("flow_intensity") or "NORMAL").upper()
            if self.required_intensity and flow_intensity not in self.required_intensity:
                self._log_skip(symbol, f"intensity {flow_intensity} below STRONG")
                continue

            if spread_pct is not None and spread_pct > self.max_spread_pct:
                self._log_skip(symbol, f"spread {spread_pct:.2f}% > {self.max_spread_pct:.2f}%")
                continue

            # Enforce Volume > Open Interest (Net New Positioning)
            if int(flow.get("open_interest") or 0) > 0:
                if total_volume <= int(flow.get("open_interest") or 0):
                    self._log_skip(symbol, f"Vol {total_volume} <= OI {flow.get('open_interest')} (not new positioning)")
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

