"""Market hours and holiday detection utilities"""
import datetime
import pytz
from typing import Optional

# US Market holidays for 2025
US_MARKET_HOLIDAYS_2025 = [
    datetime.date(2025, 1, 1),   # New Year's Day
    datetime.date(2025, 1, 20),  # Martin Luther King Jr. Day
    datetime.date(2025, 2, 17),  # Presidents' Day
    datetime.date(2025, 4, 18),  # Good Friday
    datetime.date(2025, 5, 26),  # Memorial Day
    datetime.date(2025, 6, 19),  # Juneteenth
    datetime.date(2025, 7, 4),   # Independence Day
    datetime.date(2025, 9, 1),   # Labor Day
    datetime.date(2025, 11, 27), # Thanksgiving
    datetime.date(2025, 12, 25), # Christmas
]

# US Market holidays for 2026 (add more years as needed)
US_MARKET_HOLIDAYS_2026 = [
    datetime.date(2026, 1, 1),   # New Year's Day
    datetime.date(2026, 1, 19),  # Martin Luther King Jr. Day
    datetime.date(2026, 2, 16),  # Presidents' Day
    datetime.date(2026, 4, 3),   # Good Friday
    datetime.date(2026, 5, 25),  # Memorial Day
    datetime.date(2026, 6, 19),  # Juneteenth
    datetime.date(2026, 7, 3),   # Independence Day (observed)
    datetime.date(2026, 9, 7),   # Labor Day
    datetime.date(2026, 11, 26), # Thanksgiving
    datetime.date(2026, 12, 25), # Christmas
]

ALL_MARKET_HOLIDAYS = US_MARKET_HOLIDAYS_2025 + US_MARKET_HOLIDAYS_2026
EST = pytz.timezone('America/New_York')


class MarketHours:
    """Utility class for checking market hours and trading days"""
    
    @staticmethod
    def is_market_open(check_time: Optional[datetime.datetime] = None, include_extended: bool = True) -> bool:
        """
        Check if the US stock market is open at the given time.

        Regular hours: 9:30 AM - 4:00 PM EST
        Extended hours: 4:00 AM - 8:00 PM EST (pre-market + regular + after-hours)

        Args:
            check_time: Time to check (default: current time)
            include_extended: Include pre-market (4:00-9:30 AM) and after-hours (4:00-8:00 PM)

        Returns:
            True if market is open (regular or extended hours), False otherwise
        """
        if check_time is None:
            check_time = datetime.datetime.now(EST)
        elif check_time.tzinfo is None:
            check_time = EST.localize(check_time)
        else:
            check_time = check_time.astimezone(EST)

        # Check if it's a weekend
        if check_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check if it's a holiday
        if check_time.date() in ALL_MARKET_HOLIDAYS:
            return False

        if include_extended:
            # Extended hours: 4:00 AM - 8:00 PM EST
            extended_start = check_time.replace(hour=4, minute=0, second=0, microsecond=0)
            extended_end = check_time.replace(hour=20, minute=0, second=0, microsecond=0)
            return extended_start <= check_time < extended_end
        else:
            # Regular hours only: 9:30 AM - 4:00 PM EST
            market_open = check_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = check_time.replace(hour=16, minute=0, second=0, microsecond=0)
            return market_open <= check_time < market_close
    
    @staticmethod
    def is_trading_day(check_date: Optional[datetime.date] = None) -> bool:
        """
        Check if the given date is a trading day (weekday, not a holiday)
        
        Args:
            check_date: Date to check (default: today)
            
        Returns:
            True if it's a trading day, False otherwise
        """
        if check_date is None:
            check_date = datetime.datetime.now(EST).date()
        
        # Check if it's a weekend
        if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Check if it's a holiday
        if check_date in ALL_MARKET_HOLIDAYS:
            return False
        
        return True
    
    @staticmethod
    def is_extended_hours(check_time: Optional[datetime.datetime] = None) -> bool:
        """
        Check if we're in extended trading hours (pre-market or after-hours)
        Pre-market: 4:00 AM - 9:30 AM EST
        After-hours: 4:00 PM - 8:00 PM EST
        
        Args:
            check_time: Time to check (default: current time)
            
        Returns:
            True if in extended hours, False otherwise
        """
        est = pytz.timezone('America/New_York')
        
        if check_time is None:
            check_time = datetime.datetime.now(est)
        elif check_time.tzinfo is None:
            check_time = est.localize(check_time)
        else:
            check_time = check_time.astimezone(est)
        
        # Not a trading day
        if not MarketHours.is_trading_day(check_time.date()):
            return False
        
        # Pre-market: 4:00 AM - 9:30 AM
        pre_market_start = check_time.replace(hour=4, minute=0, second=0, microsecond=0)
        market_open = check_time.replace(hour=9, minute=30, second=0, microsecond=0)
        
        if pre_market_start <= check_time < market_open:
            return True
        
        # After-hours: 4:00 PM - 8:00 PM
        market_close = check_time.replace(hour=16, minute=0, second=0, microsecond=0)
        after_hours_end = check_time.replace(hour=20, minute=0, second=0, microsecond=0)
        
        if market_close <= check_time < after_hours_end:
            return True
        
        return False
    
    @staticmethod
    def next_market_open() -> datetime.datetime:
        """
        Get the next market open time
        
        Returns:
            Next market open datetime in EST
        """
        now = datetime.datetime.now(EST)
        
        # Start with next potential open (9:30 AM)
        next_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        
        # If it's after 9:30 AM today, move to tomorrow
        if now.time() >= datetime.time(9, 30):
            next_open += datetime.timedelta(days=1)
        
        # Keep moving forward until we find a trading day
        while not MarketHours.is_trading_day(next_open.date()):
            next_open += datetime.timedelta(days=1)
        
        return next_open
    
    @staticmethod
    def get_market_status() -> dict:
        """
        Get detailed market status
        
        Returns:
            Dictionary with market status information
        """
        est = pytz.timezone('America/New_York')
        now = datetime.datetime.now(est)
        
        is_open = MarketHours.is_market_open(now)
        is_trading_day = MarketHours.is_trading_day(now.date())
        is_extended = MarketHours.is_extended_hours(now)
        
        status = {
            'current_time': now.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'is_open': is_open,
            'is_trading_day': is_trading_day,
            'is_extended_hours': is_extended,
            'day_of_week': now.strftime('%A'),
        }
        
        if not is_open:
            next_open = MarketHours.next_market_open()
            status['next_open'] = next_open.strftime('%Y-%m-%d %H:%M:%S %Z')
            status['hours_until_open'] = (next_open - now).total_seconds() / 3600
        
        if is_open:
            status['session'] = 'Regular'
        elif is_extended:
            if now.hour < 9:
                status['session'] = 'Pre-market'
            else:
                status['session'] = 'After-hours'
        else:
            status['session'] = 'Closed'
        
        return status

    @staticmethod
    def now_est() -> datetime.datetime:
        """Get current time in US/Eastern timezone"""
        return datetime.datetime.now(EST)

    @staticmethod
    def minutes_since_midnight(check_time: Optional[datetime.datetime] = None) -> int:
        """
        Helper to convert a datetime into minutes since midnight in EST.
        Useful for window-based scheduling.
        """
        if check_time is None:
            check_time = MarketHours.now_est()
        elif check_time.tzinfo is None:
            check_time = EST.localize(check_time)
        else:
            check_time = check_time.astimezone(EST)

        return check_time.hour * 60 + check_time.minute
