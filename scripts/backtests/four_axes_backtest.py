"""
Four Axes Framework Backtest

Tests the effectiveness of the P (Price Trend), V (Volatility Trend), and G (Gamma Ratio)
indicators over the last 10 trading days using Polygon historical data.

Methodology:
1. For each symbol and each trading day, compute P, V, and G
2. Identify days where signals would have been generated (extreme G values)
3. Measure next-day price movement to validate alignment theory
4. Calculate win rates for aligned vs misaligned signals

Key Hypotheses Being Tested:
- CALL signals with P > 0 and G > 0.6 should outperform
- PUT signals with P < 0 and G < 0.4 should outperform
- Misaligned signals (P and G disagreeing) should underperform
"""

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import pytz

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.enhanced_analysis import (
    EnhancedAnalyzer,
    MarketContext,
    should_take_signal,
)
from src.utils.gamma_ratio import compute_gamma_ratio, transform_polygon_snapshot

EASTERN_TZ = pytz.timezone("US/Eastern")


@dataclass
class DailySnapshot:
    """Snapshot of Four Axes values for a single symbol on a single day."""
    symbol: str
    date: datetime
    P: float  # Price trend
    V: float  # Volatility trend
    G: float  # Gamma ratio
    close: float  # Closing price
    next_day_return: Optional[float] = None  # Next day's return (for validation)
    regime: str = ""
    
    def __post_init__(self):
        if not self.regime:
            ctx = MarketContext(symbol=self.symbol, P=self.P, V=self.V, G=self.G)
            self.regime = ctx.regime


@dataclass
class SignalResult:
    """Result of a hypothetical signal."""
    symbol: str
    date: datetime
    signal_type: str  # "CALL" or "PUT"
    P: float
    V: float
    G: float
    regime: str
    aligned: bool  # Was signal aligned with context?
    conviction_mult: float
    entry_price: float
    next_day_return: float
    profitable: bool  # Did next day move in signal direction?


@dataclass
class BacktestResults:
    """Aggregated backtest results."""
    total_signals: int = 0
    aligned_signals: int = 0
    misaligned_signals: int = 0
    aligned_wins: int = 0
    aligned_losses: int = 0
    misaligned_wins: int = 0
    misaligned_losses: int = 0
    aligned_avg_return: float = 0.0
    misaligned_avg_return: float = 0.0
    daily_snapshots: List[DailySnapshot] = field(default_factory=list)
    signal_results: List[SignalResult] = field(default_factory=list)
    
    @property
    def aligned_win_rate(self) -> float:
        total = self.aligned_wins + self.aligned_losses
        return self.aligned_wins / total if total > 0 else 0.0
    
    @property
    def misaligned_win_rate(self) -> float:
        total = self.misaligned_wins + self.misaligned_losses
        return self.misaligned_wins / total if total > 0 else 0.0


# Test symbols - mix of high-volume names
TEST_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMD",
    "META", "GOOGL", "AMZN", "SPY", "QQQ",
    "NFLX", "COIN", "PLTR", "SOFI", "MARA",
    "RIOT", "NIO", "BABA", "JPM", "BAC",
]


def compute_price_trend_from_closes(closes: np.ndarray, period: int = 21) -> Optional[float]:
    """
    Compute P (price trend) from an array of closing prices.
    
    P = mean(daily_returns) / mean(abs(daily_returns))
    """
    if len(closes) < period + 1:
        return None
    
    # Daily returns
    returns = np.diff(closes) / closes[:-1]
    
    if len(returns) < period:
        return None
    
    # Use most recent 'period' returns
    window = returns[-period:]
    
    ma = np.mean(window)
    mad = np.mean(np.abs(window))
    
    if mad == 0:
        return 0.0
    
    P = ma / mad
    return float(np.clip(P, -1.0, 1.0))


def compute_volatility_trend_from_closes(closes: np.ndarray, period: int = 21) -> Optional[float]:
    """
    Compute V (volatility trend) from an array of closing prices.
    
    V = mad_recent - mad_prior
    """
    if len(closes) < period * 2 + 1:
        return None
    
    returns = np.diff(closes) / closes[:-1]
    abs_returns = np.abs(returns)
    
    if len(abs_returns) < period * 2:
        return None
    
    mad_recent = np.mean(abs_returns[-period:])
    mad_prior = np.mean(abs_returns[-period*2:-period])
    
    return float(mad_recent - mad_prior)


async def fetch_historical_closes(
    fetcher: DataFetcher,
    symbol: str,
    days: int = 60
) -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV data for a symbol."""
    try:
        from_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y-%m-%d')
        to_date = datetime.now().strftime('%Y-%m-%d')
        
        bars = await fetcher.get_aggregates(
            symbol,
            timespan='day',
            multiplier=1,
            from_date=from_date,
            to_date=to_date
        )
        
        if bars.empty:
            return None
        
        return bars
    except Exception as e:
        print(f"  Error fetching data for {symbol}: {e}")
        return None


async def compute_gamma_for_date(
    fetcher: DataFetcher,
    symbol: str,
    spot_price: float
) -> Optional[float]:
    """Compute gamma ratio for a symbol at current snapshot."""
    try:
        contracts = await fetcher.get_option_chain_snapshot(symbol)
        if not contracts:
            return None
        
        standardized = transform_polygon_snapshot(contracts)
        if not standardized:
            return None
        
        gamma_data = compute_gamma_ratio(
            options_chain=standardized,
            spot=spot_price,
            r=0.0,
            v=0.20,
            min_open_interest=100,
            max_otm_pct=0.20
        )
        
        return gamma_data['G']
    except Exception as e:
        return None


async def run_backtest(
    symbols: List[str],
    lookback_days: int = 10
) -> BacktestResults:
    """
    Run the Four Axes backtest.
    
    For each symbol:
    1. Fetch 60 days of historical data (need 42+ for P/V calculation)
    2. Calculate P and V for each of the last 10 trading days
    3. Fetch current G (gamma ratio) - note: historical G not available via Polygon
    4. Generate hypothetical signals based on extreme G values
    5. Measure next-day returns
    """
    results = BacktestResults()
    
    print("=" * 70)
    print("FOUR AXES FRAMEWORK BACKTEST")
    print("=" * 70)
    print(f"\nTest Period: Last {lookback_days} trading days")
    print(f"Symbols: {len(symbols)}")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("-" * 70)
    
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    
    try:
        all_snapshots: List[DailySnapshot] = []
        
        for i, symbol in enumerate(symbols):
            print(f"\n[{i+1}/{len(symbols)}] Processing {symbol}...")
            
            # Fetch historical data
            bars = await fetch_historical_closes(fetcher, symbol, days=60)
            if bars is None or len(bars) < 45:
                print(f"  Insufficient data for {symbol}")
                continue
            
            closes = bars['close'].to_numpy(dtype=float)
            dates = bars['timestamp'].tolist() if 'timestamp' in bars.columns else list(range(len(bars)))
            
            # Fetch current gamma ratio (live snapshot)
            current_price = closes[-1]
            G = await compute_gamma_for_date(fetcher, symbol, current_price)
            if G is None:
                print(f"  Could not fetch gamma for {symbol}")
                G = 0.5  # Default to neutral if unavailable
            
            print(f"  Current G: {G:.3f}")
            
            # Calculate P and V for each of the last N trading days
            for day_offset in range(lookback_days):
                idx = len(closes) - 1 - day_offset
                if idx < 45:  # Need enough history for P/V
                    continue
                
                # Use closes up to this day
                closes_to_date = closes[:idx + 1]
                
                P = compute_price_trend_from_closes(closes_to_date, period=21)
                V = compute_volatility_trend_from_closes(closes_to_date, period=21)
                
                if P is None:
                    continue
                if V is None:
                    V = 0.0
                
                close_price = closes[idx]
                
                # Calculate next-day return (if available)
                next_day_return = None
                if idx + 1 < len(closes):
                    next_day_return = (closes[idx + 1] - closes[idx]) / closes[idx] * 100
                
                # Get date
                if hasattr(dates[idx], 'strftime'):
                    date = dates[idx]
                else:
                    date = datetime.now() - timedelta(days=day_offset)
                
                snapshot = DailySnapshot(
                    symbol=symbol,
                    date=date,
                    P=P,
                    V=V,
                    G=G,  # Using current G as proxy (historical G not available)
                    close=close_price,
                    next_day_return=next_day_return
                )
                
                all_snapshots.append(snapshot)
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.2)
        
        results.daily_snapshots = all_snapshots
        
        # Generate hypothetical signals and measure performance
        print("\n" + "-" * 70)
        print("GENERATING HYPOTHETICAL SIGNALS")
        print("-" * 70)
        
        for snapshot in all_snapshots:
            if snapshot.next_day_return is None:
                continue
            
            # Generate CALL signal if G is call-driven (> 0.6)
            if snapshot.G > 0.6:
                ctx = MarketContext(
                    symbol=snapshot.symbol,
                    P=snapshot.P,
                    V=snapshot.V,
                    G=snapshot.G
                )
                
                should_take, reason = should_take_signal("CALL", ctx)
                
                # A CALL is profitable if next day was up
                profitable = snapshot.next_day_return > 0
                
                signal = SignalResult(
                    symbol=snapshot.symbol,
                    date=snapshot.date,
                    signal_type="CALL",
                    P=snapshot.P,
                    V=snapshot.V,
                    G=snapshot.G,
                    regime=snapshot.regime,
                    aligned=should_take and snapshot.P > 0,
                    conviction_mult=ctx.conviction_multiplier,
                    entry_price=snapshot.close,
                    next_day_return=snapshot.next_day_return,
                    profitable=profitable
                )
                
                results.signal_results.append(signal)
                results.total_signals += 1
                
                if signal.aligned:
                    results.aligned_signals += 1
                    if profitable:
                        results.aligned_wins += 1
                    else:
                        results.aligned_losses += 1
                else:
                    results.misaligned_signals += 1
                    if profitable:
                        results.misaligned_wins += 1
                    else:
                        results.misaligned_losses += 1
            
            # Generate PUT signal if G is put-driven (< 0.4)
            elif snapshot.G < 0.4:
                ctx = MarketContext(
                    symbol=snapshot.symbol,
                    P=snapshot.P,
                    V=snapshot.V,
                    G=snapshot.G
                )
                
                should_take, reason = should_take_signal("PUT", ctx)
                
                # A PUT is profitable if next day was down
                profitable = snapshot.next_day_return < 0
                
                signal = SignalResult(
                    symbol=snapshot.symbol,
                    date=snapshot.date,
                    signal_type="PUT",
                    P=snapshot.P,
                    V=snapshot.V,
                    G=snapshot.G,
                    regime=snapshot.regime,
                    aligned=should_take and snapshot.P < 0,
                    conviction_mult=ctx.conviction_multiplier,
                    entry_price=snapshot.close,
                    next_day_return=snapshot.next_day_return,
                    profitable=profitable
                )
                
                results.signal_results.append(signal)
                results.total_signals += 1
                
                if signal.aligned:
                    results.aligned_signals += 1
                    if profitable:
                        results.aligned_wins += 1
                    else:
                        results.aligned_losses += 1
                else:
                    results.misaligned_signals += 1
                    if profitable:
                        results.misaligned_wins += 1
                    else:
                        results.misaligned_losses += 1
        
        # Calculate average returns
        aligned_returns = [s.next_day_return for s in results.signal_results if s.aligned]
        misaligned_returns = [s.next_day_return for s in results.signal_results if not s.aligned]
        
        if aligned_returns:
            # For CALL signals, return is positive if stock went up
            # For PUT signals, return is positive if stock went down (flip sign)
            adjusted_aligned = []
            for s in results.signal_results:
                if s.aligned:
                    if s.signal_type == "PUT":
                        adjusted_aligned.append(-s.next_day_return)
                    else:
                        adjusted_aligned.append(s.next_day_return)
            results.aligned_avg_return = np.mean(adjusted_aligned) if adjusted_aligned else 0.0
        
        if misaligned_returns:
            adjusted_misaligned = []
            for s in results.signal_results:
                if not s.aligned:
                    if s.signal_type == "PUT":
                        adjusted_misaligned.append(-s.next_day_return)
                    else:
                        adjusted_misaligned.append(s.next_day_return)
            results.misaligned_avg_return = np.mean(adjusted_misaligned) if adjusted_misaligned else 0.0
        
    finally:
        await fetcher.close()
    
    return results


def print_results(results: BacktestResults):
    """Print formatted backtest results."""
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    
    print(f"\nTotal Daily Snapshots: {len(results.daily_snapshots)}")
    print(f"Total Signals Generated: {results.total_signals}")
    
    print("\n--- SIGNAL BREAKDOWN ---")
    print(f"Aligned Signals:    {results.aligned_signals}")
    print(f"Misaligned Signals: {results.misaligned_signals}")
    
    print("\n--- WIN RATES ---")
    print(f"Aligned Win Rate:    {results.aligned_win_rate:.1%} ({results.aligned_wins}W / {results.aligned_losses}L)")
    print(f"Misaligned Win Rate: {results.misaligned_win_rate:.1%} ({results.misaligned_wins}W / {results.misaligned_losses}L)")
    
    print("\n--- AVERAGE RETURNS (Direction-Adjusted) ---")
    print(f"Aligned Avg Return:    {results.aligned_avg_return:+.2f}%")
    print(f"Misaligned Avg Return: {results.misaligned_avg_return:+.2f}%")
    
    improvement = results.aligned_win_rate - results.misaligned_win_rate
    print(f"\n📊 ALIGNMENT EDGE: {improvement:+.1%}")
    
    if improvement > 0:
        print("✅ Four Axes alignment IMPROVES signal quality")
    elif improvement < 0:
        print("⚠️ Four Axes alignment did NOT improve signals in this period")
    else:
        print("➖ No difference observed")
    
    # Print sample signals
    print("\n--- SAMPLE SIGNALS ---")
    print(f"{'Symbol':<8} {'Type':<6} {'P':>6} {'G':>6} {'Aligned':>8} {'Return':>8} {'Result':>8}")
    print("-" * 60)
    
    for signal in results.signal_results[:20]:
        result_emoji = "✅" if signal.profitable else "❌"
        aligned_str = "Yes" if signal.aligned else "No"
        print(
            f"{signal.symbol:<8} {signal.signal_type:<6} {signal.P:>+6.2f} {signal.G:>6.2f} "
            f"{aligned_str:>8} {signal.next_day_return:>+7.2f}% {result_emoji:>8}"
        )
    
    if len(results.signal_results) > 20:
        print(f"... and {len(results.signal_results) - 20} more signals")
    
    # Regime distribution
    print("\n--- REGIME DISTRIBUTION ---")
    regimes = {}
    for snapshot in results.daily_snapshots:
        regimes[snapshot.regime] = regimes.get(snapshot.regime, 0) + 1
    
    for regime, count in sorted(regimes.items(), key=lambda x: -x[1]):
        pct = count / len(results.daily_snapshots) * 100
        print(f"  {regime:<25} {count:>4} ({pct:>5.1f}%)")
    
    # P distribution
    print("\n--- PRICE TREND (P) DISTRIBUTION ---")
    p_values = [s.P for s in results.daily_snapshots]
    print(f"  Min: {min(p_values):+.3f}")
    print(f"  Max: {max(p_values):+.3f}")
    print(f"  Mean: {np.mean(p_values):+.3f}")
    print(f"  Std: {np.std(p_values):.3f}")
    
    bullish = sum(1 for p in p_values if p > 0.2)
    bearish = sum(1 for p in p_values if p < -0.2)
    neutral = len(p_values) - bullish - bearish
    print(f"  Bullish (P > 0.2): {bullish} ({bullish/len(p_values)*100:.1f}%)")
    print(f"  Bearish (P < -0.2): {bearish} ({bearish/len(p_values)*100:.1f}%)")
    print(f"  Neutral: {neutral} ({neutral/len(p_values)*100:.1f}%)")
    
    # Save to CSV
    print("\n--- SAVING RESULTS ---")
    
    # Save snapshots
    snapshots_df = pd.DataFrame([
        {
            'symbol': s.symbol,
            'date': s.date,
            'P': s.P,
            'V': s.V,
            'G': s.G,
            'close': s.close,
            'next_day_return': s.next_day_return,
            'regime': s.regime
        }
        for s in results.daily_snapshots
    ])
    
    reports_dir = Path(__file__).parent.parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    snapshots_path = reports_dir / "four_axes_snapshots.csv"
    snapshots_df.to_csv(snapshots_path, index=False)
    print(f"  Snapshots saved to: {snapshots_path}")
    
    # Save signals
    if results.signal_results:
        signals_df = pd.DataFrame([
            {
                'symbol': s.symbol,
                'date': s.date,
                'signal_type': s.signal_type,
                'P': s.P,
                'V': s.V,
                'G': s.G,
                'regime': s.regime,
                'aligned': s.aligned,
                'conviction_mult': s.conviction_mult,
                'entry_price': s.entry_price,
                'next_day_return': s.next_day_return,
                'profitable': s.profitable
            }
            for s in results.signal_results
        ])
        
        signals_path = reports_dir / "four_axes_signals.csv"
        signals_df.to_csv(signals_path, index=False)
        print(f"  Signals saved to: {signals_path}")
    
    print("\n" + "=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)


async def main():
    """Main entry point."""
    print("\n🔬 Starting Four Axes Framework Backtest...\n")
    
    results = await run_backtest(
        symbols=TEST_SYMBOLS,
        lookback_days=10
    )
    
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())

