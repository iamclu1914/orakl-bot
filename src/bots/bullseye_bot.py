"""Bullseye Bot - Massive institutional block scanner.

Independent scanning - each bot scans its own watchlist directly.
Uses batching for efficient concurrent API calls.
"""

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
from src.utils.enhanced_analysis import EnhancedAnalyzer, should_take_signal
from src.utils.event_bus import event_bus
from src.utils.option_contract_format import format_option_contract_pretty, normalize_option_ticker

logger = logging.getLogger(__name__)


class BullseyeBot(BaseAutoBot):
    """
    Bullseye Bot surfaces massive institutional block trades (1–5 DTE).

    Contract price may exceed $1.00 – filters focus on conviction:
    - $1M+ premium blocks
    - 400+ contract prints (single leg, ask-side)
    - Fresh positioning (Vol/OI ≥ 1.0)
    
    ORAKL v3.0: Now includes Brain validation (HedgeHunter + ContextManager)
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
            "Bullseye Bot", 
            scan_interval=Config.BULLSEYE_INTERVAL,
            hedge_hunter=hedge_hunter,
            context_manager=context_manager
        )
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
        self.midprint_spread_pct_cap = 8.0  # allow wider mid-prints through
        self.midprint_midpoint_factor = 0.94  # trade must print at/above 94% of midpoint
        self.midprint_voi_override = 1.5
        self.midprint_premium_override = max(self.min_premium * 1.1, 750_000)
        self.high_conviction_premium = max(self.min_premium * 1.3, 1_000_000)
        self.low_price_floor = max(0.15, self.min_price * 0.6)
        self.low_volume_override = max(self.min_block_contracts * 2, 1000)
        self.percent_otm_extension = 0.05  # allow +5% OTM when premium is massive
        self._subscription_registered = False
        self._subscription_lock = asyncio.Lock()
        self._golden_scan_lock = asyncio.Lock()
        self.trigger_min_volume = getattr(
            Config, "BULLSEYE_TRIGGER_MIN_VOLUME", max(self.min_block_contracts, 750)
        )
        # Full scan mode - scan ALL symbols every cycle (no batching)
        self.scan_batch_size = 0  # 0 = full scan
        self.concurrency_limit = 30  # High concurrency for speed
        
        # Skip expensive validation API calls (candles, trend) - use local filtering only
        self.skip_expensive_validation = getattr(Config, 'BULLSEYE_SKIP_EXPENSIVE_VALIDATION', True)

    # =========================================================================
    # ORAKL v2.0: Kafka Event Processing
    # =========================================================================
    
    async def process_event(self, enriched_trade: Dict) -> Optional[Dict]:
        """
        Process a single enriched trade event from Kafka for institutional blocks.
        
        Evaluates if the trade qualifies as a Bullseye alert based on:
        - Premium threshold ($1M+)
        - Block size (400+ contracts)
        - DTE range (1-30 days)
        - OTM distance (<12%)
        - Vol/OI ratio (fresh positioning)
        
        Args:
            enriched_trade: Trade data enriched with Greeks, OI, Bid/Ask
            
        Returns:
            Alert payload dict if trade qualifies, None otherwise
        """
        try:
            symbol = enriched_trade.get('symbol', '')
            premium = float(enriched_trade.get('premium', 0))
            
            # Skip if below minimum premium
            if premium < self.min_premium:
                self._count_filter("premium_below_min")
                return None
            
            # Extract key fields
            strike = float(enriched_trade.get('strike_price') or enriched_trade.get('strike') or 0)
            underlying_price = float(enriched_trade.get('underlying_price') or enriched_trade.get('current_price') or 0)
            contract_type = str(enriched_trade.get('contract_type') or enriched_trade.get('type') or '').upper()
            open_interest = int(enriched_trade.get('open_interest', 0))
            day_volume = int(enriched_trade.get('day_volume', 0))
            trade_size = int(enriched_trade.get('trade_size', 0))
            delta = float(enriched_trade.get('delta', 0))
            dte = int(enriched_trade.get('dte', 0))
            contract_price = float(enriched_trade.get('trade_price', 0))
            bid = float(enriched_trade.get('current_bid', 0))
            ask = float(enriched_trade.get('current_ask', 0))
            
            # Validate required fields (count granular reasons so we can fix schema quickly)
            if not symbol:
                self._count_filter("missing_symbol")
                return None
            if strike <= 0:
                self._count_filter("missing_strike")
                return None
            if underlying_price <= 0:
                self._count_filter("missing_underlying_price")
                return None
            if not contract_type:
                self._count_filter("missing_contract_type")
                return None
            
            # Check DTE range
            if dte < self.min_dte or dte > self.max_dte:
                self._count_filter("dte_out_of_range", symbol=symbol, sample_record=True)
                self._log_skip(symbol, f"DTE {dte} outside range [{self.min_dte}, {self.max_dte}]")
                return None
            
            # Check contract price
            if contract_price < self.min_price:
                self._count_filter("contract_price_below_min", symbol=symbol, sample_record=True)
                self._log_skip(symbol, f"contract price ${contract_price:.2f} < ${self.min_price:.2f}")
                return None
            
            # Calculate OTM percentage
            if underlying_price > 0:
                if contract_type == 'CALL':
                    otm_pct = max(0, (strike - underlying_price) / underlying_price)
                else:
                    otm_pct = max(0, (underlying_price - strike) / underlying_price)
            else:
                return None
            
            # Calculate max OTM with extension for massive premium
            max_otm = self.max_percent_otm
            if premium >= self.high_conviction_premium:
                max_otm += self.percent_otm_extension
            
            # Check OTM distance
            if otm_pct > max_otm:
                self._count_filter("otm_too_far", symbol=symbol, sample_record=True)
                self._log_skip(symbol, f"OTM {otm_pct*100:.1f}% > max {max_otm*100:.1f}%")
                return None
            
            # Check block size (volume delta)
            if trade_size < self.min_block_contracts:
                self._count_filter("block_size_below_min", symbol=symbol, sample_record=True)
                self._log_skip(symbol, f"block size {trade_size} < {self.min_block_contracts}")
                return None
            
            # Calculate Vol/OI ratio
            effective_volume = trade_size if trade_size > 0 else day_volume
            if open_interest > 0:
                vol_oi_ratio = effective_volume / open_interest
            else:
                vol_oi_ratio = effective_volume  # No OI = assume fresh
            
            # Check Vol/OI ratio (fresh positioning)
            if vol_oi_ratio < self.min_voi_ratio:
                self._count_filter("voi_below_min", symbol=symbol, sample_record=True)
                self._log_skip(symbol, f"vol/OI {vol_oi_ratio:.2f} < {self.min_voi_ratio:.2f}")
                return None
            
            # Check bid-ask spread
            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / ((ask + bid) / 2) * 100
                if spread_pct > self.max_spread_pct:
                    # Allow wider spreads for massive premium
                    if not (premium >= self.midprint_premium_override and spread_pct <= self.midprint_spread_pct_cap):
                        self._log_skip(symbol, f"spread {spread_pct:.1f}% > max {self.max_spread_pct:.1f}%")
                        return None
            
            # Check cooldown
            cooldown_key = f"{symbol}_{contract_type}_{strike}_{enriched_trade.get('expiration_date', '')}"
            if self._cooldown_active(cooldown_key, self.cooldown_seconds):
                self._log_skip(symbol, "cooldown active")
                return None
            
            # Calculate score
            score = self._calculate_bullseye_score(enriched_trade, vol_oi_ratio, otm_pct)
            
            min_score = Config.BULLSEYE_MIN_SWEEP_SCORE
            if score < min_score:
                self._log_skip(symbol, f"score {score} < min {min_score}")
                return None
            
            # Build alert data
            alert = {
                'symbol': symbol,
                'ticker': symbol,
                'type': contract_type if contract_type in ['CALL', 'PUT'] else 'CALL',
                'strike': strike,
                'expiration': enriched_trade.get('expiration_date', ''),
                'premium': premium,
                'volume': day_volume,
                'volume_delta': trade_size,
                'open_interest': open_interest,
                'vol_oi_ratio': vol_oi_ratio,
                'underlying_price': underlying_price,
                'current_price': underlying_price,
                'otm_pct': otm_pct * 100,
                'delta': delta,
                'dte': dte,
                'days_to_expiry': dte,
                'score': score,
                'ai_score': score,
                'contract_price': contract_price,
                'bid': bid,
                'ask': ask,
                'moneyness': 'ITM' if otm_pct == 0 else ('ATM' if otm_pct < 0.02 else 'OTM'),
                'execution_type': 'BLOCK',
                'kafka_event': True,
                'event_timestamp': enriched_trade.get('event_timestamp'),
            }
            
            # Mark cooldown
            self._mark_cooldown(cooldown_key)
            
            # Post the signal
            await self._post_signal(alert)
            
            logger.info(f"{self.name} ALERT: {symbol} {contract_type} block ${premium:,.0f} score={score}")
            
            return alert
            
        except Exception as e:
            logger.error(f"{self.name} error processing event: {e}")
            return None
    
    def _calculate_bullseye_score(self, trade: Dict, vol_oi_ratio: float, otm_pct: float) -> int:
        """Calculate conviction score for an institutional block trade."""
        score = 50  # Base score
        
        premium = float(trade.get('premium', 0))
        trade_size = int(trade.get('trade_size', 0))
        delta = abs(float(trade.get('delta', 0)))
        dte = int(trade.get('dte', 0))
        
        # Premium tiers (institutional size)
        if premium >= 5000000:
            score += 30
        elif premium >= 2000000:
            score += 25
        elif premium >= 1500000:
            score += 20
        elif premium >= 1000000:
            score += 15
        
        # Block size
        if trade_size >= 1000:
            score += 15
        elif trade_size >= 600:
            score += 10
        elif trade_size >= 400:
            score += 5
        
        # Vol/OI ratio (fresh positioning)
        if vol_oi_ratio >= 3.0:
            score += 10
        elif vol_oi_ratio >= 2.0:
            score += 7
        elif vol_oi_ratio >= 1.5:
            score += 5
        
        # OTM distance (closer is better)
        if otm_pct < 0.02:
            score += 10  # ATM
        elif otm_pct < 0.05:
            score += 7
        elif otm_pct < 0.08:
            score += 5
        
        # Delta (sweet spot range)
        if 0.35 <= delta <= 0.65:
            score += 5
        
        # DTE (short-term = higher conviction)
        if 1 <= dte <= 7:
            score += 10
        elif 7 < dte <= 14:
            score += 5
        
        return min(score, 100)

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
            await event_bus.subscribe("sweep_detected", self._handle_sweep_event)
            self._subscription_registered = True

    async def _handle_golden_sweep_event(self, **payload: Any) -> None:
        if not self.running:
            return

        symbol = payload.get("symbol")
        option_type = (payload.get("option_type") or payload.get("direction") or "").upper()

        if not symbol or option_type not in {"CALL", "PUT"}:
            return

        sweep_payload = payload.get("sweep") or {}
        min_score = getattr(Config, "MIN_GOLDEN_SCORE", 85)
        payload_score = (
            payload.get("final_score")
            or sweep_payload.get("final_score")
            or sweep_payload.get("enhanced_score")
            or sweep_payload.get("sweep_score")
        )

        if self._is_score_blocked(payload_score, payload.get("score_passed")):
            logger.debug(
                "%s ignoring golden sweep event for %s (score %.1f below threshold)",
                self.name,
                symbol,
                float(payload_score) if payload_score is not None else -1.0,
            )
            return
    async def _handle_sweep_event(self, **payload: Any) -> None:
        if not self.running:
            return

        symbol = payload.get("symbol")
        if not symbol:
            return

        option_type = (payload.get("option_type") or payload.get("direction") or "").upper()
        if option_type not in {"CALL", "PUT"}:
            return

        sweep_payload = payload.get("sweep") or payload
        payload_score = (
            sweep_payload.get("enhanced_score")
            or sweep_payload.get("sweep_score")
            or payload.get("score")
        )

        if self._is_score_blocked(payload_score, payload.get("score_passed")):
            return

        try:
            async with self._golden_scan_lock:
                await self._scan_golden_triggered(symbol, option_type, payload)
        except Exception as exc:
            logger.exception("%s sweep processing failed for %s: %s", self.name, symbol, exc)

    @staticmethod
    def _is_score_blocked(payload_score: Optional[float], score_passed_flag: Optional[bool]) -> bool:
        if score_passed_flag is False:
            return True
        min_score = getattr(Config, "BULLSEYE_MIN_SWEEP_SCORE", 65)
        if isinstance(payload_score, (int, float)):
            return payload_score < min_score
        return False

    async def _candidate_from_event(
        self,
        symbol: str,
        option_type: str,
        event_payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        sweep = event_payload.get("sweep") or {}
        if not sweep:
            return None

        expiration = sweep.get("expiration")
        strike = sweep.get("strike")
        premium = sweep.get("premium")
        volume = sweep.get("volume_delta") or sweep.get("volume")

        try:
            strike = float(strike)
            premium = float(premium or 0.0)
            volume = int(volume or 0)
        except (TypeError, ValueError):
            return None

        if premium <= 0 or volume <= 0 or not expiration:
            return None

        contract_price = sweep.get("contract_price") or sweep.get("price") or sweep.get("avg_price")
        if contract_price is None:
            try:
                contract_price = premium / (volume * 100.0)
            except ZeroDivisionError:
                contract_price = None

        if contract_price is None or contract_price <= 0:
            return None

        underlying_price = sweep.get("current_price") or event_payload.get("underlying_price")
        try:
            expiration_dt = datetime.fromisoformat(expiration)
            dte = max((expiration_dt - datetime.utcnow()).total_seconds() / 86400.0, 0.0)
        except ValueError:
            dte = sweep.get("days_to_expiry")
            if isinstance(dte, (int, float)):
                dte = float(dte)
            else:
                dte = None

        bid = sweep.get("bid")
        ask = sweep.get("ask")
        midpoint = sweep.get("midpoint")
        spread_pct = None
        try:
            bid_val = float(bid) if bid is not None else None
            ask_val = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            bid_val = ask_val = None

        if bid_val and ask_val and bid_val > 0 and ask_val > 0:
            spread_pct = self._calculate_spread_pct(bid_val, ask_val)
            if midpoint is None:
                midpoint = (bid_val + ask_val) / 2.0

        voi_ratio = sweep.get("volume_ratio") or sweep.get("vol_oi_ratio")
        if voi_ratio is None:
            open_interest = sweep.get("open_interest")
            try:
                if open_interest:
                    voi_ratio = float(volume) / float(open_interest)
            except (TypeError, ValueError, ZeroDivisionError):
                voi_ratio = None

        intensity = (sweep.get("flow_intensity") or sweep.get("alert_type") or "SWEEP").upper()

        ticker = sweep.get("ticker") or sweep.get("option_symbol")
        if not ticker:
            ticker = f"{symbol}{expiration.replace('-', '')}{option_type[0]}{int(strike * 1000)}"

        candidate = {
            "ticker": ticker,
            "strike": strike,
            "expiration": expiration,
            "price": float(contract_price),
            "ask": ask_val or float(contract_price),
            "bid": bid_val,
            "midpoint": midpoint if midpoint is not None else float(contract_price),
            "volume": volume,
            "open_interest": sweep.get("open_interest") or 0,
            "premium": premium,
            "dte": dte if isinstance(dte, (int, float)) else None,
            "underlying_price": underlying_price,
            "spread_pct": spread_pct,
            "voi_ratio": float(voi_ratio) if isinstance(voi_ratio, (int, float)) else 0.0,
            "intensity": intensity,
            "execution_type": sweep.get("execution_type", "SWEEP"),
            "origin": "event",
        }
        return candidate

    async def _finalize_candidate(
        self,
        symbol: str,
        option_type: str,
        candidate: Dict[str, Any],
        event_payload: Dict[str, Any],
        underlying_price: Optional[float] = None,
    ) -> bool:
        volume = int(candidate.get("volume") or 0)
        if volume <= 0:
            return False

        premium = float(candidate.get("premium") or 0.0)
        if premium <= 0:
            return False

        underlying_price = (
            candidate.get("underlying_price")
            or underlying_price
            or await self.fetcher.get_stock_price(symbol)
        )

        candidate["underlying_price"] = underlying_price

        flow_payload: Dict[str, Any] = {
            "ticker": candidate["ticker"],
            "underlying": symbol,
            "type": option_type,
            "strike": candidate["strike"],
            "expiration": candidate["expiration"],
            "volume_delta": volume,
            "total_volume": volume,
            "open_interest": candidate.get("open_interest"),
            "last_price": candidate["price"],
            "ask": candidate.get("ask"),
            "bid": candidate.get("bid"),
            "midpoint": candidate.get("midpoint"),
            "premium": premium,
            "underlying_price": candidate.get("underlying_price"),
            "timestamp": datetime.now(timezone.utc),
            "multi_leg_ratio": 0.0,
            "vol_oi_ratio": candidate.get("voi_ratio", 0.0),
            "flow_intensity": candidate.get("intensity", "SWEEP"),
            "last_trade_timestamp": datetime.now(timezone.utc),
            "execution_type": candidate.get("execution_type", "SWEEP"),
        }

        metrics = build_metrics_from_flow(flow_payload)
        if not metrics:
            logger.info("%s trigger: failed to build metrics for %s", self.name, symbol)
            return False

        cooldown_key = self._build_cooldown_key(metrics)
        if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
            logger.debug("%s trigger: cooldown active for %s", self.name, cooldown_key)
            return False

        score = self._calculate_block_score(
            metrics=metrics,
            voi_ratio=candidate.get("voi_ratio", 0.0),
            block_size=volume,
            intensity=candidate.get("intensity", "SWEEP"),
            spread_pct=candidate.get("spread_pct"),
        )

        min_score = Config.BULLSEYE_MIN_SCORE
        if candidate.get("execution_type", "SWEEP").upper() == "SWEEP":
            min_score = getattr(Config, "BULLSEYE_MIN_SWEEP_SCORE", 65)

        if score < min_score:
            logger.debug("%s trigger: score %d below threshold for %s", self.name, score, symbol)
            return False

        oi_value = flow_payload.get("open_interest") or 0
        if oi_value and volume <= oi_value:
            self._log_skip(symbol, f"volume {volume} <= OI {oi_value}")
            return False

        trend_data = await self.enhanced_analyzer.get_trend_alignment(symbol)
        if trend_data:
            desired = "BULLISH" if option_type == "CALL" else "BEARISH"
            if not all(tf_info.get("trend") == desired for tf_info in trend_data.values()):
                self._log_skip(symbol, f"trend misaligned ({desired} required)")
                return False

        # Four Axes Framework: Get market context and validate alignment
        market_context = await self.enhanced_analyzer.get_market_context(symbol)
        context_data = None
        
        if market_context:
            # Check if signal aligns with market context
            should_take, reason = should_take_signal(option_type, market_context)
            
            if not should_take:
                self._log_skip(symbol, f"Four Axes rejection: {reason}")
                return False
            
            # Apply conviction multiplier to score
            original_score = score
            score = int(score * market_context.conviction_multiplier)
            
            if score != original_score:
                logger.debug(
                    "%s %s score adjusted %d -> %d (mult=%.2f, regime=%s)",
                    self.name, symbol, original_score, score,
                    market_context.conviction_multiplier, market_context.regime
                )
            
            context_data = market_context.to_dict()

        payload = {
            "metrics": metrics,
            "flow": flow_payload,
            "contract_price": metrics.price,
            "score": score,
            "cooldown_key": cooldown_key,
            "spread_pct": candidate.get("spread_pct"),
            "origin_event": event_payload,
            "triggered_by_golden": candidate.get("origin") != "event",
            "trend_data": trend_data,
            "market_context": context_data,
        }

        posted = await self._post_signal(payload)
        if posted:
            logger.info(
                "%s trigger alert %s %.2f %s volume %s premium %s",
                self.name,
                metrics.underlying,
                metrics.strike,
                metrics.option_type,
                volume,
                f"{metrics.premium:,.0f}",
            )
        return posted

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
        event_candidate = await self._candidate_from_event(symbol, option_type, event_payload)
        if event_candidate:
            processed = await self._finalize_candidate(symbol, option_type, event_candidate, event_payload)
            if processed:
                return

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

            execution_type = "BLOCK" if volume >= self.min_block_contracts else "SWEEP"

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
                "execution_type": execution_type,
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
        await self._finalize_candidate(symbol, option_type, best_candidate, event_payload, underlying_price)

    async def scan_and_post(self):
        """
        Full scan - scans ALL watchlist symbols every cycle for institutional block flow.
        Uses two-phase approach: fast scan then deep validation.
        """
        await self._ensure_subscription()
        logger.info("%s starting full scan of %d symbols", self.name, len(self.watchlist))

        if not MarketHours.is_market_open(include_extended=False):
            logger.debug("%s skipping scan: market closed", self.name)
            return
        
        # Phase 1: Fast scan ALL symbols concurrently (with semaphore for rate limiting)
        all_candidates: List[Dict[str, Any]] = []
        max_alerts = 10  # Limit alerts per cycle
        
        # Full scan - all symbols at once with concurrency control
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def scan_with_limit(symbol: str):
            async with semaphore:
                return await self._fast_scan_symbol(symbol)
        
        tasks = [scan_with_limit(symbol) for symbol in self.watchlist]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_candidates.extend(result)
        
        logger.info("%s found %d candidates from fast scan", self.name, len(all_candidates))
        
        if not all_candidates:
            logger.debug("%s no candidates from fast scan", self.name)
            return
        
        # Sort by score and premium
        all_candidates.sort(key=lambda s: (s.get("score", 0), s.get("metrics").premium if s.get("metrics") else 0), reverse=True)
        
        # Phase 2: Deep validate and post top candidates
        posted_symbols = set()
        alerts_posted = 0
        
        for candidate in all_candidates[:max_alerts * 2]:  # Check more than we'll post
            try:
                metrics = candidate.get("metrics")
                if not metrics:
                    continue
                    
                symbol = metrics.underlying
                if symbol in posted_symbols:
                    continue

                # Deep validation (can make additional API calls if needed)
                validated = await self._deep_validate_candidate(candidate)
                if not validated:
                    continue

                success = await self._post_signal(candidate)
                if success:
                    posted_symbols.add(symbol)
                    alerts_posted += 1
                    # Add delay between posts to avoid Discord rate limits
                    if alerts_posted < max_alerts:
                        await asyncio.sleep(1.5)
                    if alerts_posted >= max_alerts:
                        break
            except Exception as e:
                logger.debug("%s error validating candidate: %s", self.name, e)
                continue
        
        logger.info("%s scan complete - posted %d alerts", self.name, alerts_posted)

    async def _fast_scan_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Phase 1: Fast flow detection with basic filtering only.
        NO expensive API calls (candles, alignment, trend) - those happen in Phase 2.
        Returns list of candidates for deep validation.
        """
        candidates: List[Dict[str, Any]] = []

        try:
            flows = await self.fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=self.min_premium,
                min_volume_delta=self.min_volume_delta,
                min_volume_ratio=0.0,
            )
        except Exception as exc:
            logger.debug("%s failed to load flow for %s: %s", self.name, symbol, exc)
            return candidates

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

            # === BASIC FILTERS (no API calls) ===
            
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
            oi_value = int(flow.get("open_interest") or 0)
            if oi_value and volume_delta <= oi_value:
                self._log_skip(symbol, f"volume {volume_delta} <= OI {oi_value} (no fresh positioning)")
                continue

            cooldown_key = self._build_cooldown_key(metrics)
            if self._cooldown_active(cooldown_key, cooldown_seconds=self.cooldown_seconds):
                self._log_skip(symbol, f"cooldown active ({cooldown_key})")
                continue

            # Passed basic filters - add to candidates for deep validation
            candidates.append({
                "symbol": symbol,
                "metrics": metrics,
                "flow": flow,
                "contract_price": contract_price,
                "voi_ratio": voi_ratio,
                "spread_pct": spread_pct,
                "flow_intensity": flow_intensity,
                "volume_delta": volume_delta,
                "cooldown_key": cooldown_key,
            })

        return candidates[:5]  # Limit candidates per symbol

    async def _deep_validate_candidate(self, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Phase 2: Deep validation with expensive API calls.
        Only called for candidates that passed basic filters.
        Returns signal dict if validation passes, None otherwise.
        """
        symbol = candidate["symbol"]
        metrics = candidate["metrics"]
        flow = candidate["flow"]
        
        try:
            # 10-minute Candle Verification
            # Ensure the option contract itself traded > $100k in the last 10 minutes
            try:
                bars_10m = await self.fetcher.get_aggregates(
                    flow['ticker'],
                    timespan='minute',
                    multiplier=10,
                    limit=1
                )
                
                if not bars_10m.empty:
                    last_bar = bars_10m.iloc[-1]
                    candle_premium = last_bar['volume'] * last_bar['close'] * 100
                    
                    if candle_premium < 100_000:
                        self._log_skip(symbol, f"10m option candle premium ${candle_premium:,.0f} < $100k")
                        return None

                # Stock Candle Logic
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
                        return None
                    if metrics.option_type == 'PUT' and not is_red:
                        self._log_skip(symbol, "10m stock candle is not red (Put needs red)")
                        return None
            except Exception as e:
                logger.debug(f"{self.name} failed to verify 10m candle for {flow['ticker']}: {e}")

            # Trend Alignment Check
            trend_data = None
            try:
                alignment = await self.enhanced_analyzer.check_price_action_alignment(symbol, metrics.option_type)
                if alignment:
                    m5 = alignment.get('momentum_5m', 0)
                    m15 = alignment.get('momentum_15m', 0)
                    
                    if metrics.option_type == 'CALL':
                        if m5 < 0 and m15 < 0:
                            self._log_skip(symbol, f"fighting trend (5m: {m5:.2f}%, 15m: {m15:.2f}%)")
                            return None
                    elif metrics.option_type == 'PUT':
                        if m5 > 0 and m15 > 0:
                            self._log_skip(symbol, f"fighting trend (5m: {m5:.2f}%, 15m: {m15:.2f}%)")
                            return None
            except Exception as e:
                logger.debug(f"{self.name} trend check failed for {symbol}: {e}")

            try:
                trend_data = await self.enhanced_analyzer.get_trend_alignment(symbol)
                if trend_data:
                    desired_trend = "BULLISH" if metrics.option_type.upper() == "CALL" else "BEARISH"
                    if not all(tf_info.get("trend") == desired_trend for tf_info in trend_data.values()):
                        self._log_skip(symbol, f"trend misaligned ({desired_trend} required)")
                        return None
            except Exception as e:
                logger.debug(f"{self.name} get_trend_alignment failed for {symbol}: {e}")

            # Calculate score
            score = self._calculate_block_score(
                metrics=metrics,
                voi_ratio=candidate["voi_ratio"],
                block_size=candidate["volume_delta"],
                intensity=candidate["flow_intensity"],
                spread_pct=candidate["spread_pct"],
            )

            return {
                "metrics": metrics,
                "flow": flow,
                "contract_price": candidate["contract_price"],
                "score": score,
                "cooldown_key": candidate["cooldown_key"],
                "spread_pct": candidate["spread_pct"],
                "trend_data": trend_data,
            }

        except Exception as e:
            logger.error(f"{self.name} deep validation error for {symbol}: {e}")
            return None

    async def _scan_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Legacy method for event-driven scans - uses both phases."""
        candidates = await self._fast_scan_symbol(symbol)
        signals = []
        for candidate in candidates:
            result = await self._deep_validate_candidate(candidate)
            if result:
                signals.append(result)
        return signals

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
        
        # ORAKL v3.0 Brain Validation - Check if signal is hedged or against market regime
        brain_metadata = {}
        if self.hedge_hunter or self.context_manager:
            sentiment = "bullish" if metrics.option_type.upper() == "CALL" else "bearish"
            sip_timestamp = flow.get("sip_timestamp")  # nanoseconds if available
            
            is_valid, brain_metadata = await self.validate_signal(
                symbol=metrics.underlying,
                premium=metrics.premium,
                option_size=int(flow.get("volume_delta") or flow.get("total_volume") or 0),
                sentiment=sentiment,
                sip_timestamp=sip_timestamp
            )
            
            if not is_valid:
                logger.info(
                    "🚫 %s filtered %s %s %s premium $%s - %s",
                    self.name,
                    metrics.underlying,
                    metrics.strike,
                    metrics.option_type,
                    f"{metrics.premium:,.0f}",
                    brain_metadata.get("hedge_reason", "Brain validation failed")
                )
                return False

        embed = self._build_embed(
            metrics,
            contract_price,
            flow,
            score,
            payload.get("spread_pct"),
            payload.get("trend_data"),
            payload.get("market_context"),
            brain_metadata,
        )
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
        trend_data: Optional[Dict[str, Dict[str, Any]]] = None,
        market_context: Optional[Dict[str, Any]] = None,
        brain_metadata: Optional[Dict[str, Any]] = None,
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
        execution_type = (flow.get("execution_type") or "SWEEP").upper()
        spot_price = flow.get("underlying_price") or metrics.underlying_price or 0.0

        premium_fmt = (
            f"${metrics.premium / 1_000_000:.1f}M"
            if metrics.premium >= 1_000_000
            else f"${metrics.premium / 1_000:.0f}K"
        )

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

        prob_itm = flow.get("probability_itm")
        if prob_itm is None:
            try:
                # Rough approximation from percent OTM
                pct_otm = metrics.percent_otm * 100.0
                prob_itm = max(0.0, min(100.0, 100.0 - abs(pct_otm)))
            except Exception:
                prob_itm = None
        if isinstance(prob_itm, float) and prob_itm <= 1.0:
            prob_itm *= 100.0

        momentum_direction = "BULLISH" if metrics.option_type.upper() == "CALL" else "BEARISH"
        momentum_value = voi_ratio if isinstance(voi_ratio, (int, float)) else 0.0

        liquidity_label = "Moderate"
        if spread_pct is None:
            liquidity_label = "n/a"
        elif spread_pct <= 2.0:
            liquidity_label = "Excellent"
        elif spread_pct <= 4.0:
            liquidity_label = "Good"
        elif spread_pct <= 7.0:
            liquidity_label = "Fair"

        expected_move = (
            flow.get("expected_move_5d")
            or flow.get("expected_move")
            or flow.get("implied_move_5d")
        )

        current_price_line = "n/a"
        try:
            if spot_price:
                current_price_line = f"${float(spot_price):.2f}"
        except Exception:
            current_price_line = "n/a"

        contract_pretty = format_option_contract_pretty(
            metrics.underlying,
            expiration_fmt,
            metrics.strike,
            metrics.option_type,
        )
        contract_id = normalize_option_ticker(getattr(metrics, "ticker", "") or "")

        description = (
            f"Current Price: **{current_price_line}**\n\n"
            "**Contract Details**\n\n"
            f"{contract_pretty} ({dte_days} days)"
        )

        title = f"{metrics.underlying} ${metrics.strike:.1f} {option_type_short} - Bullseye Signal"

        fields = [
            {"name": "Contract", "value": contract_pretty, "inline": False},
            {"name": "Contract ID", "value": f"`{contract_id}`" if contract_id else "Unavailable", "inline": False},
            {"name": "Premium", "value": premium_fmt, "inline": True},
            {"name": "Volume", "value": f"{total_volume:,}", "inline": True},
            {"name": "Open Interest", "value": f"{oi_value:,}", "inline": True},
            {
                "name": "ITM Probability",
                "value": f"{prob_itm:.1f}%" if isinstance(prob_itm, (int, float)) else "n/a",
                "inline": True,
            },
            {
                "name": "Momentum",
                "value": f"{momentum_value:.2f} {momentum_direction}"
                if isinstance(momentum_value, (int, float))
                else momentum_direction,
                "inline": True,
            },
            {"name": "Liquidity", "value": liquidity_label, "inline": True},
            {
                "name": "Expected Move (5d)",
                "value": (
                    f"${expected_move:.2f}"
                    if isinstance(expected_move, (int, float))
                    else "n/a"
                ),
                "inline": True,
            },
            {"name": "Flow Intensity", "value": f"{flow_intensity} ({recency_text})", "inline": True},
            {"name": "Bullseye Score", "value": f"{score}/100", "inline": True},
        ]

        if trend_data:
            tf_priority = {"1h": 0, "4h": 1, "1d": 2}
            ordered = sorted(trend_data.items(), key=lambda kv: tf_priority.get(kv[0], 99))
            trends_only = {tf: info.get("trend", "UNKNOWN") for tf, info in ordered}
            unique = set(trends_only.values())
            if len(unique) == 1:
                summary = f"{unique.pop()} ({'/'.join(trends_only.keys())})"
            else:
                summary = " | ".join(f"{tf}:{trend}" for tf, trend in trends_only.items())
            fields.append({"name": "Trend Alignment", "value": summary, "inline": True})

        # Four Axes Market Context
        if market_context:
            P = market_context.get("P", 0)
            V = market_context.get("V", 0)
            G = market_context.get("G", 0.5)
            regime = market_context.get("regime", "NEUTRAL")
            mult = market_context.get("conviction_multiplier", 1.0)
            
            # Format regime with emoji
            regime_emojis = {
                "BULLISH_CALL_DRIVEN": "🟢📈",
                "BEARISH_PUT_DRIVEN": "🔴📉",
                "BULLISH_PUT_HEDGED": "🟡⚠️",
                "BEARISH_CALL_HEDGED": "🟡🔄",
                "VOLATILITY_EXPANSION": "📊⬆️",
                "VOLATILITY_CONTRACTION": "📊⬇️",
                "NEUTRAL": "⚪",
            }
            regime_emoji = regime_emojis.get(regime, "⚪")
            regime_display = regime.replace("_", " ").title()
            
            context_value = f"{regime_emoji} {regime_display}\nP={P:+.2f} V={V:+.3f} G={G:.2f}"
            if mult != 1.0:
                context_value += f"\nConviction: {mult:.0%}"
            
            fields.append({"name": "Market Context", "value": context_value, "inline": True})

        # ORAKL v3.0 Brain Validation Status
        if brain_metadata and brain_metadata.get("brain_validated"):
            hedge_status = brain_metadata.get("hedge_status", "SKIPPED")
            gex_regime = brain_metadata.get("regime", "NEUTRAL")
            net_gex = brain_metadata.get("net_gex", 0)
            flip_level = brain_metadata.get("flip_level", 0)
            
            # Format GEX regime with emoji
            gex_emojis = {
                "POSITIVE_GAMMA": "🟢",  # Stabilizing market
                "NEGATIVE_GAMMA": "🔴",  # Volatile market
                "NEUTRAL": "⚪"
            }
            gex_emoji = gex_emojis.get(gex_regime, "⚪")
            
            # Hedge status
            if "VERIFIED" in hedge_status:
                inventory_text = "✅ Verified Unhedged"
            elif hedge_status == "SKIPPED":
                inventory_text = "⏭️ Not Checked"
            else:
                inventory_text = f"⚠️ {hedge_status}"
            
            fields.append({"name": "Inventory Check", "value": inventory_text, "inline": True})
            
            # GEX Context
            if gex_regime != "NEUTRAL" and flip_level > 0:
                gex_value = f"{gex_emoji} {gex_regime.replace('_', ' ').title()}"
                if net_gex != 0:
                    gex_fmt = f"${abs(net_gex)/1e9:.1f}B" if abs(net_gex) >= 1e9 else f"${abs(net_gex)/1e6:.0f}M"
                    gex_value += f"\nNet GEX: {'+' if net_gex > 0 else '-'}{gex_fmt}"
                if flip_level > 0:
                    gex_value += f"\nFlip: ${flip_level:.0f}"
                fields.append({"name": "GEX Regime", "value": gex_value, "inline": True})

        if execution_type == "BLOCK":
            fields.append(
                {
                    "name": "Execution",
                    "value": "Block contract (single print)",
                    "inline": False,
                }
            )
            fields.append(
                {"name": "Spread", "value": f"{spread_text} ({spread_label})", "inline": True}
            )
        else:
            fields.append(
                {"name": "Execution", "value": "Sweep accumulation", "inline": False}
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

