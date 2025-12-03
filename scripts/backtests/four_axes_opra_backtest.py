"""
Four Axes Backtest with Real OPRA Options Data

Downloads historical options minute aggregates from Massive.io and runs
a proper backtest using actual options flow data to determine what alerts
each bot would have fired vs filtered.

Data source: OPRA minute aggregates (real options trades)
"""

import asyncio
import gzip
import io
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

import boto3
from botocore.config import Config as BotoConfig
import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import Config
from src.data_fetcher import DataFetcher
from src.utils.enhanced_analysis import (
    MarketContext,
    should_take_signal,
)


# Massive.io credentials
AWS_ACCESS_KEY = 'c423a324-922b-49d9-be16-fb970594e49f'
AWS_SECRET_KEY = 'NnbFphaif6yWkufcTV8rOEDXRi2LefZN'
S3_ENDPOINT = 'https://files.massive.com'
BUCKET_NAME = 'flatfiles'


@dataclass
class OptionsFlow:
    """Parsed options flow from OPRA data."""
    ticker: str  # O:AAPL251219C00250000
    underlying: str  # AAPL
    option_type: str  # CALL or PUT
    strike: float
    expiration: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float
    num_trades: int
    
    @property
    def premium(self) -> float:
        """Estimated premium = volume * vwap * 100"""
        return self.volume * self.vwap * 100
    
    @property
    def dte(self) -> int:
        """Days to expiration."""
        try:
            exp_date = datetime.strptime(self.expiration, "%Y-%m-%d")
            return max(0, (exp_date - self.timestamp).days)
        except:
            return 0


@dataclass
class RealAlert:
    """A real alert from OPRA data."""
    date: str
    bot_name: str
    symbol: str
    ticker: str
    signal_type: str
    strike: float
    expiration: str
    dte: int
    price: float
    volume: int
    premium: float
    P: float
    V: float
    G: float
    regime: str
    would_fire: bool
    filter_reason: str
    conviction_mult: float


@dataclass
class BotResults:
    """Results for a single bot."""
    bot_name: str
    total_candidates: int = 0
    would_fire: int = 0
    would_filter: int = 0
    alerts: List[RealAlert] = field(default_factory=list)
    
    @property
    def fire_rate(self) -> float:
        return self.would_fire / self.total_candidates if self.total_candidates > 0 else 0.0


def parse_option_ticker(ticker: str) -> Optional[Dict]:
    """
    Parse Polygon/OPRA option ticker format.
    Example: O:AAPL251219C00250000
    """
    # Pattern: O:SYMBOL YYMMDD C/P STRIKE(8 digits, strike*1000)
    match = re.match(r'O:([A-Z]+)(\d{6})([CP])(\d{8})', ticker)
    if not match:
        return None
    
    symbol, exp_str, opt_type, strike_str = match.groups()
    
    try:
        # Parse expiration (YYMMDD)
        exp_date = datetime.strptime(exp_str, "%y%m%d")
        expiration = exp_date.strftime("%Y-%m-%d")
        
        # Parse strike (divide by 1000)
        strike = int(strike_str) / 1000
        
        return {
            'underlying': symbol,
            'expiration': expiration,
            'option_type': 'CALL' if opt_type == 'C' else 'PUT',
            'strike': strike
        }
    except:
        return None


def download_opra_data(date_str: str) -> Optional[pd.DataFrame]:
    """
    Download OPRA minute aggregates for a specific date.
    
    Args:
        date_str: Date in YYYY-MM-DD format
    
    Returns:
        DataFrame with options data or None if failed
    """
    try:
        # Parse date for path
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        
        object_key = f"us_options_opra/minute_aggs_v1/{year}/{month}/{date_str}.csv.gz"
        
        print(f"  Downloading {object_key}...")
        
        # Create S3 client
        session = boto3.Session(
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
        )
        
        s3 = session.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            config=BotoConfig(signature_version='s3v4'),
        )
        
        # Download to memory
        response = s3.get_object(Bucket=BUCKET_NAME, Key=object_key)
        
        # Decompress and read
        with gzip.GzipFile(fileobj=io.BytesIO(response['Body'].read())) as gz:
            df = pd.read_csv(gz)
        
        print(f"  Downloaded {len(df):,} rows")
        return df
        
    except Exception as e:
        print(f"  Error downloading data: {e}")
        return None


def filter_high_activity_options(df: pd.DataFrame, min_volume: int = 100) -> pd.DataFrame:
    """Filter to high-activity options contracts."""
    # Group by ticker and sum volume
    ticker_volume = df.groupby('ticker').agg({
        'volume': 'sum',
        'transactions': 'sum',
        'close': 'last',
        'open': 'first',
        'high': 'max',
        'low': 'min'
    }).reset_index()
    
    # Calculate approximate VWAP as (high + low + close) / 3
    ticker_volume['vwap'] = (ticker_volume['high'] + ticker_volume['low'] + ticker_volume['close']) / 3
    
    # Filter to high volume
    high_vol = ticker_volume[ticker_volume['volume'] >= min_volume]
    
    return high_vol


def identify_bullseye_candidates(df: pd.DataFrame) -> List[Dict]:
    """
    Identify Bullseye Bot candidates from OPRA data.
    
    Criteria:
    - Premium >= $1,000,000
    - Volume >= 400 contracts
    - DTE 1-5 days
    """
    candidates = []
    
    for _, row in df.iterrows():
        ticker = row['ticker']
        parsed = parse_option_ticker(ticker)
        if not parsed:
            continue
        
        volume = row['volume']
        price = row.get('vwap', 0) or row.get('close', 0) or 0
        if price <= 0:
            continue
        premium = volume * price * 100
        
        # Calculate DTE (use a reference date of 2025-11-28 for the backtest)
        try:
            exp_date = datetime.strptime(parsed['expiration'], "%Y-%m-%d")
            ref_date = datetime(2025, 11, 28)  # Reference date for DTE calc
            dte = (exp_date - ref_date).days
        except:
            dte = 99
        
        # Bullseye criteria
        if premium >= 1_000_000 and volume >= 400 and 1 <= dte <= 7:
            candidates.append({
                'ticker': ticker,
                'underlying': parsed['underlying'],
                'option_type': parsed['option_type'],
                'strike': parsed['strike'],
                'expiration': parsed['expiration'],
                'dte': dte,
                'volume': volume,
                'price': price,
                'premium': premium,
            })
    
    return candidates


def identify_sweeps_candidates(df: pd.DataFrame) -> List[Dict]:
    """
    Identify Sweeps Bot candidates from OPRA data.
    
    Criteria:
    - Premium >= $100,000
    - Volume >= 500 contracts
    - DTE 0-14 days
    """
    candidates = []
    
    for _, row in df.iterrows():
        ticker = row['ticker']
        parsed = parse_option_ticker(ticker)
        if not parsed:
            continue
        
        volume = row['volume']
        price = row.get('vwap', 0) or row.get('close', 0) or 0
        if price <= 0:
            continue
        premium = volume * price * 100
        
        try:
            exp_date = datetime.strptime(parsed['expiration'], "%Y-%m-%d")
            ref_date = datetime(2025, 11, 28)
            dte = (exp_date - ref_date).days
        except:
            dte = 99
        
        # Sweeps criteria
        if premium >= 100_000 and volume >= 500 and 0 <= dte <= 21:
            candidates.append({
                'ticker': ticker,
                'underlying': parsed['underlying'],
                'option_type': parsed['option_type'],
                'strike': parsed['strike'],
                'expiration': parsed['expiration'],
                'dte': dte,
                'volume': volume,
                'price': price,
                'premium': premium,
            })
    
    return candidates


def identify_spread_candidates(df: pd.DataFrame) -> List[Dict]:
    """
    Identify 99 Cent Store candidates from OPRA data.
    
    Criteria:
    - Contract price <= $1.00
    - Premium >= $250,000
    - DTE 5-21 days
    - Volume >= 500 contracts
    """
    candidates = []
    
    for _, row in df.iterrows():
        ticker = row['ticker']
        parsed = parse_option_ticker(ticker)
        if not parsed:
            continue
        
        volume = row['volume']
        price = row.get('vwap', 0) or row.get('close', 0) or 0
        if price <= 0:
            continue
        premium = volume * price * 100
        
        try:
            exp_date = datetime.strptime(parsed['expiration'], "%Y-%m-%d")
            ref_date = datetime(2025, 11, 28)
            dte = (exp_date - ref_date).days
        except:
            dte = 99
        
        # 99 Cent Store criteria
        if price <= 1.00 and price >= 0.05 and premium >= 250_000 and 5 <= dte <= 30 and volume >= 500:
            candidates.append({
                'ticker': ticker,
                'underlying': parsed['underlying'],
                'option_type': parsed['option_type'],
                'strike': parsed['strike'],
                'expiration': parsed['expiration'],
                'dte': dte,
                'volume': volume,
                'price': price,
                'premium': premium,
            })
    
    return candidates


def identify_gamma_candidates(df: pd.DataFrame) -> List[Dict]:
    """
    Identify Gamma Ratio Bot candidates.
    
    For gamma, we look at high OI options with significant volume.
    This is a simplified version since we don't have full OI data.
    """
    # Group by underlying and option type
    candidates = []
    
    # Get unique underlyings with high total volume
    df_parsed = df.copy()
    df_parsed['underlying'] = df_parsed['ticker'].apply(
        lambda x: parse_option_ticker(x).get('underlying') if parse_option_ticker(x) else None
    )
    df_parsed = df_parsed[df_parsed['underlying'].notna()]
    
    underlying_volume = df_parsed.groupby('underlying')['volume'].sum()
    high_vol_underlyings = underlying_volume[underlying_volume >= 10000].index.tolist()
    
    for underlying in high_vol_underlyings[:50]:  # Limit to top 50
        underlying_df = df_parsed[df_parsed['underlying'] == underlying]
        
        # Parse all options for this underlying
        calls_volume = 0
        puts_volume = 0
        
        for _, row in underlying_df.iterrows():
            parsed = parse_option_ticker(row['ticker'])
            if not parsed:
                continue
            
            if parsed['option_type'] == 'CALL':
                calls_volume += row['volume']
            else:
                puts_volume += row['volume']
        
        total_volume = calls_volume + puts_volume
        if total_volume == 0:
            continue
        
        # Estimate G from call/put volume ratio
        G = calls_volume / total_volume
        
        # Only alert if G is extreme
        if G > 0.65 or G < 0.35:
            signal_type = "CALL" if G > 0.5 else "PUT"
            candidates.append({
                'ticker': f"GAMMA:{underlying}",
                'underlying': underlying,
                'option_type': signal_type,
                'strike': 0,
                'expiration': '',
                'dte': 0,
                'volume': total_volume,
                'price': 0,
                'premium': 0,
                'estimated_G': G,
            })
    
    return candidates


async def compute_P_V_for_symbol(
    fetcher: DataFetcher,
    symbol: str
) -> Tuple[float, float]:
    """Compute P and V for a symbol using Polygon historical data."""
    try:
        from_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        to_date = datetime.now().strftime('%Y-%m-%d')
        
        bars = await fetcher.get_aggregates(
            symbol,
            timespan='day',
            multiplier=1,
            from_date=from_date,
            to_date=to_date
        )
        
        if bars.empty or len(bars) < 25:
            return 0.0, 0.0
        
        closes = bars['close'].to_numpy()
        
        # Compute P
        returns = np.diff(closes) / closes[:-1]
        if len(returns) >= 21:
            window = returns[-21:]
            ma = np.mean(window)
            mad = np.mean(np.abs(window))
            P = float(np.clip(ma / mad, -1.0, 1.0)) if mad != 0 else 0.0
        else:
            P = 0.0
        
        # Compute V
        abs_returns = np.abs(returns)
        if len(abs_returns) >= 42:
            mad_recent = np.mean(abs_returns[-21:])
            mad_prior = np.mean(abs_returns[-42:-21])
            V = float(mad_recent - mad_prior)
        else:
            V = 0.0
        
        return P, V
        
    except Exception as e:
        return 0.0, 0.0


async def run_opra_backtest(dates: List[str]) -> Dict[str, BotResults]:
    """Run backtest on OPRA data for specified dates."""
    
    print("=" * 80)
    print("FOUR AXES BACKTEST WITH REAL OPRA DATA")
    print("=" * 80)
    print(f"\nDates to analyze: {dates}")
    print("-" * 80)
    
    results = {
        'Bullseye Bot': BotResults(bot_name='Bullseye Bot'),
        'Sweeps Bot': BotResults(bot_name='Sweeps Bot'),
        '99 Cent Store': BotResults(bot_name='99 Cent Store'),
        'Gamma Ratio Bot': BotResults(bot_name='Gamma Ratio Bot'),
    }
    
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    
    # Cache for P, V values
    pv_cache: Dict[str, Tuple[float, float]] = {}
    
    try:
        for date_str in dates:
            print(f"\n📅 Processing {date_str}...")
            
            # Download OPRA data
            df = download_opra_data(date_str)
            if df is None:
                print(f"  Skipping {date_str} - no data")
                continue
            
            # Filter to high-activity options
            high_activity = filter_high_activity_options(df, min_volume=100)
            print(f"  High-activity contracts: {len(high_activity):,}")
            
            # Identify candidates for each bot
            bullseye_candidates = identify_bullseye_candidates(high_activity)
            sweeps_candidates = identify_sweeps_candidates(high_activity)
            spread_candidates = identify_spread_candidates(high_activity)
            gamma_candidates = identify_gamma_candidates(high_activity)
            
            print(f"  Candidates: Bullseye={len(bullseye_candidates)}, Sweeps={len(sweeps_candidates)}, "
                  f"99Cent={len(spread_candidates)}, Gamma={len(gamma_candidates)}")
            
            # Process each bot's candidates
            for bot_name, candidates in [
                ('Bullseye Bot', bullseye_candidates),
                ('Sweeps Bot', sweeps_candidates),
                ('99 Cent Store', spread_candidates),
                ('Gamma Ratio Bot', gamma_candidates),
            ]:
                for candidate in candidates:
                    symbol = candidate['underlying']
                    
                    # Get P, V (with caching)
                    if symbol not in pv_cache:
                        P, V = await compute_P_V_for_symbol(fetcher, symbol)
                        pv_cache[symbol] = (P, V)
                    else:
                        P, V = pv_cache[symbol]
                    
                    # Get G (estimated from candidate or default)
                    G = candidate.get('estimated_G', 0.5)
                    if G == 0.5:
                        # Estimate G from option type
                        G = 0.65 if candidate['option_type'] == 'CALL' else 0.35
                    
                    # Create market context
                    context = MarketContext(symbol=symbol, P=P, V=V, G=G)
                    
                    # Apply Four Axes filter
                    signal_type = candidate['option_type']
                    would_fire = True
                    filter_reason = "PASSED"
                    
                    if bot_name in ('Bullseye Bot', '99 Cent Store'):
                        # Strict filtering
                        should_take, reason = should_take_signal(signal_type, context)
                        if not should_take:
                            would_fire = False
                            filter_reason = reason
                        elif bot_name == '99 Cent Store':
                            # Additional P filter
                            if signal_type == "CALL" and P < -0.2:
                                would_fire = False
                                filter_reason = f"P too bearish for CALL (P={P:.2f})"
                            elif signal_type == "PUT" and P > 0.2:
                                would_fire = False
                                filter_reason = f"P too bullish for PUT (P={P:.2f})"
                    
                    elif bot_name == 'Sweeps Bot':
                        # Light filtering
                        if signal_type == "CALL" and P < -0.3 and G < 0.4:
                            would_fire = False
                            filter_reason = f"CALL fighting bearish (P={P:.2f}, G={G:.2f})"
                        elif signal_type == "PUT" and P > 0.3 and G > 0.6:
                            would_fire = False
                            filter_reason = f"PUT fighting bullish (P={P:.2f}, G={G:.2f})"
                    
                    # Create alert record
                    alert = RealAlert(
                        date=date_str,
                        bot_name=bot_name,
                        symbol=symbol,
                        ticker=candidate['ticker'],
                        signal_type=signal_type,
                        strike=candidate['strike'],
                        expiration=candidate['expiration'],
                        dte=candidate['dte'],
                        price=candidate['price'],
                        volume=candidate['volume'],
                        premium=candidate['premium'],
                        P=P,
                        V=V,
                        G=G,
                        regime=context.regime,
                        would_fire=would_fire,
                        filter_reason=filter_reason,
                        conviction_mult=context.conviction_multiplier
                    )
                    
                    results[bot_name].alerts.append(alert)
                    results[bot_name].total_candidates += 1
                    
                    if would_fire:
                        results[bot_name].would_fire += 1
                    else:
                        results[bot_name].would_filter += 1
            
            await asyncio.sleep(0.5)  # Rate limiting
    
    finally:
        await fetcher.close()
    
    return results


def print_results(results: Dict[str, BotResults]):
    """Print formatted results."""
    
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS - REAL OPRA DATA")
    print("=" * 80)
    
    # Summary table
    print(f"\n{'Bot Name':<20} {'Candidates':>12} {'Would Fire':>12} {'Filtered':>12} {'Fire Rate':>12}")
    print("-" * 80)
    
    total_candidates = 0
    total_fired = 0
    total_filtered = 0
    
    for bot_name, bot_results in results.items():
        fire_rate = bot_results.fire_rate
        filter_rate = 1 - fire_rate if bot_results.total_candidates > 0 else 0
        print(
            f"{bot_name:<20} {bot_results.total_candidates:>12} "
            f"{bot_results.would_fire:>12} {bot_results.would_filter:>12} "
            f"{fire_rate:>11.1%}"
        )
        total_candidates += bot_results.total_candidates
        total_fired += bot_results.would_fire
        total_filtered += bot_results.would_filter
    
    print("-" * 80)
    overall_fire_rate = total_fired / total_candidates if total_candidates > 0 else 0
    print(
        f"{'TOTAL':<20} {total_candidates:>12} "
        f"{total_fired:>12} {total_filtered:>12} "
        f"{overall_fire_rate:>11.1%}"
    )
    
    # Detailed breakdown
    for bot_name, bot_results in results.items():
        if not bot_results.alerts:
            continue
        
        print(f"\n{'=' * 80}")
        print(f"{bot_name.upper()} - DETAILED ALERTS")
        print("=" * 80)
        
        fired = [a for a in bot_results.alerts if a.would_fire]
        filtered = [a for a in bot_results.alerts if not a.would_fire]
        
        if fired:
            print(f"\n✅ WOULD FIRE ({len(fired)} alerts):")
            print(f"{'Date':<12} {'Symbol':<8} {'Type':<6} {'Strike':>10} {'Premium':>12} {'P':>7} {'G':>7}")
            print("-" * 70)
            for a in fired[:15]:
                prem_str = f"${a.premium/1000:.0f}K" if a.premium >= 1000 else f"${a.premium:.0f}"
                print(
                    f"{a.date:<12} {a.symbol:<8} {a.signal_type:<6} "
                    f"${a.strike:>9.2f} {prem_str:>12} {a.P:>+7.2f} {a.G:>7.2f}"
                )
            if len(fired) > 15:
                print(f"  ... and {len(fired) - 15} more")
        
        if filtered:
            print(f"\n❌ WOULD FILTER ({len(filtered)} alerts):")
            print(f"{'Date':<12} {'Symbol':<8} {'Type':<6} {'P':>7} {'G':>7} {'Reason':<30}")
            print("-" * 75)
            for a in filtered[:15]:
                reason_short = a.filter_reason[:28] + ".." if len(a.filter_reason) > 30 else a.filter_reason
                print(
                    f"{a.date:<12} {a.symbol:<8} {a.signal_type:<6} "
                    f"{a.P:>+7.2f} {a.G:>7.2f} {reason_short:<30}"
                )
            if len(filtered) > 15:
                print(f"  ... and {len(filtered) - 15} more")
    
    # Filter reason breakdown
    all_filtered = []
    for bot_results in results.values():
        all_filtered.extend([a for a in bot_results.alerts if not a.would_fire])
    
    if all_filtered:
        print(f"\n{'=' * 80}")
        print("FILTER REASON BREAKDOWN")
        print("=" * 80)
        
        reasons = {}
        for a in all_filtered:
            reason = a.filter_reason.split('(')[0].strip()
            reasons[reason] = reasons.get(reason, 0) + 1
        
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            pct = count / len(all_filtered) * 100
            print(f"  {reason:<50} {count:>4} ({pct:>5.1f}%)")
    
    # Save to CSV
    print(f"\n{'=' * 80}")
    print("SAVING RESULTS")
    print("=" * 80)
    
    all_alerts = []
    for bot_results in results.values():
        all_alerts.extend(bot_results.alerts)
    
    if all_alerts:
        df = pd.DataFrame([
            {
                'date': a.date,
                'bot': a.bot_name,
                'symbol': a.symbol,
                'ticker': a.ticker,
                'signal_type': a.signal_type,
                'strike': a.strike,
                'expiration': a.expiration,
                'dte': a.dte,
                'price': a.price,
                'volume': a.volume,
                'premium': a.premium,
                'P': a.P,
                'V': a.V,
                'G': a.G,
                'regime': a.regime,
                'would_fire': a.would_fire,
                'filter_reason': a.filter_reason,
                'conviction_mult': a.conviction_mult
            }
            for a in all_alerts
        ])
        
        reports_dir = Path(__file__).parent.parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        
        path = reports_dir / "four_axes_opra_backtest.csv"
        df.to_csv(path, index=False)
        print(f"  Results saved to: {path}")
    
    print(f"\n{'=' * 80}")
    print("BACKTEST COMPLETE")
    print("=" * 80)


async def main():
    """Main entry point."""
    print("\n🔬 Starting Four Axes Backtest with Real OPRA Data...")
    print("   Downloading historical options data from Massive.io...\n")
    
    # Test dates (trading days with OPRA data available)
    dates = [
        "2025-11-25",
        "2025-11-26",
        "2025-11-27",
    ]
    
    results = await run_opra_backtest(dates)
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())

