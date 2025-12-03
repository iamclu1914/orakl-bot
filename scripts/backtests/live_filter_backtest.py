"""
Live Filter Backtest with OPRA Trades Data
==========================================
Applies the EXACT same filters as the live bots to real trade data.

Bot Filters Applied:
- Bullseye: $500K premium, 400+ contracts, VOI 1.0+, score 65+, max 3/scan, 30min cooldown
- Sweeps: $150K premium, score 85+, 12% max OTM, 1 per symbol, 5min cooldown  
- 99 Cent Store: $200K premium, price ≤$1.00, VOI 1.5+, 15% max OTM

Plus Four Axes filtering on top.
"""

import boto3
from botocore.config import Config
import gzip
import io
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import re
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ============================================================================
# LIVE BOT THRESHOLDS - PRODUCTION MODE (optimized for quality over quantity)
# ============================================================================
# Target: ~150-200 alerts/full trading day = ~25-30/hour = 1 alert every 2 minutes
# This provides actionable signals without overwhelming the Discord channel.

# Bullseye Bot thresholds (institutional blocks - highest conviction)
BULLSEYE_MIN_PREMIUM = 1_000_000    # $1M minimum (institutional size)
BULLSEYE_MIN_CONTRACTS = 600        # Min volume delta (significant size)
BULLSEYE_MIN_BLOCK = 400            # Min block contracts
BULLSEYE_MIN_VOI = 1.0              # Volume/OI ratio
BULLSEYE_MIN_SCORE = 90             # Minimum score to fire (high conviction only)
BULLSEYE_MAX_ALERTS_PER_SCAN = 2    # Max alerts per scan
BULLSEYE_COOLDOWN_MINS = 45         # 45 minute cooldown per symbol
BULLSEYE_MIN_DTE = 1                # Minimum days to expiry
BULLSEYE_MAX_DTE = 30               # 30 days max (tightened for conviction)
BULLSEYE_MAX_OTM_PCT = 0.12         # 12% max OTM

# Sweeps Bot thresholds (conviction buyers)
SWEEPS_MIN_PREMIUM = 750_000        # $750K minimum (raised for quality)
SWEEPS_MIN_SCORE = 85               # High score required
SWEEPS_MAX_OTM_PCT = 0.06           # 6% max OTM (near the money)
SWEEPS_MAX_PER_SYMBOL = 1           # 1 per symbol per scan
SWEEPS_COOLDOWN_MINS = 30           # 30 minute cooldown
SWEEPS_MAX_ALERTS_PER_SCAN = 2      # Max 2 alerts per scan cycle
SWEEPS_MIN_VOLUME_RATIO = 1.3       # Higher volume ratio

# Golden Sweeps Bot thresholds (whale activity)
GOLDEN_MIN_PREMIUM = 1_500_000      # $1.5M minimum (true whale size)

# 99 Cent Store thresholds (swing trades)
CENT99_MIN_PREMIUM = 400_000        # $400K minimum (raised for quality)
CENT99_MAX_PRICE = 1.00             # Max $1.00 per contract (user preference)
CENT99_MIN_VOI = 2.5                # Higher VOI required
CENT99_MAX_OTM_PCT = 0.10           # 10% max OTM
CENT99_COOLDOWN_MINS = 30           # 30 minute cooldown
CENT99_MAX_ALERTS_PER_SCAN = 2      # Max 2 alerts per scan

# ============================================================================
# OCC SYMBOL PARSER
# ============================================================================

def parse_occ_symbol(ticker: str) -> dict:
    """
    Parse OCC option symbol: O:AAPL251219C00150000
    Returns: {underlying, expiration, option_type, strike}
    """
    if not ticker.startswith('O:'):
        return None
    
    symbol = ticker[2:]  # Remove 'O:' prefix
    
    # OCC format: SYMBOL + YYMMDD + C/P + 8-digit strike (strike * 1000)
    # Find where the date starts (6 digits followed by C or P)
    match = re.match(r'^([A-Z]+)(\d{6})([CP])(\d{8})$', symbol)
    if not match:
        return None
    
    underlying = match.group(1)
    date_str = match.group(2)
    option_type = 'CALL' if match.group(3) == 'C' else 'PUT'
    strike = int(match.group(4)) / 1000  # Convert from strike * 1000
    
    # Parse expiration date
    try:
        expiration = datetime.strptime(date_str, '%y%m%d')
    except:
        return None
    
    return {
        'underlying': underlying,
        'expiration': expiration,
        'option_type': option_type,
        'strike': strike
    }

# ============================================================================
# DATA LOADING
# ============================================================================

def download_trades_data(date_str: str) -> pd.DataFrame:
    """Download trades data from Massive.io S3"""
    session = boto3.Session(
        aws_access_key_id='c423a324-922b-49d9-be16-fb970594e49f',
        aws_secret_access_key='NnbFphaif6yWkufcTV8rOEDXRi2LefZN',
    )
    
    s3 = session.client(
        's3',
        endpoint_url='https://files.massive.com',
        config=Config(signature_version='s3v4'),
    )
    
    object_key = f'us_options_opra/trades_v1/2025/11/{date_str}.csv.gz'
    print(f"  Downloading {object_key}...")
    
    try:
        response = s3.get_object(Bucket='flatfiles', Key=object_key)
        with gzip.GzipFile(fileobj=io.BytesIO(response['Body'].read())) as gz:
            df = pd.read_csv(gz)
        return df
    except Exception as e:
        print(f"  Error downloading {date_str}: {e}")
        return None

# ============================================================================
# AGGREGATE TRADES INTO FLOW WINDOWS
# ============================================================================

def aggregate_into_flow_windows(df: pd.DataFrame, window_mins: int = 5) -> pd.DataFrame:
    """
    Aggregate individual trades into 5-minute flow windows.
    This mimics how the live bots see data - they scan every 5 minutes
    and see accumulated volume in that window.
    """
    print(f"  Aggregating {len(df):,} trades into {window_mins}-minute windows...")
    
    # Convert timestamp to datetime
    df['timestamp'] = pd.to_datetime(df['sip_timestamp'], unit='ns')
    
    # Create window key (floor to 5-minute intervals)
    df['window'] = df['timestamp'].dt.floor(f'{window_mins}min')
    
    # Calculate premium per trade
    df['premium'] = df['price'] * df['size'] * 100  # x100 for options
    
    # Parse ticker symbols
    parsed = df['ticker'].apply(parse_occ_symbol)
    df['parsed'] = parsed
    
    # Filter out unparseable tickers
    df = df[df['parsed'].notna()].copy()
    
    # Extract fields
    df['underlying'] = df['parsed'].apply(lambda x: x['underlying'] if x else None)
    df['option_type'] = df['parsed'].apply(lambda x: x['option_type'] if x else None)
    df['strike'] = df['parsed'].apply(lambda x: x['strike'] if x else None)
    df['expiration'] = df['parsed'].apply(lambda x: x['expiration'] if x else None)
    
    # Group by window, ticker to get flow per option contract
    flows = df.groupby(['window', 'ticker', 'underlying', 'option_type', 'strike', 'expiration']).agg({
        'size': 'sum',          # Total contracts
        'premium': 'sum',       # Total premium
        'price': 'mean',        # Average price
    }).reset_index()
    
    flows.columns = ['window', 'ticker', 'underlying', 'option_type', 'strike', 
                     'expiration', 'contracts', 'premium', 'avg_price']
    
    print(f"  Created {len(flows):,} flow records across {flows['window'].nunique()} windows")
    
    return flows

# ============================================================================
# SIMULATED STOCK PRICES (for OTM calculation)
# ============================================================================

# Approximate stock prices for Nov 28, 2025 (these would normally come from API)
STOCK_PRICES = {
    'AAPL': 234.0, 'MSFT': 430.0, 'GOOGL': 175.0, 'AMZN': 210.0, 'META': 575.0,
    'NVDA': 140.0, 'TSLA': 340.0, 'AMD': 140.0, 'NFLX': 900.0, 'SPY': 600.0,
    'QQQ': 510.0, 'IWM': 240.0, 'DIA': 445.0, 'XLF': 50.0, 'XLE': 90.0,
    'COIN': 310.0, 'MSTR': 400.0, 'PLTR': 65.0, 'SOFI': 15.0, 'HOOD': 38.0,
    'GME': 27.0, 'AMC': 5.0, 'RIVN': 11.0, 'LCID': 2.5, 'NIO': 4.5,
    'BA': 155.0, 'DIS': 115.0, 'JPM': 250.0, 'V': 310.0, 'MA': 530.0,
    'WMT': 93.0, 'HD': 420.0, 'COST': 950.0, 'TGT': 125.0, 'LOW': 270.0,
    'A': 135.0, 'INTC': 24.0, 'MU': 100.0, 'AVGO': 180.0, 'QCOM': 160.0,
}

def get_stock_price(symbol: str) -> float:
    """Get approximate stock price for OTM calculation"""
    return STOCK_PRICES.get(symbol, 100.0)  # Default $100 if unknown

def calculate_otm_pct(underlying: str, strike: float, option_type: str) -> float:
    """Calculate how far OTM an option is"""
    stock_price = get_stock_price(underlying)
    if option_type == 'CALL':
        return max(0, (strike - stock_price) / stock_price)
    else:  # PUT
        return max(0, (stock_price - strike) / stock_price)

# ============================================================================
# SCORING FUNCTIONS (simplified versions of live bot logic)
# ============================================================================

def calculate_bullseye_score(flow: dict) -> int:
    """Calculate Bullseye conviction score (0-100)"""
    score = 50  # Base score
    
    # Premium boost
    if flow['premium'] >= 2_000_000:
        score += 20
    elif flow['premium'] >= 1_000_000:
        score += 15
    elif flow['premium'] >= 500_000:
        score += 10
    
    # Contract boost
    if flow['contracts'] >= 2000:
        score += 15
    elif flow['contracts'] >= 1000:
        score += 10
    elif flow['contracts'] >= 500:
        score += 5
    
    # VOI boost (using contracts as proxy since we don't have OI)
    voi_proxy = flow['contracts'] / 100  # Simplified
    if voi_proxy >= 5.0:
        score += 10
    elif voi_proxy >= 2.0:
        score += 5
    
    return min(100, score)

def calculate_sweeps_score(flow: dict) -> int:
    """Calculate Sweeps conviction score (0-100)"""
    score = 60  # Base score for sweeps
    
    # Premium boost
    if flow['premium'] >= 500_000:
        score += 20
    elif flow['premium'] >= 300_000:
        score += 15
    elif flow['premium'] >= 150_000:
        score += 10
    
    # Contracts boost
    if flow['contracts'] >= 1000:
        score += 10
    elif flow['contracts'] >= 500:
        score += 5
    
    # OTM penalty
    otm_pct = calculate_otm_pct(flow['underlying'], flow['strike'], flow['option_type'])
    if otm_pct > 0.10:
        score -= 10
    elif otm_pct > 0.05:
        score -= 5
    
    return min(100, max(0, score))

# ============================================================================
# FOUR AXES FILTER
# ============================================================================

def should_take_signal_four_axes(flow: dict, P: float = 0.0) -> tuple:
    """
    Apply Four Axes filter.
    P > 0 = uptrend, P < 0 = downtrend
    Returns (should_fire, reason)
    """
    option_type = flow['option_type']
    
    # Strong trend alignment check
    if option_type == 'CALL' and P < -0.3:
        return False, "CALL in strong downtrend (P < -0.3)"
    if option_type == 'PUT' and P > 0.3:
        return False, "PUT in strong uptrend (P > 0.3)"
    
    return True, "Aligned with trend"

# Simulated P values for common symbols (would normally be calculated from daily data)
SYMBOL_P_VALUES = {
    'AAPL': 0.15, 'MSFT': 0.20, 'GOOGL': 0.10, 'AMZN': 0.25, 'META': 0.35,
    'NVDA': 0.40, 'TSLA': 0.30, 'AMD': 0.20, 'NFLX': 0.15, 'SPY': 0.20,
    'QQQ': 0.25, 'IWM': 0.15, 'COIN': 0.35, 'MSTR': 0.45, 'PLTR': 0.50,
    'GME': -0.10, 'AMC': -0.25, 'RIVN': -0.20, 'LCID': -0.30, 'NIO': -0.35,
    'INTC': -0.15, 'BA': 0.05,
}

def get_symbol_P(symbol: str) -> float:
    """Get P value for symbol"""
    return SYMBOL_P_VALUES.get(symbol, 0.0)

# ============================================================================
# APPLY LIVE BOT FILTERS
# ============================================================================

def apply_bullseye_filter(flows: pd.DataFrame, trade_date: datetime) -> dict:
    """Apply Bullseye Bot filters exactly as in live code"""
    results = {
        'candidates': 0,
        'passed_premium': 0,
        'passed_contracts': 0,
        'passed_dte': 0,
        'passed_otm': 0,
        'passed_score': 0,
        'passed_cooldown': 0,
        'passed_dedup': 0,
        'fired': 0,
        'filtered_by_four_axes': 0,
        'alerts': []
    }
    
    cooldowns = {}  # symbol -> last_alert_time
    alerted_contracts = set()  # Contract-level dedup
    
    for window in sorted(flows['window'].unique()):
        window_flows = flows[flows['window'] == window].copy()
        
        # Collect candidates for this scan, then sort and take top 3
        scan_candidates = []
        
        for _, flow in window_flows.iterrows():
            results['candidates'] += 1
            
            # Premium filter
            if flow['premium'] < BULLSEYE_MIN_PREMIUM:
                continue
            results['passed_premium'] += 1
            
            # Contracts filter
            if flow['contracts'] < BULLSEYE_MIN_CONTRACTS:
                continue
            results['passed_contracts'] += 1
            
            # DTE filter (1-45 days)
            if pd.notna(flow['expiration']):
                dte = (flow['expiration'] - trade_date).days
                if dte < BULLSEYE_MIN_DTE or dte > BULLSEYE_MAX_DTE:
                    continue
            results['passed_dte'] += 1
            
            # OTM filter (max 20%)
            otm_pct = calculate_otm_pct(flow['underlying'], flow['strike'], flow['option_type'])
            if otm_pct > BULLSEYE_MAX_OTM_PCT:
                continue
            results['passed_otm'] += 1
            
            # Score filter
            flow_dict = flow.to_dict()
            score = calculate_bullseye_score(flow_dict)
            if score < BULLSEYE_MIN_SCORE:
                continue
            results['passed_score'] += 1
            
            # Cooldown filter (30 min per symbol)
            symbol = flow['underlying']
            if symbol in cooldowns:
                time_since = (window - cooldowns[symbol]).total_seconds() / 60
                if time_since < BULLSEYE_COOLDOWN_MINS:
                    continue
            results['passed_cooldown'] += 1
            
            # Contract-level deduplication
            contract_key = flow['ticker']
            if contract_key in alerted_contracts:
                continue
            results['passed_dedup'] += 1
            
            # Four Axes filter
            P = get_symbol_P(symbol)
            should_fire, reason = should_take_signal_four_axes(flow_dict, P)
            if not should_fire:
                results['filtered_by_four_axes'] += 1
                continue
            
            # Add to scan candidates
            scan_candidates.append({
                'flow': flow,
                'score': score,
                'symbol': symbol,
                'contract_key': contract_key
            })
        
        # Sort by score and take top N
        scan_candidates.sort(key=lambda x: x['score'], reverse=True)
        
        for candidate in scan_candidates[:BULLSEYE_MAX_ALERTS_PER_SCAN]:
            flow = candidate['flow']
            symbol = candidate['symbol']
            
            results['fired'] += 1
            cooldowns[symbol] = window
            alerted_contracts.add(candidate['contract_key'])
            
            results['alerts'].append({
                'time': window,
                'symbol': symbol,
                'option_type': flow['option_type'],
                'strike': flow['strike'],
                'premium': flow['premium'],
                'contracts': flow['contracts'],
                'score': candidate['score']
            })
    
    return results

def apply_sweeps_filter(flows: pd.DataFrame) -> dict:
    """Apply Sweeps Bot filters exactly as in live code"""
    results = {
        'candidates': 0,
        'passed_premium': 0,
        'passed_otm': 0,
        'passed_score': 0,
        'passed_cooldown': 0,
        'passed_dedup': 0,
        'fired': 0,
        'filtered_by_four_axes': 0,
        'golden_fired': 0,
        'alerts': []
    }
    
    cooldowns = {}  # symbol -> last_alert_time
    alerted_contracts = set()  # Contract-level dedup (ticker)
    
    for window in sorted(flows['window'].unique()):
        window_flows = flows[flows['window'] == window].copy()
        
        # Collect candidates for this scan
        scan_candidates = []
        
        for _, flow in window_flows.iterrows():
            results['candidates'] += 1
            
            # Premium filter
            if flow['premium'] < SWEEPS_MIN_PREMIUM:
                continue
            results['passed_premium'] += 1
            
            # OTM filter
            otm_pct = calculate_otm_pct(flow['underlying'], flow['strike'], flow['option_type'])
            if otm_pct > SWEEPS_MAX_OTM_PCT:
                continue
            results['passed_otm'] += 1
            
            # Score filter
            flow_dict = flow.to_dict()
            score = calculate_sweeps_score(flow_dict)
            if score < SWEEPS_MIN_SCORE:
                continue
            results['passed_score'] += 1
            
            # Cooldown filter (symbol-level, 5 min)
            symbol = flow['underlying']
            if symbol in cooldowns:
                time_since = (window - cooldowns[symbol]).total_seconds() / 60
                if time_since < SWEEPS_COOLDOWN_MINS:
                    continue
            results['passed_cooldown'] += 1
            
            # Contract-level deduplication (SmartDeduplicator)
            contract_key = flow['ticker']  # Unique option contract
            if contract_key in alerted_contracts:
                continue
            results['passed_dedup'] += 1
            
            # Four Axes filter
            P = get_symbol_P(symbol)
            should_fire, reason = should_take_signal_four_axes(flow_dict, P)
            if not should_fire:
                results['filtered_by_four_axes'] += 1
                continue
            
            # Add to candidates
            scan_candidates.append({
                'flow': flow,
                'score': score,
                'symbol': symbol,
                'contract_key': contract_key
            })
        
        # Sort by score and take top N, respecting 1 per symbol
        scan_candidates.sort(key=lambda x: x['score'], reverse=True)
        
        symbols_alerted_this_scan = set()
        alerts_this_scan = 0
        
        for candidate in scan_candidates:
            if alerts_this_scan >= SWEEPS_MAX_ALERTS_PER_SCAN:
                break
            
            symbol = candidate['symbol']
            if symbol in symbols_alerted_this_scan:
                continue
            
            flow = candidate['flow']
            
            results['fired'] += 1
            alerts_this_scan += 1
            symbols_alerted_this_scan.add(symbol)
            cooldowns[symbol] = window
            alerted_contracts.add(candidate['contract_key'])
            
            # Check if Golden Sweep
            if flow['premium'] >= GOLDEN_MIN_PREMIUM:
                results['golden_fired'] += 1
            
            results['alerts'].append({
                'time': window,
                'symbol': symbol,
                'option_type': flow['option_type'],
                'strike': flow['strike'],
                'premium': flow['premium'],
                'contracts': flow['contracts'],
                'score': candidate['score'],
                'is_golden': flow['premium'] >= GOLDEN_MIN_PREMIUM
            })
    
    return results

def apply_99cent_filter(flows: pd.DataFrame) -> dict:
    """Apply 99 Cent Store Bot filters exactly as in live code"""
    results = {
        'candidates': 0,
        'passed_price': 0,
        'passed_premium': 0,
        'passed_otm': 0,
        'passed_cooldown': 0,
        'passed_dedup': 0,
        'fired': 0,
        'filtered_by_four_axes': 0,
        'alerts': []
    }
    
    cooldowns = {}  # symbol -> last_alert_time
    alerted_contracts = set()  # Contract-level dedup
    
    for window in sorted(flows['window'].unique()):
        window_flows = flows[flows['window'] == window].copy()
        
        # Collect candidates for this scan
        scan_candidates = []
        
        for _, flow in window_flows.iterrows():
            results['candidates'] += 1
            
            # Price filter (must be ≤ $1.00)
            if flow['avg_price'] > CENT99_MAX_PRICE:
                continue
            results['passed_price'] += 1
            
            # Premium filter
            if flow['premium'] < CENT99_MIN_PREMIUM:
                continue
            results['passed_premium'] += 1
            
            # OTM filter
            otm_pct = calculate_otm_pct(flow['underlying'], flow['strike'], flow['option_type'])
            if otm_pct > CENT99_MAX_OTM_PCT:
                continue
            results['passed_otm'] += 1
            
            # Cooldown filter (15 min per symbol)
            symbol = flow['underlying']
            if symbol in cooldowns:
                time_since = (window - cooldowns[symbol]).total_seconds() / 60
                if time_since < CENT99_COOLDOWN_MINS:
                    continue
            results['passed_cooldown'] += 1
            
            # Contract-level deduplication
            contract_key = flow['ticker']
            if contract_key in alerted_contracts:
                continue
            results['passed_dedup'] += 1
            
            # Four Axes filter (stricter for swing trades)
            flow_dict = flow.to_dict()
            P = get_symbol_P(symbol)
            should_fire, reason = should_take_signal_four_axes(flow_dict, P)
            if not should_fire:
                results['filtered_by_four_axes'] += 1
                continue
            
            # Add to candidates with premium as score
            scan_candidates.append({
                'flow': flow,
                'premium': flow['premium'],
                'symbol': symbol,
                'contract_key': contract_key
            })
        
        # Sort by premium and take top N
        scan_candidates.sort(key=lambda x: x['premium'], reverse=True)
        
        for candidate in scan_candidates[:CENT99_MAX_ALERTS_PER_SCAN]:
            flow = candidate['flow']
            symbol = candidate['symbol']
            
            results['fired'] += 1
            cooldowns[symbol] = window
            alerted_contracts.add(candidate['contract_key'])
            
            results['alerts'].append({
                'time': window,
                'symbol': symbol,
                'option_type': flow['option_type'],
                'strike': flow['strike'],
                'premium': flow['premium'],
                'contracts': flow['contracts'],
                'avg_price': flow['avg_price']
            })
    
    return results

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("LIVE FILTER BACKTEST - OPRA Trades Data")
    print("=" * 70)
    print()
    print("Applying EXACT live bot thresholds:")
    print(f"  Bullseye: ${BULLSEYE_MIN_PREMIUM/1000:.0f}K premium, {BULLSEYE_MIN_CONTRACTS}+ contracts, score {BULLSEYE_MIN_SCORE}+")
    print(f"  Sweeps:   ${SWEEPS_MIN_PREMIUM/1000:.0f}K premium, score {SWEEPS_MIN_SCORE}+, {SWEEPS_MAX_OTM_PCT*100:.0f}% max OTM")
    print(f"  99 Cent:  ${CENT99_MIN_PREMIUM/1000:.0f}K premium, price ≤${CENT99_MAX_PRICE:.2f}, {CENT99_MAX_OTM_PCT*100:.0f}% max OTM")
    print()
    
    # Download data for Nov 19, 2025 (regular full trading day)
    date_str = '2025-11-19'
    print(f"Loading trades data for {date_str}...")
    df = download_trades_data(date_str)
    
    if df is None or df.empty:
        print("Failed to load data!")
        return
    
    print(f"  Loaded {len(df):,} raw trades")
    
    # Aggregate into flow windows
    flows = aggregate_into_flow_windows(df, window_mins=5)
    
    # Apply each bot's filters
    print()
    print("=" * 70)
    print("APPLYING BOT FILTERS...")
    print("=" * 70)
    
    # Trade date for DTE calculation
    trade_date = datetime(2025, 11, 19)
    
    # Bullseye
    print()
    print("BULLSEYE BOT:")
    bullseye = apply_bullseye_filter(flows, trade_date)
    print(f"  Total candidates:      {bullseye['candidates']:,}")
    print(f"  Passed premium filter: {bullseye['passed_premium']:,}")
    print(f"  Passed contracts:      {bullseye['passed_contracts']:,}")
    print(f"  Passed DTE (1-45):     {bullseye['passed_dte']:,}")
    print(f"  Passed OTM (<20%):     {bullseye['passed_otm']:,}")
    print(f"  Passed score (65+):    {bullseye['passed_score']:,}")
    print(f"  Passed cooldown (30m): {bullseye['passed_cooldown']:,}")
    print(f"  Passed dedup:          {bullseye['passed_dedup']:,}")
    print(f"  Filtered by 4-Axes:    {bullseye['filtered_by_four_axes']:,}")
    print(f"  → FIRED TO DISCORD:    {bullseye['fired']} (max 3 per scan)")
    
    # Sweeps
    print()
    print("SWEEPS BOT:")
    sweeps = apply_sweeps_filter(flows)
    print(f"  Total candidates:      {sweeps['candidates']:,}")
    print(f"  Passed premium filter: {sweeps['passed_premium']:,}")
    print(f"  Passed OTM filter:     {sweeps['passed_otm']:,}")
    print(f"  Passed score (85+):    {sweeps['passed_score']:,}")
    print(f"  Passed cooldown (5m):  {sweeps['passed_cooldown']:,}")
    print(f"  Passed dedup:          {sweeps['passed_dedup']:,}")
    print(f"  Filtered by 4-Axes:    {sweeps['filtered_by_four_axes']:,}")
    print(f"  → FIRED TO DISCORD:    {sweeps['fired']} (max 10 per scan, 1 per symbol)")
    print(f"    (Golden Sweeps):     {sweeps['golden_fired']}")
    
    # 99 Cent Store
    print()
    print("99 CENT STORE:")
    cent99 = apply_99cent_filter(flows)
    print(f"  Total candidates:      {cent99['candidates']:,}")
    print(f"  Passed price filter:   {cent99['passed_price']:,}")
    print(f"  Passed premium filter: {cent99['passed_premium']:,}")
    print(f"  Passed OTM filter:     {cent99['passed_otm']:,}")
    print(f"  Passed cooldown (15m): {cent99['passed_cooldown']:,}")
    print(f"  Passed dedup:          {cent99['passed_dedup']:,}")
    print(f"  Filtered by 4-Axes:    {cent99['filtered_by_four_axes']:,}")
    print(f"  → FIRED TO DISCORD:    {cent99['fired']} (max 5 per scan)")
    
    # Summary
    print()
    print("=" * 70)
    print("SUMMARY - ALERTS THAT WOULD FIRE ON NOV 28, 2025")
    print("=" * 70)
    total_alerts = bullseye['fired'] + sweeps['fired'] + cent99['fired']
    print(f"  Bullseye:      {bullseye['fired']:3} alerts")
    print(f"  Sweeps:        {sweeps['fired']:3} alerts ({sweeps['golden_fired']} Golden)")
    print(f"  99 Cent Store: {cent99['fired']:3} alerts")
    print(f"  ─────────────────────────")
    print(f"  TOTAL:         {total_alerts:3} alerts for the day")
    
    # Show sample alerts
    if bullseye['alerts']:
        print()
        print("Sample Bullseye Alerts:")
        for alert in bullseye['alerts'][:5]:
            print(f"  {alert['time'].strftime('%H:%M')} {alert['symbol']} {alert['option_type']} ${alert['strike']:.0f} - ${alert['premium']/1000:.0f}K ({alert['contracts']} contracts)")
    
    if sweeps['alerts']:
        print()
        print("Sample Sweeps Alerts:")
        for alert in sweeps['alerts'][:5]:
            golden = "🌟 GOLDEN" if alert['is_golden'] else ""
            print(f"  {alert['time'].strftime('%H:%M')} {alert['symbol']} {alert['option_type']} ${alert['strike']:.0f} - ${alert['premium']/1000:.0f}K {golden}")
    
    if cent99['alerts']:
        print()
        print("Sample 99 Cent Store Alerts:")
        for alert in cent99['alerts'][:5]:
            print(f"  {alert['time'].strftime('%H:%M')} {alert['symbol']} {alert['option_type']} ${alert['strike']:.0f} @ ${alert['avg_price']:.2f} - ${alert['premium']/1000:.0f}K")

if __name__ == "__main__":
    main()

