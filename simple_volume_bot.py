#!/usr/bin/env python3
"""Simple volume-based signal bot"""
import asyncio
import aiohttp
import logging
from datetime import datetime
from src.config import Config
from src.data_fetcher import DataFetcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_signal(webhook_url, signal):
    """Send signal to Discord"""
    embed = {
        "title": f"🚨 {signal['type']}: {signal['ticker']}",
        "description": signal['description'],
        "color": signal['color'],
        "fields": [
            {"name": "Current Price", "value": f"${signal['price']:.2f}", "inline": True},
            {"name": "Volume Ratio", "value": f"{signal['volume_ratio']:.1f}x", "inline": True},
            {"name": "Volume", "value": f"{signal['volume']:,}", "inline": True},
        ],
        "footer": {"text": "ORAKL Simple Bot | Not Financial Advice"},
        "timestamp": datetime.utcnow().isoformat()
    }
    
    payload = {"embeds": [embed], "username": "ORAKL Volume Bot"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(webhook_url, json=payload) as response:
                if response.status == 204:
                    logger.info(f"✅ Signal posted for {signal['ticker']}")
                    return True
                else:
                    logger.error(f"Failed to post signal: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error posting signal: {e}")
            return False

async def scan_for_signals():
    """Simple scan for volume spikes"""
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    webhook_url = Config.UNUSUAL_ACTIVITY_WEBHOOK
    
    # Use a small focused list
    watchlist = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN", "SPY", "QQQ"]
    
    try:
        logger.info(f"Scanning {len(watchlist)} symbols for unusual volume...")
        signals_found = 0
        
        for symbol in watchlist:
            try:
                # Get current price
                price = await fetcher.get_stock_price(symbol)
                if not price:
                    continue
                
                # Get today's volume
                today = datetime.now().strftime('%Y-%m-%d')
                bars = await fetcher.get_aggregates(
                    symbol,
                    timespan='day',
                    multiplier=1,
                    from_date=today,
                    to_date=today
                )
                
                if bars.empty:
                    continue
                
                current_volume = bars.iloc[0]['volume'] if 'volume' in bars.columns else 0
                
                # Get 20-day average volume
                from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                hist_bars = await fetcher.get_aggregates(
                    symbol,
                    timespan='day',
                    multiplier=1,
                    from_date=from_date,
                    to_date=today
                )
                
                if not hist_bars.empty and 'volume' in hist_bars.columns:
                    avg_volume = hist_bars['volume'].mean()
                    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
                    logger.info(f"{symbol}: Price=${price:.2f}, Volume={current_volume:,}, Avg={avg_volume:,.0f}, Ratio={volume_ratio:.2f}x")
                    
                    # Adjust threshold based on time of day
                    # It's ~11:45 AM ET, so about 2.25 hours into trading day (out of 6.5 hours)
                    time_factor = 2.25 / 6.5  # About 35% through the day
                    adjusted_ratio = volume_ratio / time_factor if time_factor > 0 else volume_ratio
                    
                    # Signal if projected full-day volume would be 2x+ average
                    if adjusted_ratio >= 2.0 and current_volume > 500000:
                        signal = {
                            'ticker': symbol,
                            'type': 'Unusual Volume Alert',
                            'description': f"Trading at {volume_ratio:.1f}x average volume",
                            'price': price,
                            'volume': current_volume,
                            'volume_ratio': volume_ratio,
                            'color': 0xFF9800  # Orange
                        }
                        
                        await send_signal(webhook_url, signal)
                        signals_found += 1
                        
                        # Limit to 3 signals per scan
                        if signals_found >= 3:
                            break
                
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
                continue
        
        logger.info(f"Scan complete. Found {signals_found} signals.")
        
    except Exception as e:
        logger.error(f"Scan error: {e}")
    finally:
        await fetcher.close()

async def main():
    """Run the simple bot"""
    logger.info("Starting Simple Volume Bot...")
    
    while True:
        try:
            await scan_for_signals()
            logger.info("Waiting 3 minutes before next scan...")
            await asyncio.sleep(180)  # 3 minutes
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Bot error: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error

if __name__ == "__main__":
    # Add missing import
    from datetime import timedelta
    asyncio.run(main())