"""
ORAKL Bot Calculation Utilities
Helper functions for options calculations, technical indicators, and probabilities
"""

import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import pandas as pd
from typing import Optional, Tuple, Dict
import math

def calculate_implied_volatility(option_price: float, stock_price: float, strike: float,
                               time_to_expiry: float, risk_free_rate: float = 0.02,
                               option_type: str = 'CALL', iterations: int = 100) -> float:
    """
    Calculate implied volatility using Newton-Raphson method
    """
    # Initial guess
    vol = 0.3
    
    for _ in range(iterations):
        # Calculate option price and vega
        price, vega = black_scholes_price_and_vega(
            stock_price, strike, time_to_expiry, risk_free_rate, vol, option_type
        )
        
        # Newton-Raphson update
        diff = option_price - price
        if abs(diff) < 0.001:
            break
            
        if vega == 0:
            break
            
        vol = vol + diff / vega
        vol = max(0.001, min(5.0, vol))  # Keep IV in reasonable range
        
    return vol

def black_scholes_price_and_vega(stock_price: float, strike: float, time_to_expiry: float,
                                risk_free_rate: float, volatility: float, 
                                option_type: str) -> Tuple[float, float]:
    """
    Calculate Black-Scholes option price and vega
    """
    if time_to_expiry <= 0:
        # Option expired
        if option_type == 'CALL':
            price = max(0, stock_price - strike)
        else:
            price = max(0, strike - stock_price)
        return price, 0
        
    d1 = (np.log(stock_price / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / \
         (volatility * np.sqrt(time_to_expiry))
    d2 = d1 - volatility * np.sqrt(time_to_expiry)
    
    if option_type == 'CALL':
        price = stock_price * norm.cdf(d1) - strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)
    else:
        price = strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2) - stock_price * norm.cdf(-d1)
        
    vega = stock_price * norm.pdf(d1) * np.sqrt(time_to_expiry) / 100
    
    return price, vega

def calculate_all_greeks(stock_price: float, strike: float, time_to_expiry: float,
                        risk_free_rate: float, volatility: float, 
                        option_type: str = 'CALL') -> Dict[str, float]:
    """
    Calculate all option Greeks
    """
    if time_to_expiry <= 0:
        return {
            'delta': 1.0 if (option_type == 'CALL' and stock_price > strike) else 0.0,
            'gamma': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'rho': 0.0
        }
        
    sqrt_t = np.sqrt(time_to_expiry)
    d1 = (np.log(stock_price / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / \
         (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    
    # Delta
    if option_type == 'CALL':
        delta = norm.cdf(d1)
        theta = -(stock_price * norm.pdf(d1) * volatility) / (2 * sqrt_t) - \
                risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)
        rho = strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)
    else:
        delta = norm.cdf(d1) - 1
        theta = -(stock_price * norm.pdf(d1) * volatility) / (2 * sqrt_t) + \
                risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2)
        rho = -strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * norm.cdf(-d2)
        
    # Greeks common to both
    gamma = norm.pdf(d1) / (stock_price * volatility * sqrt_t)
    vega = stock_price * norm.pdf(d1) * sqrt_t / 100
    theta = theta / 365  # Convert to daily theta
    rho = rho / 100  # Convert to percentage
    
    return {
        'delta': round(delta, 4),
        'gamma': round(gamma, 4),
        'theta': round(theta, 4),
        'vega': round(vega, 4),
        'rho': round(rho, 4)
    }

def calculate_expected_move(volatility: float, stock_price: float, days: int) -> Tuple[float, float]:
    """
    Calculate expected move based on implied volatility
    """
    daily_move = volatility / np.sqrt(252)  # Convert annual vol to daily
    expected_move_pct = daily_move * np.sqrt(days)
    expected_move_dollars = stock_price * expected_move_pct
    
    return round(expected_move_dollars, 2), round(expected_move_pct * 100, 2)

def calculate_breakeven(option_type: str, strike: float, premium: float) -> float:
    """
    Calculate breakeven price for an option
    """
    if option_type == 'CALL':
        return strike + premium
    else:
        return strike - premium

def calculate_profit_loss(option_type: str, strike: float, premium: float, 
                         current_price: float, contracts: int = 1) -> float:
    """
    Calculate profit/loss for an option position
    """
    if option_type == 'CALL':
        intrinsic_value = max(0, current_price - strike)
    else:
        intrinsic_value = max(0, strike - current_price)
        
    profit_per_contract = (intrinsic_value - premium) * 100
    total_profit = profit_per_contract * contracts
    
    return round(total_profit, 2)

def calculate_volume_weighted_average(trades_df: pd.DataFrame) -> float:
    """
    Calculate volume-weighted average price
    """
    if trades_df.empty or 'volume' not in trades_df.columns or 'price' not in trades_df.columns:
        return 0
        
    total_volume = trades_df['volume'].sum()
    if total_volume == 0:
        return trades_df['price'].mean()
        
    vwap = (trades_df['price'] * trades_df['volume']).sum() / total_volume
    return round(vwap, 2)

def calculate_moneyness(stock_price: float, strike: float, option_type: str) -> str:
    """
    Determine if option is ITM, ATM, or OTM
    """
    ratio = stock_price / strike
    
    if option_type == 'CALL':
        if ratio > 1.02:
            return 'ITM'
        elif ratio < 0.98:
            return 'OTM'
        else:
            return 'ATM'
    else:  # PUT
        if ratio < 0.98:
            return 'ITM'
        elif ratio > 1.02:
            return 'OTM'
        else:
            return 'ATM'

def calculate_max_pain(options_chain_df: pd.DataFrame, current_price: float) -> float:
    """
    Calculate max pain price from options chain
    """
    if options_chain_df.empty:
        return current_price
        
    strikes = options_chain_df['strike'].unique()
    pain_values = []
    
    for strike in strikes:
        total_pain = 0
        
        # Calculate pain for calls
        calls = options_chain_df[(options_chain_df['type'] == 'CALL') & 
                               (options_chain_df['strike'] != strike)]
        for _, call in calls.iterrows():
            if call['strike'] < strike:
                total_pain += (strike - call['strike']) * call.get('open_interest', 0)
                
        # Calculate pain for puts
        puts = options_chain_df[(options_chain_df['type'] == 'PUT') & 
                              (options_chain_df['strike'] != strike)]
        for _, put in puts.iterrows():
            if put['strike'] > strike:
                total_pain += (put['strike'] - strike) * put.get('open_interest', 0)
                
        pain_values.append((strike, total_pain))
        
    # Find strike with minimum pain
    if pain_values:
        max_pain_strike = min(pain_values, key=lambda x: x[1])[0]
        return max_pain_strike
    else:
        return current_price

def calculate_put_call_ratio(options_data: pd.DataFrame) -> float:
    """
    Calculate put/call ratio from options data
    """
    if options_data.empty:
        return 1.0
        
    call_volume = options_data[options_data['type'] == 'CALL']['volume'].sum()
    put_volume = options_data[options_data['type'] == 'PUT']['volume'].sum()
    
    if call_volume == 0:
        return float('inf') if put_volume > 0 else 1.0
        
    return round(put_volume / call_volume, 2)

def calculate_gamma_exposure(options_chain: pd.DataFrame, spot_price: float) -> pd.DataFrame:
    """
    Calculate gamma exposure by strike
    """
    gamma_exposure = []
    
    for _, option in options_chain.iterrows():
        strike = option['strike']
        oi = option.get('open_interest', 0)
        gamma = option.get('gamma', 0)
        
        # Gamma exposure = OI * Gamma * Spot Price^2 / 100
        gex = oi * gamma * (spot_price ** 2) / 100
        
        if option['type'] == 'PUT':
            gex = -gex
            
        gamma_exposure.append({
            'strike': strike,
            'gamma_exposure': gex,
            'type': option['type']
        })
        
    return pd.DataFrame(gamma_exposure)

def calculate_historical_volatility(price_series: pd.Series, periods: int = 20) -> float:
    """
    Calculate historical volatility from price series
    """
    if len(price_series) < periods:
        return 0.3  # Default volatility
        
    returns = price_series.pct_change().dropna()
    daily_vol = returns.rolling(periods).std().iloc[-1]
    annual_vol = daily_vol * np.sqrt(252)
    
    return round(annual_vol, 4)
