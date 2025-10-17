#!/usr/bin/env python3
"""Debug scanning issue"""
import asyncio
import logging
from src.data_fetcher import DataFetcher
from src.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_scan():
    """Test scanning a few symbols"""
    fetcher = DataFetcher(Config.POLYGON_API_KEY)
    
    # Test with just a few symbols
    test_symbols = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
    
    try:
        logger.info(f"Testing scan with {len(test_symbols)} symbols...")
        
        for symbol in test_symbols:
            logger.info(f"\nScanning {symbol}...")
            
            # Get stock price
            price = await fetcher.get_stock_price(symbol)
            logger.info(f"  Price: ${price}")
            
            # Get options chain
            options = await fetcher.get_options_chain(symbol)
            logger.info(f"  Options contracts: {len(options)}")
            
            # Check what columns we have
            if not options.empty:
                logger.info(f"  Columns: {list(options.columns)}")
                # Show first row to understand structure
                if len(options) > 0:
                    first = options.iloc[0]
                    logger.info(f"  Sample contract: {first.to_dict()}")
        
        logger.info("\nScan completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Scan failed: {e}", exc_info=True)
        return False
    finally:
        await fetcher.close()

if __name__ == "__main__":
    success = asyncio.run(test_scan())
    if not success:
        print("\n❌ Scan failed!")