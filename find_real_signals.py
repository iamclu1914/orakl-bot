#!/usr/bin/env python3
"""Find and send real trading signals"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from src.config import Config
from src.data_fetcher import DataFetcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_signal(webhook_url, embed):
    """Send signal to Discord"""
    payload = {"embeds": [embed], "username": "ORAKL Signal Finder"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(webhook_url, json=payload) as response:
                if response.status == 204:
                    return True
        except Exception as e:
            logger.error(f"Error sending signal: {e}")
    return False

async def find_volume_signals():
    """Find real volume signals"""
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    signals_sent = 0
    
    # Focus on high-volume stocks
    symbols = ["NVDA", "TSLA", "AMD", "SPY", "QQQ", "AAPL", "META", "AMZN"]
    
    try:
        for symbol in symbols:
            try:
                # Get current price
                price = await fetcher.get_stock_price(symbol)
                if not price:
                    continue
                
                # Get today's data
                today = datetime.now().strftime('%Y-%m-%d')
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                
                # Get minute bars for today
                bars = await fetcher.get_aggregates(
                    symbol,
                    timespan='minute',
                    multiplier=5,  # 5-minute bars
                    from_date=today,
                    to_date=today
                )
                
                if bars.empty or 'volume' not in bars.columns:
                    continue
                
                # Calculate current session volume
                current_volume = bars['volume'].sum()
                
                # Get yesterday's volume for comparison
                yesterday_bars = await fetcher.get_aggregates(
                    symbol,
                    timespan='day',
                    multiplier=1,
                    from_date=yesterday,
                    to_date=yesterday
                )
                
                if not yesterday_bars.empty and 'volume' in yesterday_bars.columns:
                    yesterday_volume = yesterday_bars['volume'].iloc[0]
                    
                    # Time adjustment (market is about 2.5 hours in)
                    time_factor = 2.5 / 6.5
                    expected_volume = yesterday_volume * time_factor
                    
                    if current_volume > expected_volume * 1.2:  # 20% above expected
                        volume_ratio = current_volume / expected_volume
                        
                        # Check recent price movement
                        price_change = 0
                        if len(bars) > 5:
                            recent_high = bars['high'].tail(5).max()
                            recent_low = bars['low'].tail(5).min()
                            price_change = ((price - recent_low) / recent_low) * 100
                        
                        # Create alert
                        color = 0x00FF00 if price_change > 0 else 0xFF0000
                        
                        embed = {
                            "title": f"📊 Unusual Volume: {symbol}",
                            "description": f"Higher than expected volume detected",
                            "color": color,
                            "fields": [
                                {"name": "Current Price", "value": f"${price:.2f}", "inline": True},
                                {"name": "Volume vs Expected", "value": f"{volume_ratio:.1f}x", "inline": True},
                                {"name": "Current Volume", "value": f"{current_volume:,}", "inline": True},
                                {"name": "Price Move", "value": f"{price_change:+.2f}%", "inline": True},
                                {"name": "Yesterday Volume", "value": f"{yesterday_volume:,}", "inline": True},
                                {"name": "Time", "value": datetime.now().strftime("%I:%M %p ET"), "inline": True}
                            ],
                            "footer": {"text": "ORAKL Bot | Real Market Data"},
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        
                        if await send_signal(Config.UNUSUAL_ACTIVITY_WEBHOOK, embed):
                            logger.info(f"✅ Sent volume alert for {symbol}")
                            signals_sent += 1
                            
                            if signals_sent >= 3:  # Limit to 3 signals
                                break
                
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
        
        logger.info(f"Found and sent {signals_sent} real signals")
        
    finally:
        await fetcher.close()

async def find_options_activity():
    """Find options with high activity"""
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    
    # Check popular stocks for options activity
    symbols = ["SPY", "QQQ", "TSLA", "NVDA", "AAPL"]
    
    try:
        for symbol in symbols:
            # This would need real options flow data
            # For now, we'll focus on volume signals
            pass
    finally:
        await fetcher.close()

async def main():
    """Find and send real signals"""
    logger.info("Searching for real market signals...")
    
    # Find volume signals
    await find_volume_signals()
    
    logger.info("Signal search complete")

if __name__ == "__main__":
    asyncio.run(main())