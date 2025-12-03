"""
Backtest the 99 Cent Store alerts using Polygon minute aggregates.

Steps performed:
1. Hard-code the historical alert tape supplied by the user.
2. Map each alert to the Polygon option ticker format.
3. Pull minute aggregates from the alert timestamp through contract expiration.
4. Compute the maximum price achieved after the alert and the corresponding return.
5. Output a per-alert table plus aggregate performance metrics.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd  # type: ignore
import pytz

from src.config import Config
from src.data_fetcher import DataFetcher

EASTERN_TZ = pytz.timezone("US/Eastern")


@dataclass(frozen=True)
class AlertRecord:
    """
    Represents a single 99 Cent Store alert.

    The timestamps supplied in the Discord log are assumed to be in US/Eastern time.
    """

    symbol: str
    option_type: str  # "C" or "P"
    strike: float
    expiration: str  # ISO date (YYYY-MM-DD)
    alert_time: str  # ISO datetime without timezone (YYYY-MM-DD HH:MM)
    entry_price: float
    size: int
    premium: float

    @property
    def alert_dt(self) -> datetime:
        """Return the timezone-aware alert timestamp."""
        naive = datetime.strptime(self.alert_time, "%Y-%m-%d %H:%M")
        return EASTERN_TZ.localize(naive)

    @property
    def expiration_close(self) -> datetime:
        """
        Options generally expire at market close (16:00 ET) on the listed date.
        Use that as the backtest cutoff.
        """
        exp_date = datetime.strptime(self.expiration, "%Y-%m-%d")
        exp_dt = exp_date.replace(hour=16, minute=0)
        return EASTERN_TZ.localize(exp_dt)

    @property
    def polygon_option_ticker(self) -> str:
        """
        Build the Polygon option ticker identifier, e.g. O:AAPL250117C00200000.
        See https://polygon.io/docs/options/get_v3_snapshot_options__underlyingasset_
        """
        exp = datetime.strptime(self.expiration, "%Y-%m-%d")
        exp_token = exp.strftime("%y%m%d")
        strike_int = int(round(self.strike * 1000))
        strike_token = f"{strike_int:08d}"
        option_side = "C" if self.option_type.upper().startswith("C") else "P"
        return f"O:{self.symbol.upper()}{exp_token}{option_side}{strike_token}"


# Hard-coded alert history taken directly from the Discord feed provided by the user.
def dedupe_alerts(alerts: List[AlertRecord]) -> List[AlertRecord]:
    """
    Remove duplicate alerts based on unique key of symbol, option type, strike,
    expiration, and alert timestamp while preserving insertion order.
    """
    seen: Dict[tuple, AlertRecord] = {}
    for alert in alerts:
        key = (
            alert.symbol.upper(),
            alert.option_type.upper(),
            alert.strike,
            alert.expiration,
            alert.alert_time,
        )
        if key not in seen:
            seen[key] = alert
    return list(seen.values())


ALERTS_RAW: List[AlertRecord] = [
    # 2025-11-14
    AlertRecord("PFE", "C", 25.5, "2025-11-28", "2025-11-14 12:51", 0.57, 5000, 285_000),
    AlertRecord("PFE", "C", 25.5, "2025-11-28", "2025-11-14 13:03", 0.50, 5000, 250_000),
    AlertRecord("MRNA", "C", 25.5, "2025-11-21", "2025-11-14 13:03", 0.53, 5000, 265_000),
    AlertRecord("MRK", "C", 96.0, "2025-11-21", "2025-11-14 13:25", 0.81, 5000, 405_000),
    AlertRecord("PYPL", "C", 65.0, "2025-11-21", "2025-11-14 13:40", 0.67, 5000, 335_000),
    AlertRecord("MRK", "C", 96.0, "2025-11-21", "2025-11-14 13:52", 0.64, 5000, 320_000),
    AlertRecord("MRK", "C", 96.0, "2025-11-21", "2025-11-14 14:11", 0.60, 5000, 300_000),
    AlertRecord("PYPL", "C", 65.0, "2025-11-21", "2025-11-14 14:14", 0.62, 5000, 310_000),
    AlertRecord("PYPL", "C", 65.0, "2025-11-21", "2025-11-14 14:40", 0.55, 5000, 275_000),
    AlertRecord("PYPL", "C", 65.0, "2025-11-21", "2025-11-14 14:50", 0.52, 6759, 351_000),
    AlertRecord("GME", "C", 21.0, "2025-11-21", "2025-11-14 14:50", 0.43, 10_856, 467_000),
    AlertRecord("MRK", "C", 96.0, "2025-11-21", "2025-11-14 15:09", 0.74, 5000, 370_000),
    AlertRecord("MRNA", "C", 25.5, "2025-11-21", "2025-11-14 15:09", 0.55, 5000, 275_000),
    AlertRecord("MRNA", "C", 25.5, "2025-11-21", "2025-11-14 15:20", 0.55, 5000, 275_000),
    AlertRecord("PYPL", "C", 65.0, "2025-11-21", "2025-11-14 15:23", 0.52, 5000, 260_000),
    AlertRecord("DIS", "C", 108.0, "2025-11-21", "2025-11-14 15:48", 0.78, 4065, 317_000),
    AlertRecord("ORCL", "C", 245.0, "2025-11-21", "2025-11-14 15:52", 0.89, 5000, 445_000),
    # 2025-11-17
    AlertRecord("CLF", "C", 11.5, "2025-12-05", "2025-11-17 11:49", 0.61, 5000, 305_000),
    AlertRecord("CLF", "C", 11.5, "2025-12-05", "2025-11-17 12:28", 0.58, 5000, 290_000),
    AlertRecord("CLF", "C", 11.5, "2025-12-05", "2025-11-17 13:06", 0.52, 5000, 260_000),
    AlertRecord("GOOGL", "C", 310.0, "2025-11-28", "2025-11-17 13:57", 0.90, 4067, 366_000),
    AlertRecord("ARKK", "P", 70.0, "2025-11-28", "2025-11-17 14:16", 0.99, 5000, 495_000),
    AlertRecord("PYPL", "C", 65.0, "2025-12-05", "2025-11-17 14:20", 0.95, 5000, 475_000),
    AlertRecord("GOOGL", "C", 310.0, "2025-11-28", "2025-11-17 14:34", 0.74, 4302, 318_000),
    AlertRecord("AAPL", "C", 277.5, "2025-11-28", "2025-11-17 15:02", 0.97, 5000, 485_000),
    AlertRecord("PYPL", "C", 65.0, "2025-12-05", "2025-11-17 15:02", 0.85, 10_086, 857_000),
    AlertRecord("PYPL", "C", 65.0, "2025-12-05", "2025-11-17 15:03", 0.85, 5000, 425_000),
    AlertRecord("UBER", "P", 87.0, "2025-11-28", "2025-11-17 15:07", 0.74, 3771, 279_000),
    AlertRecord("UBER", "P", 87.0, "2025-11-28", "2025-11-17 15:08", 0.74, 3771, 279_000),
    AlertRecord("AAPL", "C", 277.5, "2025-11-28", "2025-11-17 15:17", 0.94, 5000, 470_000),
    AlertRecord("AAPL", "C", 277.5, "2025-11-28", "2025-11-17 15:23", 0.94, 5000, 470_000),
    AlertRecord("GOOGL", "C", 310.0, "2025-11-28", "2025-11-17 15:23", 0.73, 4444, 324_000),
    AlertRecord("GOOGL", "C", 310.0, "2025-11-28", "2025-11-17 15:37", 0.74, 4461, 330_000),
    AlertRecord("AAPL", "C", 277.5, "2025-11-28", "2025-11-17 15:39", 0.96, 5000, 480_000),
    AlertRecord("GOOGL", "C", 310.0, "2025-11-28", "2025-11-17 15:39", 0.73, 4463, 326_000),
    AlertRecord("UBER", "P", 87.0, "2025-11-28", "2025-11-17 15:39", 0.69, 3772, 260_000),
    AlertRecord("DAL", "P", 53.0, "2025-11-28", "2025-11-17 15:39", 0.74, 5000, 370_000),
    AlertRecord("AAPL", "C", 277.5, "2025-11-28", "2025-11-17 15:40", 0.96, 5000, 480_000),
    AlertRecord("UBER", "P", 87.0, "2025-11-28", "2025-11-17 15:40", 0.69, 3772, 260_000),
    AlertRecord("DAL", "P", 53.0, "2025-11-28", "2025-11-17 15:40", 0.74, 5000, 370_000),
    AlertRecord("PYPL", "C", 65.0, "2025-12-05", "2025-11-17 15:46", 0.91, 5000, 455_000),
    AlertRecord("PYPL", "C", 65.0, "2025-12-05", "2025-11-17 15:46", 0.91, 5000, 455_000),
    AlertRecord("UBER", "P", 87.0, "2025-11-28", "2025-11-17 15:39", 0.69, 3772, 260_000),
    # 2025-11-18 (additional mid-day alerts)
    AlertRecord("GDX", "P", 70.0, "2025-11-28", "2025-11-18 11:00", 0.55, 5000, 275_000),
    AlertRecord("GDX", "C", 80.0, "2025-11-28", "2025-11-18 12:12", 0.67, 5000, 335_000),
    AlertRecord("GDX", "C", 80.0, "2025-11-28", "2025-11-18 12:21", 0.67, 5000, 335_000),
    AlertRecord("MRNA", "P", 24.0, "2025-11-28", "2025-11-18 12:40", 1.00, 2913, 291_000),
    AlertRecord("GDX", "C", 80.0, "2025-11-28", "2025-11-18 12:45", 0.67, 5000, 335_000),
    AlertRecord("MRNA", "P", 24.0, "2025-11-28", "2025-11-18 12:50", 1.00, 2913, 291_000),
    AlertRecord("MRNA", "P", 24.0, "2025-11-28", "2025-11-18 13:14", 1.00, 2913, 291_000),
    AlertRecord("MRNA", "P", 24.0, "2025-11-28", "2025-11-18 13:24", 1.00, 2913, 291_000),
    # 2025-11-18
    AlertRecord("GOOGL", "C", 312.5, "2025-11-28", "2025-11-18 15:49", 0.84, 5000, 420_000),
    AlertRecord("GOOGL", "C", 312.5, "2025-11-28", "2025-11-18 15:58", 0.84, 5000, 420_000),
    AlertRecord("RIVN", "C", 15.0, "2025-11-28", "2025-11-18 16:01", 0.65, 5000, 325_000),
    # 2025-11-19
    AlertRecord("GDX", "C", 82.5, "2025-11-28", "2025-11-19 10:12", 0.79, 3500, 276_000),
    AlertRecord("GDX", "C", 82.5, "2025-11-28", "2025-11-19 10:13", 0.79, 3500, 276_000),
    AlertRecord("SMCI", "C", 36.0, "2025-11-28", "2025-11-19 11:29", 1.00, 5000, 500_000),
    AlertRecord("SMCI", "C", 36.0, "2025-11-28", "2025-11-19 11:37", 0.93, 5000, 465_000),
    AlertRecord("BMY", "P", 45.0, "2025-11-28", "2025-11-19 12:06", 0.65, 5000, 325_000),
    AlertRecord("BMY", "P", 45.0, "2025-11-28", "2025-11-19 12:08", 0.65, 5000, 325_000),
    AlertRecord("SMCI", "C", 36.0, "2025-11-28", "2025-11-19 12:44", 0.94, 5000, 470_000),
    AlertRecord("SMCI", "C", 36.0, "2025-11-28", "2025-11-19 13:51", 0.87, 5000, 435_000),
    AlertRecord("WMT", "P", 95.0, "2025-11-28", "2025-11-19 14:13", 0.94, 2764, 260_000),
    AlertRecord("WMT", "P", 95.0, "2025-11-28", "2025-11-19 15:04", 1.00, 2804, 280_000),
    # 2025-11-25
    AlertRecord("AAPL", "P", 267.5, "2025-12-05", "2025-11-25 15:10", 0.96, 4614, 443_000),
    AlertRecord("AAPL", "C", 287.5, "2025-12-05", "2025-11-25 15:10", 0.64, 5000, 320_000),
    AlertRecord("SMCI", "C", 33.5, "2025-12-05", "2025-11-25 15:10", 0.94, 5000, 470_000),
    AlertRecord("SMCI", "C", 34.0, "2025-12-05", "2025-11-25 15:10", 0.81, 5000, 405_000),
    AlertRecord("AI", "C", 15.0, "2025-12-05", "2025-11-25 15:10", 0.63, 5000, 315_000),
    AlertRecord("AAPL", "P", 267.5, "2025-12-05", "2025-11-25 15:24", 0.89, 4620, 411_000),
    AlertRecord("AAPL", "C", 287.5, "2025-12-05", "2025-11-25 15:24", 0.61, 5000, 305_000),
    AlertRecord("SMCI", "C", 33.5, "2025-12-05", "2025-11-25 15:24", 0.94, 5000, 470_000),
    AlertRecord("SMCI", "C", 34.0, "2025-12-05", "2025-11-25 15:24", 0.82, 5000, 410_000),
    AlertRecord("AI", "C", 15.0, "2025-12-05", "2025-11-25 15:24", 0.63, 5000, 315_000),
    AlertRecord("GOOGL", "C", 350.0, "2025-12-05", "2025-11-25 15:41", 0.78, 3894, 304_000),
    AlertRecord("SMCI", "C", 34.0, "2025-12-05", "2025-11-25 15:41", 0.83, 5000, 415_000),
    AlertRecord("IWM", "P", 222.0, "2025-12-03", "2025-11-25 16:07", 0.69, 5000, 345_000),
    AlertRecord("GOOGL", "P", 295.0, "2025-12-05", "2025-11-25 16:07", 0.80, 5000, 400_000),
    # 2025-11-26
    AlertRecord("SOFI", "P", 28.5, "2025-12-05", "2025-11-26 15:17", 0.86, 3526, 303_000),
    AlertRecord("FCX", "C", 45.0, "2025-12-12", "2025-11-26 15:29", 0.36, 8218, 296_000),
    AlertRecord("GDX", "P", 76.5, "2025-12-05", "2025-11-26 15:41", 0.42, 13237, 556_000),
    AlertRecord("MRNA", "C", 25.5, "2025-12-05", "2025-11-26 15:41", 0.67, 15344, 1_028_000),
    AlertRecord("MRNA", "C", 26.0, "2025-12-05", "2025-11-26 15:41", 0.50, 8702, 435_000),
    AlertRecord("MRNA", "C", 27.0, "2025-12-05", "2025-11-26 15:41", 0.26, 14658, 381_000),
    AlertRecord("SLV", "C", 50.0, "2025-12-05", "2025-11-26 15:41", 0.58, 19169, 1_112_000),
    AlertRecord("SLV", "C", 50.5, "2025-12-05", "2025-11-26 15:41", 0.46, 10439, 480_000),
    AlertRecord("SLV", "C", 49.0, "2025-12-05", "2025-11-26 15:41", 0.91, 4370, 398_000),
    # 2025-12-01
    AlertRecord("FXI", "P", 39.5, "2025-12-12", "2025-12-01 14:53", 0.51, 5000, 255_000),
    # 2025-12-02
    AlertRecord("INTC", "C", 46.0, "2025-12-05", "2025-12-02 10:54", 0.64, 4353, 279_000),
    AlertRecord("IWM", "P", 240.0, "2025-12-10", "2025-12-02 11:24", 0.97, 4351, 422_000),
    AlertRecord("RIVN", "C", 18.0, "2025-12-05", "2025-12-02 11:31", 0.18, 24340, 438_000),
    AlertRecord("PINS", "C", 27.5, "2025-12-05", "2025-12-02 11:45", 0.20, 11997, 240_000),
    AlertRecord("SOFI", "C", 31.0, "2025-12-12", "2025-12-02 11:46", 0.87, 5000, 435_000),
    AlertRecord("MRNA", "P", 23.5, "2025-12-12", "2025-12-02 11:58", 0.76, 2742, 208_000),
    AlertRecord("SLV", "C", 55.0, "2025-12-05", "2025-12-02 11:58", 0.26, 10496, 273_000),
    AlertRecord("IWM", "P", 241.0, "2025-12-09", "2025-12-02 12:16", 0.95, 2532, 241_000),
    AlertRecord("NVDA", "C", 197.5, "2025-12-12", "2025-12-02 12:16", 0.62, 4451, 276_000),
    AlertRecord("RIVN", "P", 17.0, "2025-12-05", "2025-12-02 12:48", 0.32, 7786, 249_000),
    AlertRecord("NVDA", "C", 197.5, "2025-12-12", "2025-12-02 13:36", 0.60, 4675, 280_000),
    AlertRecord("SGML", "C", 11.0, "2025-12-19", "2025-12-02 13:52", 0.90, 3648, 328_000),
    AlertRecord("SLV", "C", 56.0, "2025-12-12", "2025-12-02 15:57", 0.81, 3532, 286_000),
]


ALERTS: List[AlertRecord] = dedupe_alerts(ALERTS_RAW)


async def fetch_option_aggregates(
    fetcher: DataFetcher,
    option_ticker: str,
    start_date: datetime,
    end_date: datetime,
) -> Optional[pd.DataFrame]:
    """
    Fetch 1-minute aggregate candles for an option contract and return a DataFrame.

    Polygon's aggregate endpoint expects date strings in the path, so request the full
    day range and perform timestamp filtering locally.
    """
    # Include one extra day of buffer after expiration close to capture late prints.
    end_with_buffer = end_date + timedelta(days=1)

    endpoint = (
        f"/v2/aggs/ticker/{option_ticker}/range/1/minute/"
        f"{start_date.strftime('%Y-%m-%d')}/{end_with_buffer.strftime('%Y-%m-%d')}"
    )
    params = {"adjusted": "true", "sort": "asc", "limit": 50_000}

    try:
        response = await fetcher._make_request(endpoint, params)  # pylint: disable=protected-access
    except Exception as exc:  # noqa: BLE001 - surface per-alert failures in results
        print(f"[WARN] Failed to load aggregates for {option_ticker}: {exc}")
        return None

    if not response or "results" not in response:
        return None

    df = pd.DataFrame(response["results"])
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert(EASTERN_TZ)
    df.rename(
        columns={
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "vw": "vwap",
        },
        inplace=True,
    )
    columns = ["timestamp", "open", "high", "low", "close", "volume", "vwap"]
    return df[columns]


def evaluate_alert(alert: AlertRecord, df: Optional[pd.DataFrame]) -> Dict[str, Optional[float]]:
    """
    Reduce the aggregate data into peak performance metrics for the alert.
    """
    summary: Dict[str, Optional[float]] = {
        "symbol": alert.symbol,
        "type": alert.option_type.upper(),
        "strike": alert.strike,
        "expiration": alert.expiration,
        "alert_time": alert.alert_dt.isoformat(),
        "entry_price": alert.entry_price,
        "size": alert.size,
        "premium": alert.premium,
        "polygon_ticker": alert.polygon_option_ticker,
        "samples": None,
        "peak_price": None,
        "peak_time": None,
        "peak_return_pct": None,
        "minutes_to_peak": None,
        "hit_15_pct": None,
        "hit_20_pct": None,
        "hit_25_pct": None,
    }

    if df is None or df.empty:
        return summary

    mask = (df["timestamp"] >= alert.alert_dt) & (df["timestamp"] <= alert.expiration_close)
    filtered = df.loc[mask].copy()
    summary["samples"] = float(len(filtered))

    if filtered.empty:
        return summary

    idx = filtered["high"].idxmax()
    peak_row = filtered.loc[idx]
    peak_price = float(peak_row["high"])
    peak_time = peak_row["timestamp"]
    peak_return = (peak_price - alert.entry_price) / alert.entry_price

    summary.update(
        {
            "peak_price": peak_price,
            "peak_time": peak_time.isoformat(),
            "peak_return_pct": peak_return * 100.0,
            "minutes_to_peak": float((peak_time - alert.alert_dt).total_seconds() / 60.0),
            "hit_15_pct": peak_return >= 0.15,
            "hit_20_pct": peak_return >= 0.20,
            "hit_25_pct": peak_return >= 0.25,
        }
    )

    return summary


async def run_backtest() -> List[Dict[str, Optional[float]]]:
    """Execute the backtest end-to-end."""
    api_key = Config.POLYGON_API_KEY
    if not api_key:
        raise RuntimeError("Config.POLYGON_API_KEY is empty. Populate it before running the backtest.")

    results: List[Dict[str, Optional[float]]] = []
    async with DataFetcher(api_key) as fetcher:
        for alert in ALERTS:
            option_ticker = alert.polygon_option_ticker
            aggregates = await fetch_option_aggregates(fetcher, option_ticker, alert.alert_dt, alert.expiration_close)
            summary = evaluate_alert(alert, aggregates)
            results.append(summary)
            peak_info = summary["peak_return_pct"]
            print(
                f"[INFO] {alert.symbol} {alert.option_type.upper()} {alert.strike} "
                f"{alert.expiration} | entry ${alert.entry_price:.2f} | "
                f"peak return: {peak_info:.2f}%"
                if peak_info is not None
                else f"[WARN] {alert.symbol} {alert.option_type.upper()} {alert.strike} "
                f"{alert.expiration} | no data"
            )

    return results


def summarize(results: List[Dict[str, Optional[float]]]) -> None:
    """Print per-alert and aggregate statistics."""
    df = pd.DataFrame(results)
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "99_cent_store_backtest.csv"
    df.to_csv(output_path, index=False)

    print("\n=== Per-Alert Results ===")
    display_cols = [
        "symbol",
        "type",
        "strike",
        "expiration",
        "alert_time",
        "entry_price",
        "peak_price",
        "peak_return_pct",
        "minutes_to_peak",
        "hit_15_pct",
        "hit_20_pct",
        "hit_25_pct",
    ]
    print(df[display_cols].to_string(index=False, float_format=lambda x: f"{x:.2f}" if pd.notna(x) else "nan"))

    # Aggregate stats ignoring alerts without data.
    realized = df[df["peak_return_pct"].notna()]
    hit_counts = {
        "hit_15_pct": int(realized["hit_15_pct"].sum()),
        "hit_20_pct": int(realized["hit_20_pct"].sum()),
        "hit_25_pct": int(realized["hit_25_pct"].sum()),
    }

    print("\n=== Aggregate Stats ===")
    print(f"Alerts analyzed: {len(df)}")
    print(f"Alerts with price data: {len(realized)}")
    if not realized.empty:
        print(f"Average peak return: {realized['peak_return_pct'].mean():.2f}%")
        print(f"Median peak return: {realized['peak_return_pct'].median():.2f}%")
        print(f"Best peak return: {realized['peak_return_pct'].max():.2f}%")
        print(f"Worst peak return: {realized['peak_return_pct'].min():.2f}%")
        print(
            "Target hits "
            f"(15%: {hit_counts['hit_15_pct']} | 20%: {hit_counts['hit_20_pct']} | 25%: {hit_counts['hit_25_pct']})"
        )
    else:
        print("No price data was available for the analyzed alerts.")

    print(f"\nDetailed CSV written to: {output_path.resolve()}")


def main() -> None:
    results = asyncio.run(run_backtest())
    summarize(results)


if __name__ == "__main__":
    main()

