"""
ORAKL Bot Chart Utilities
Functions for generating options flow charts and visualizations
"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from io import BytesIO
import plotly.graph_objects as go
import plotly.io as pio
from typing import Optional, List, Dict
import warnings
warnings.filterwarnings('ignore')

# Set style
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

def create_flow_chart(trades_df: pd.DataFrame, symbol: str) -> BytesIO:
    """
    Create options flow chart showing premium over time
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    
    # Prepare data
    trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
    trades_df = trades_df.sort_values('timestamp')
    
    # Separate calls and puts
    calls = trades_df[trades_df['type'] == 'CALL']
    puts = trades_df[trades_df['type'] == 'PUT']
    
    # Plot 1: Premium flow over time
    if not calls.empty:
        ax1.scatter(calls['timestamp'], calls['premium'], 
                   color='green', alpha=0.6, s=50, label='Call Premium')
    if not puts.empty:
        ax1.scatter(puts['timestamp'], puts['premium'], 
                   color='red', alpha=0.6, s=50, label='Put Premium')
    
    ax1.set_ylabel('Premium ($)')
    ax1.set_title(f'{symbol} Options Flow Analysis')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Cumulative premium
    trades_df['cumulative_call'] = trades_df[trades_df['type'] == 'CALL']['premium'].cumsum()
    trades_df['cumulative_put'] = trades_df[trades_df['type'] == 'PUT']['premium'].cumsum()
    
    trades_df['cumulative_call'].fillna(method='ffill', inplace=True)
    trades_df['cumulative_put'].fillna(method='ffill', inplace=True)
    
    ax2.plot(trades_df['timestamp'], trades_df['cumulative_call'], 
             color='green', linewidth=2, label='Cumulative Call Premium')
    ax2.plot(trades_df['timestamp'], trades_df['cumulative_put'], 
             color='red', linewidth=2, label='Cumulative Put Premium')
    
    ax2.set_xlabel('Time')
    ax2.set_ylabel('Cumulative Premium ($)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Format x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf

def create_heatmap(options_chain: pd.DataFrame, current_price: float, symbol: str) -> BytesIO:
    """
    Create options heatmap showing volume/OI by strike
    """
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Prepare data
    pivot_data = options_chain.pivot_table(
        index='strike',
        columns='type',
        values='volume',
        aggfunc='sum',
        fill_value=0
    )
    
    # Create heatmap
    sns.heatmap(pivot_data, annot=True, fmt='.0f', cmap='YlOrRd', 
                cbar_kws={'label': 'Volume'}, ax=ax)
    
    # Add current price line
    if current_price in pivot_data.index:
        ax.axhline(y=pivot_data.index.get_loc(current_price), 
                  color='blue', linewidth=2, linestyle='--', label=f'Current: ${current_price}')
    
    ax.set_title(f'{symbol} Options Volume Heatmap')
    ax.set_xlabel('Option Type')
    ax.set_ylabel('Strike Price')
    
    plt.tight_layout()
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf

def create_oi_chart(options_chain: pd.DataFrame, current_price: float, symbol: str) -> BytesIO:
    """
    Create open interest chart by strike
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Separate calls and puts
    calls = options_chain[options_chain['type'] == 'CALL'].groupby('strike')['open_interest'].sum()
    puts = options_chain[options_chain['type'] == 'PUT'].groupby('strike')['open_interest'].sum()
    
    # Plot bars
    strikes = sorted(set(calls.index) | set(puts.index))
    x = np.arange(len(strikes))
    width = 0.35
    
    call_oi = [calls.get(strike, 0) for strike in strikes]
    put_oi = [puts.get(strike, 0) for strike in strikes]
    
    ax.bar(x - width/2, call_oi, width, label='Call OI', color='green', alpha=0.7)
    ax.bar(x + width/2, put_oi, width, label='Put OI', color='red', alpha=0.7)
    
    # Add current price indicator
    current_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - current_price))
    ax.axvline(x=current_idx, color='blue', linestyle='--', linewidth=2, 
              label=f'Current: ${current_price}')
    
    ax.set_xlabel('Strike Price')
    ax.set_ylabel('Open Interest')
    ax.set_title(f'{symbol} Open Interest by Strike')
    ax.set_xticks(x)
    ax.set_xticklabels([f'${s}' for s in strikes], rotation=45)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf

def create_gamma_exposure_chart(gamma_data: pd.DataFrame, current_price: float, symbol: str) -> BytesIO:
    """
    Create gamma exposure chart
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Aggregate gamma exposure by strike
    gex_by_strike = gamma_data.groupby('strike')['gamma_exposure'].sum()
    
    # Plot
    strikes = gex_by_strike.index
    values = gex_by_strike.values
    
    colors = ['green' if v > 0 else 'red' for v in values]
    ax.bar(strikes, values, color=colors, alpha=0.7)
    
    # Add current price line
    ax.axvline(x=current_price, color='blue', linestyle='--', linewidth=2,
              label=f'Current: ${current_price}')
    
    # Add zero line
    ax.axhline(y=0, color='black', linewidth=0.5)
    
    ax.set_xlabel('Strike Price')
    ax.set_ylabel('Gamma Exposure')
    ax.set_title(f'{symbol} Gamma Exposure by Strike')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf

def create_price_volume_chart(price_data: pd.DataFrame, trades_df: pd.DataFrame, symbol: str) -> BytesIO:
    """
    Create price chart with volume overlay
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, 
                                   gridspec_kw={'height_ratios': [3, 1]})
    
    # Price chart
    ax1.plot(price_data['timestamp'], price_data['close'], 
             color='black', linewidth=2, label='Price')
    
    # Add trade markers
    if not trades_df.empty:
        calls = trades_df[trades_df['type'] == 'CALL']
        puts = trades_df[trades_df['type'] == 'PUT']
        
        # Size markers by premium
        call_sizes = (calls['premium'] / 1000).clip(10, 200)
        put_sizes = (puts['premium'] / 1000).clip(10, 200)
        
        ax1.scatter(calls['timestamp'], calls['strike'], 
                   s=call_sizes, color='green', alpha=0.5, marker='^', label='Call Trades')
        ax1.scatter(puts['timestamp'], puts['strike'], 
                   s=put_sizes, color='red', alpha=0.5, marker='v', label='Put Trades')
    
    ax1.set_ylabel('Price ($)')
    ax1.set_title(f'{symbol} Price and Options Flow')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # Volume chart
    ax2.bar(price_data['timestamp'], price_data['volume'], 
            color='gray', alpha=0.5)
    ax2.set_ylabel('Volume')
    ax2.set_xlabel('Time')
    ax2.grid(True, alpha=0.3)
    
    # Format x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf

def create_sentiment_gauge(sentiment_score: float, symbol: str) -> BytesIO:
    """
    Create sentiment gauge chart
    """
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=sentiment_score,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': f"{symbol} Options Sentiment"},
        delta={'reference': 0},
        gauge={
            'axis': {'range': [-100, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [-100, -50], 'color': "darkred"},
                {'range': [-50, -20], 'color': "red"},
                {'range': [-20, 20], 'color': "gray"},
                {'range': [20, 50], 'color': "lightgreen"},
                {'range': [50, 100], 'color': "green"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': sentiment_score
            }
        }
    ))
    
    fig.update_layout(height=400, width=600)
    
    # Save to BytesIO
    buf = BytesIO()
    fig.write_image(buf, format='png')
    buf.seek(0)
    
    return buf

def create_flow_distribution(trades_df: pd.DataFrame, symbol: str) -> BytesIO:
    """
    Create flow distribution chart
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # Premium distribution
    calls_premium = trades_df[trades_df['type'] == 'CALL']['premium']
    puts_premium = trades_df[trades_df['type'] == 'PUT']['premium']
    
    ax1.hist(calls_premium, bins=20, alpha=0.5, color='green', label='Calls')
    ax1.hist(puts_premium, bins=20, alpha=0.5, color='red', label='Puts')
    ax1.set_xlabel('Premium ($)')
    ax1.set_ylabel('Frequency')
    ax1.set_title(f'{symbol} Premium Distribution')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Strike distribution
    trades_by_strike = trades_df.groupby(['strike', 'type'])['premium'].sum().unstack(fill_value=0)
    trades_by_strike.plot(kind='bar', ax=ax2, color=['green', 'red'], alpha=0.7)
    ax2.set_xlabel('Strike Price')
    ax2.set_ylabel('Total Premium ($)')
    ax2.set_title(f'{symbol} Premium by Strike')
    ax2.legend(['Call', 'Put'])
    ax2.grid(True, alpha=0.3)
    
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Save to BytesIO
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf
