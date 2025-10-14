"""Check bot status and scanning intervals"""
from src.config import Config
from datetime import datetime
import pytz

print("=" * 70)
print("  ORAKL Bot v2.0 - Scanning Intervals & Status")
print("=" * 70)
print()
print("BOT SCAN INTERVALS:")
print("-" * 70)
print(f"1. Orakl Flow Bot      : {Config.TRADY_FLOW_INTERVAL:3d}s ({Config.TRADY_FLOW_INTERVAL/60:.1f} minutes)")
print(f"2. Bullseye Bot        : {Config.BULLSEYE_INTERVAL:3d}s ({Config.BULLSEYE_INTERVAL/60:.1f} minutes)")
print(f"3. Scalps Bot          : {Config.SCALPS_INTERVAL:3d}s ({Config.SCALPS_INTERVAL/60:.1f} minutes)")
print(f"4. Sweeps Bot          : {Config.SWEEPS_INTERVAL:3d}s ({Config.SWEEPS_INTERVAL/60:.1f} minutes)")
print(f"5. Golden Sweeps Bot   : {Config.GOLDEN_SWEEPS_INTERVAL:3d}s ({Config.GOLDEN_SWEEPS_INTERVAL/60:.1f} minutes)")
print(f"6. Darkpool Bot        : {Config.DARKPOOL_INTERVAL:3d}s ({Config.DARKPOOL_INTERVAL/60:.1f} minutes)")
print(f"7. Breakouts Bot       : {Config.BREAKOUTS_INTERVAL:3d}s ({Config.BREAKOUTS_INTERVAL/60:.1f} minutes)")
print(f"8. Unusual Volume Bot  : {Config.UNUSUAL_VOLUME_INTERVAL:3d}s ({Config.UNUSUAL_VOLUME_INTERVAL/60:.1f} minutes)")
print()

# Get current time in ET
et_tz = pytz.timezone('US/Eastern')
current_time_et = datetime.now(et_tz)
print(f"CURRENT TIME (ET): {current_time_et.strftime('%I:%M %p')}")
print(f"Date: {current_time_et.strftime('%A, %B %d, %Y')}")
print()

# Check market hours
hour = current_time_et.hour
minute = current_time_et.minute
weekday = current_time_et.weekday()

market_open_time = current_time_et.replace(hour=9, minute=30, second=0)
market_close_time = current_time_et.replace(hour=16, minute=0, second=0)

is_market_hours = (
    weekday < 5 and  # Monday-Friday
    market_open_time <= current_time_et <= market_close_time
)

print("MARKET STATUS:")
print("-" * 70)
if weekday >= 5:
    print("Status: CLOSED (Weekend)")
    print("Next Open: Monday 9:30 AM ET")
elif current_time_et < market_open_time:
    print("Status: PRE-MARKET")
    minutes_until_open = int((market_open_time - current_time_et).total_seconds() / 60)
    print(f"Opens in: {minutes_until_open} minutes ({market_open_time.strftime('%I:%M %p')})")
elif current_time_et > market_close_time:
    print("Status: AFTER-HOURS (Market Closed)")
    print("Next Open: Tomorrow 9:30 AM ET")
else:
    print("Status: OPEN (Trading Hours)")
    minutes_until_close = int((market_close_time - current_time_et).total_seconds() / 60)
    print(f"Closes in: {minutes_until_close} minutes ({market_close_time.strftime('%I:%M %p')})")
print()

print("SIGNAL THRESHOLDS:")
print("-" * 70)
print(f"Min Premium (General)  : ${Config.MIN_PREMIUM:,.0f}")
print(f"Golden Sweeps Premium  : ${Config.GOLDEN_MIN_PREMIUM:,.0f}")
print(f"Sweeps Premium         : ${Config.SWEEPS_MIN_PREMIUM:,.0f}")
print(f"Bullseye Premium       : ${Config.BULLSEYE_MIN_PREMIUM:,.0f}")
print(f"Scalps Premium         : ${Config.SCALPS_MIN_PREMIUM:,.0f}")
print(f"Volume Ratio (Unusual) : {Config.MIN_VOLUME_RATIO}x")
print(f"Absolute Volume (Min)  : {Config.MIN_ABSOLUTE_VOLUME:,} shares")
print()

print("WHY YOU MIGHT NOT SEE SIGNALS:")
print("-" * 70)
if not is_market_hours:
    print("1. Market is CLOSED - Bots scan but find no activity")
    print("   -> Signals only appear during trading hours (9:30 AM - 4:00 PM ET)")
else:
    print("1. Market IS OPEN - Bots should be finding signals")
    print("   -> If no signals, thresholds may be too high or low activity")

print("2. Thresholds may be high:")
print(f"   -> Golden Sweeps needs $1M+ premium")
print(f"   -> Sweeps need $50k+ premium")
print(f"   -> Volume needs 3x+ average")
print("3. Signals may be in different channels than expected")
print("4. Discord may need refresh (Ctrl+R)")
print("5. Low volatility day (fewer signals on quiet days)")
print()
print("=" * 70)

