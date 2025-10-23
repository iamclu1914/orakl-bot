"""
Bar Alignment Utilities for STRAT Pattern Detection
Validates that Polygon bars align to expected clock hours per MVP specification
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz

logger = logging.getLogger(__name__)


def get_bar_for_hour(bars: List[Dict], target_hour: int, tz=pytz.timezone('America/New_York')) -> Optional[Dict]:
    """
    Get bar that CONTAINS the target hour (e.g., 8:00 AM - 8:59:59 AM)

    Args:
        bars: List of bar dicts with 't' (timestamp in ms)
        target_hour: Target hour (0-23) in specified timezone
        tz: Timezone for hour calculation

    Returns:
        Bar dict that contains the target hour, or None if not found

    Example:
        # Get 8:00 AM bar (any bar containing 8:00:00 - 8:59:59)
        bar_8am = get_bar_for_hour(bars, 8, pytz.timezone('America/New_York'))
    """
    for bar in bars:
        if 't' not in bar:
            continue

        bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)

        # For 60-minute bars, end is start + 60 minutes
        # For other timeframes, this needs to be parameterized
        bar_end = bar_start + timedelta(minutes=60)

        # Create target time at the specified hour
        target_time = bar_start.replace(hour=target_hour, minute=0, second=0, microsecond=0)

        # Check if target hour falls within this bar's range
        if bar_start <= target_time < bar_end:
            logger.debug(f"Found bar for hour {target_hour}: {bar_start} - {bar_end}")
            return bar

    logger.warning(f"No bar found containing hour {target_hour} in {len(bars)} bars")
    return None


def get_bars_for_hours(bars: List[Dict], target_hours: List[int],
                       timeframe_minutes: int = 60,
                       tz=pytz.timezone('America/New_York')) -> Dict[int, Optional[Dict]]:
    """
    Get bars for multiple target hours with alignment validation

    Args:
        bars: List of bar dicts with 't' (timestamp in ms)
        target_hours: List of target hours (e.g., [8, 9, 10])
        timeframe_minutes: Bar timeframe in minutes (60, 240, 720)
        tz: Timezone for hour calculation

    Returns:
        Dict mapping hour -> bar (or None if not found)

    Example:
        # Get 8am, 9am, 10am bars for 3-2-2 pattern
        pattern_bars = get_bars_for_hours(bars, [8, 9, 10], timeframe_minutes=60)
    """
    result = {}

    for target_hour in target_hours:
        found_bar = None

        for bar in bars:
            if 't' not in bar:
                continue

            bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)
            bar_end = bar_start + timedelta(minutes=timeframe_minutes)

            # Create target time at the specified hour
            target_time = bar_start.replace(hour=target_hour, minute=0, second=0, microsecond=0)

            # Check if target hour falls within this bar's range
            if bar_start <= target_time < bar_end:
                found_bar = bar
                logger.debug(f"Found bar for hour {target_hour}: {bar_start} - {bar_end}")
                break

        if found_bar:
            result[target_hour] = found_bar
        else:
            result[target_hour] = None
            logger.warning(f"No bar found containing hour {target_hour}")

    return result


def validate_bar_alignment(bar: Dict, expected_hour: int,
                          timeframe_minutes: int = 60,
                          tz=pytz.timezone('America/New_York'),
                          tolerance_seconds: int = 60) -> bool:
    """
    Validate that a bar aligns to expected clock hour within tolerance

    Args:
        bar: Bar dict with 't' (timestamp in ms)
        expected_hour: Expected hour for bar start (0-23)
        timeframe_minutes: Bar timeframe in minutes
        tz: Timezone for validation
        tolerance_seconds: Allowed deviation in seconds (default: 60)

    Returns:
        True if bar aligns to expected hour within tolerance

    Example:
        # Validate 8:00 AM bar starts within 1 minute of 8:00:00
        is_aligned = validate_bar_alignment(bar, 8, timeframe_minutes=60)
    """
    if 't' not in bar:
        logger.error("Bar missing timestamp field 't'")
        return False

    bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)
    expected_start = bar_start.replace(hour=expected_hour, minute=0, second=0, microsecond=0)

    # Calculate time difference in seconds
    time_diff = abs((bar_start - expected_start).total_seconds())

    if time_diff <= tolerance_seconds:
        logger.debug(f"Bar aligned: hour={expected_hour}, diff={time_diff}s, start={bar_start}")
        return True
    else:
        logger.warning(
            f"Bar misaligned: expected hour={expected_hour}, "
            f"actual_start={bar_start}, diff={time_diff}s (tolerance={tolerance_seconds}s)"
        )
        return False


def get_bar_boundaries_et(timeframe: str, ref_time: datetime) -> tuple[datetime, datetime]:
    """
    Compute exact bar boundaries in ET for a given timeframe

    Args:
        timeframe: '60m', '4h', or '12h'
        ref_time: Reference time (already in ET timezone)

    Returns:
        (start_et, end_et) tuple for the bar containing ref_time

    Example:
        # Get boundaries for 8am bar
        ref = datetime(2025, 10, 22, 8, 30, tzinfo=pytz.timezone('America/New_York'))
        start, end = get_bar_boundaries_et('60m', ref)
        # Returns: (2025-10-22 08:00:00 ET, 2025-10-22 08:59:59 ET)
    """
    est = pytz.timezone('America/New_York')

    if timeframe == '60m':
        # Align to hour boundary
        start = ref_time.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1) - timedelta(microseconds=1)

    elif timeframe == '4h':
        # Align to 4-hour boundaries: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
        hour_boundary = (ref_time.hour // 4) * 4
        start = ref_time.replace(hour=hour_boundary, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=4) - timedelta(microseconds=1)

    elif timeframe == '12h':
        # Align to 12-hour boundaries: 08:00-19:59, 20:00-07:59
        if 8 <= ref_time.hour < 20:
            # Day session: 08:00 - 19:59
            start = ref_time.replace(hour=8, minute=0, second=0, microsecond=0)
            end = ref_time.replace(hour=19, minute=59, second=59, microsecond=999999)
        else:
            # Night session: 20:00 - 07:59 (next day)
            if ref_time.hour >= 20:
                start = ref_time.replace(hour=20, minute=0, second=0, microsecond=0)
                end = (ref_time + timedelta(days=1)).replace(hour=7, minute=59, second=59, microsecond=999999)
            else:  # hour < 8
                start = (ref_time - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
                end = ref_time.replace(hour=7, minute=59, second=59, microsecond=999999)
    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    return start, end


def log_bar_alignment_info(bars: List[Dict], pattern_name: str,
                          expected_hours: List[int],
                          tz=pytz.timezone('America/New_York')):
    """
    Log detailed bar alignment information for debugging

    Args:
        bars: List of bars to analyze
        pattern_name: Pattern name (e.g., "3-2-2 Reversal")
        expected_hours: Expected hours for this pattern
        tz: Timezone for display
    """
    logger.info(f"=== Bar Alignment Analysis for {pattern_name} ===")
    logger.info(f"Expected hours: {expected_hours}")
    logger.info(f"Total bars: {len(bars)}")

    for i, bar in enumerate(bars):
        if 't' not in bar:
            logger.warning(f"Bar {i}: Missing timestamp")
            continue

        bar_start = datetime.fromtimestamp(bar['t'] / 1000, tz=tz)
        logger.info(
            f"Bar {i}: {bar_start.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"OHLC: {bar.get('o', 0):.2f}/{bar.get('h', 0):.2f}/"
            f"{bar.get('l', 0):.2f}/{bar.get('c', 0):.2f}"
        )

    logger.info("=== End Bar Alignment Analysis ===")


def get_previous_bar(bars: List[Dict], current_bar: Dict) -> Optional[Dict]:
    """
    Get the bar immediately before current_bar in the sequence

    This is more robust than searching for specific hours (e.g., hour==0)

    Args:
        bars: List of bars in chronological order
        current_bar: The current bar

    Returns:
        Previous bar or None if current_bar is first

    Example:
        # Get bar before 4am bar (for 2-2 pattern target calculation)
        bar_4am = get_bar_for_hour(bars, 4)
        bar_before = get_previous_bar(bars, bar_4am)
    """
    if not bars or current_bar not in bars:
        logger.warning("Current bar not found in bars list")
        return None

    current_index = bars.index(current_bar)

    if current_index == 0:
        logger.warning("Current bar is first bar, no previous bar available")
        return None

    return bars[current_index - 1]
