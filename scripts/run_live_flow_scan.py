import asyncio
import logging
from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config  # noqa: E402
from src.data_fetcher import DataFetcher  # noqa: E402


async def run_scan(symbols: list[str]) -> None:
    """Execute detect_unusual_flow against a set of symbols."""
    async with DataFetcher(Config.POLYGON_API_KEY) as fetcher:
        for symbol in symbols:
            flows = await fetcher.detect_unusual_flow(
                underlying=symbol,
                min_premium=1_000,
                min_volume_delta=5,
            )

            if flows:
                top_flow = flows[0]
                print(
                    f"\n{symbol}: detected {len(flows)} flows "
                    f"(top premium ${top_flow['premium']:.2f}, "
                    f"volume delta {top_flow['volume_delta']}, "
                    f"price ${top_flow['last_price']:.2f})"
                )
            else:
                print(f"\n{symbol}: no qualifying flows")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    print(f"Starting live flow scan @ {datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC")
    symbols = ["AAPL", "TSLA", "NVDA", "SPY"]
    await run_scan(symbols)


if __name__ == "__main__":
    asyncio.run(main())
