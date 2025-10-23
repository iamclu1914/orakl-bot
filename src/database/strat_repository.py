"""
Repository layer for STRAT bot database operations
Provides high-level interface for storing/retrieving patterns, bars, and alerts
"""
import logging
from datetime import datetime, date
from typing import List, Optional, Dict
import pytz

from .models import (
    Bar, ClassifiedBar, Pattern, Alert, JobRun,
    TimeframeEnum, PatternTypeEnum, BarTypeEnum, JobStatusEnum
)

logger = logging.getLogger(__name__)


class STRATRepository:
    """Repository for STRAT bot database operations"""

    def __init__(self, session):
        """
        Initialize repository with database session

        Args:
            session: SQLAlchemy session
        """
        self.session = session

    # Bar operations

    def save_bar(self, symbol: str, timeframe: str, bar_data: Dict) -> Bar:
        """
        Save or update a bar in the database

        Args:
            symbol: Stock symbol
            timeframe: '60m', '4h', or '12h'
            bar_data: Dict with keys: t_start_utc, t_end_utc, open, high, low, close, volume

        Returns:
            Saved Bar object
        """
        tf_enum = TimeframeEnum(timeframe)

        # Check if bar already exists
        existing_bar = self.session.query(Bar).filter(
            Bar.symbol == symbol,
            Bar.timeframe == tf_enum,
            Bar.t_start_utc == bar_data['t_start_utc']
        ).first()

        if existing_bar:
            # Update existing bar
            existing_bar.open = bar_data['open']
            existing_bar.high = bar_data['high']
            existing_bar.low = bar_data['low']
            existing_bar.close = bar_data['close']
            existing_bar.volume = bar_data['volume']
            existing_bar.t_end_utc = bar_data['t_end_utc']
            return existing_bar
        else:
            # Create new bar
            bar = Bar(
                symbol=symbol,
                timeframe=tf_enum,
                t_start_utc=bar_data['t_start_utc'],
                t_end_utc=bar_data['t_end_utc'],
                open=bar_data['open'],
                high=bar_data['high'],
                low=bar_data['low'],
                close=bar_data['close'],
                volume=bar_data['volume']
            )
            self.session.add(bar)
            return bar

    def get_bars(self, symbol: str, timeframe: str, start_utc: datetime,
                 end_utc: datetime) -> List[Bar]:
        """
        Get bars for symbol and timeframe within date range

        Args:
            symbol: Stock symbol
            timeframe: '60m', '4h', or '12h'
            start_utc: Start datetime (UTC)
            end_utc: End datetime (UTC)

        Returns:
            List of Bar objects
        """
        tf_enum = TimeframeEnum(timeframe)

        bars = self.session.query(Bar).filter(
            Bar.symbol == symbol,
            Bar.timeframe == tf_enum,
            Bar.t_start_utc >= start_utc,
            Bar.t_start_utc <= end_utc
        ).order_by(Bar.t_start_utc).all()

        return bars

    # Pattern operations

    def save_pattern(self, symbol: str, pattern_type: str, timeframe: str,
                    pattern_data: Dict) -> Pattern:
        """
        Save a detected pattern to database

        Args:
            symbol: Stock symbol
            pattern_type: '3-2-2', '2-2', or '1-3-1'
            timeframe: '60m', '4h', or '12h'
            pattern_data: Dict with pattern metadata

        Returns:
            Saved Pattern object
        """
        pattern = Pattern(
            symbol=symbol,
            pattern_type=PatternTypeEnum(pattern_type),
            timeframe=TimeframeEnum(timeframe),
            completion_bar_start_utc=pattern_data['completion_bar_start_utc'],
            meta=pattern_data.get('meta', {}),
            confidence=pattern_data['confidence'],
            direction=pattern_data['direction'],
            entry_price=pattern_data['entry'],
            stop_price=pattern_data['stop'],
            target_price=pattern_data['target']
        )

        self.session.add(pattern)
        self.session.flush()  # Get pattern ID

        return pattern

    def get_patterns(self, symbol: Optional[str] = None,
                    pattern_type: Optional[str] = None,
                    start_date: Optional[datetime] = None,
                    end_date: Optional[datetime] = None) -> List[Pattern]:
        """
        Query patterns with optional filters

        Args:
            symbol: Filter by symbol (optional)
            pattern_type: Filter by pattern type (optional)
            start_date: Filter by completion date >= (optional)
            end_date: Filter by completion date <= (optional)

        Returns:
            List of Pattern objects
        """
        query = self.session.query(Pattern)

        if symbol:
            query = query.filter(Pattern.symbol == symbol)

        if pattern_type:
            query = query.filter(Pattern.pattern_type == PatternTypeEnum(pattern_type))

        if start_date:
            query = query.filter(Pattern.completion_bar_start_utc >= start_date)

        if end_date:
            query = query.filter(Pattern.completion_bar_start_utc <= end_date)

        return query.order_by(Pattern.completion_bar_start_utc.desc()).all()

    # Alert operations

    def check_duplicate_alert(self, symbol: str, pattern_type: str,
                             timeframe: str, trading_date: date) -> bool:
        """
        Check if alert already sent for this pattern today

        Args:
            symbol: Stock symbol
            pattern_type: '3-2-2', '2-2', or '1-3-1'
            timeframe: '60m', '4h', or '12h'
            trading_date: Trading date (date object)

        Returns:
            True if duplicate exists, False otherwise
        """
        dedup_key = f"{symbol}|{pattern_type}|{timeframe}|{trading_date.isoformat()}"

        exists = self.session.query(Alert).filter(
            Alert.dedup_key == dedup_key
        ).first()

        return exists is not None

    def save_alert(self, pattern_id: int, symbol: str, pattern_type: str,
                  timeframe: str, trading_date: date, payload: Dict) -> Alert:
        """
        Save sent alert to database with deduplication

        Args:
            pattern_id: ID of related Pattern
            symbol: Stock symbol
            pattern_type: '3-2-2', '2-2', or '1-3-1'
            timeframe: '60m', '4h', or '12h'
            trading_date: Trading date (date object)
            payload: Alert payload dict

        Returns:
            Saved Alert object

        Raises:
            ValueError: If duplicate alert exists
        """
        dedup_key = f"{symbol}|{pattern_type}|{timeframe}|{trading_date.isoformat()}"

        # Check for duplicate
        if self.check_duplicate_alert(symbol, pattern_type, timeframe, trading_date):
            raise ValueError(f"Duplicate alert: {dedup_key}")

        alert = Alert(
            pattern_id=pattern_id,
            symbol=symbol,
            pattern_type=PatternTypeEnum(pattern_type),
            timeframe=TimeframeEnum(timeframe),
            alert_ts_utc=datetime.utcnow(),
            payload=payload,
            dedup_key=dedup_key
        )

        self.session.add(alert)
        return alert

    def get_alerts(self, symbol: Optional[str] = None,
                  start_date: Optional[datetime] = None,
                  end_date: Optional[datetime] = None) -> List[Alert]:
        """
        Query alerts with optional filters

        Args:
            symbol: Filter by symbol (optional)
            start_date: Filter by alert time >= (optional)
            end_date: Filter by alert time <= (optional)

        Returns:
            List of Alert objects
        """
        query = self.session.query(Alert)

        if symbol:
            query = query.filter(Alert.symbol == symbol)

        if start_date:
            query = query.filter(Alert.alert_ts_utc >= start_date)

        if end_date:
            query = query.filter(Alert.alert_ts_utc <= end_date)

        return query.order_by(Alert.alert_ts_utc.desc()).all()

    # Job run operations

    def create_job_run(self, job_type: str) -> JobRun:
        """
        Create a new job run record

        Args:
            job_type: '60m', '4h', or '12h'

        Returns:
            New JobRun object
        """
        job_run = JobRun(
            job_type=TimeframeEnum(job_type),
            started_at=datetime.utcnow(),
            status=JobStatusEnum.SUCCESS  # Will be updated on completion
        )

        self.session.add(job_run)
        self.session.flush()  # Get job run ID

        return job_run

    def complete_job_run(self, job_run: JobRun, symbols_scanned: int,
                        patterns_found: int, alerts_sent: int,
                        errors: Optional[List[str]] = None,
                        status: str = 'success'):
        """
        Mark job run as complete

        Args:
            job_run: JobRun object to update
            symbols_scanned: Number of symbols scanned
            patterns_found: Number of patterns detected
            alerts_sent: Number of alerts sent
            errors: List of error messages (optional)
            status: 'success', 'partial', or 'failed'
        """
        job_run.ended_at = datetime.utcnow()
        job_run.symbols_scanned = symbols_scanned
        job_run.patterns_found = patterns_found
        job_run.alerts_sent = alerts_sent
        job_run.errors = errors
        job_run.status = JobStatusEnum(status)

    def get_recent_job_runs(self, job_type: Optional[str] = None,
                           limit: int = 100) -> List[JobRun]:
        """
        Get recent job runs for monitoring

        Args:
            job_type: Filter by job type (optional)
            limit: Maximum number of records to return

        Returns:
            List of JobRun objects
        """
        query = self.session.query(JobRun)

        if job_type:
            query = query.filter(JobRun.job_type == TimeframeEnum(job_type))

        return query.order_by(JobRun.started_at.desc()).limit(limit).all()

    # Statistics and analytics

    def get_pattern_stats(self, start_date: Optional[datetime] = None,
                         end_date: Optional[datetime] = None) -> Dict:
        """
        Get pattern detection statistics

        Args:
            start_date: Filter patterns >= (optional)
            end_date: Filter patterns <= (optional)

        Returns:
            Dict with statistics
        """
        query = self.session.query(Pattern)

        if start_date:
            query = query.filter(Pattern.completion_bar_start_utc >= start_date)

        if end_date:
            query = query.filter(Pattern.completion_bar_start_utc <= end_date)

        patterns = query.all()

        stats = {
            'total_patterns': len(patterns),
            'by_type': {},
            'by_symbol': {},
            'avg_confidence': 0.0
        }

        if patterns:
            # Count by type
            for pattern in patterns:
                pt = pattern.pattern_type.value
                stats['by_type'][pt] = stats['by_type'].get(pt, 0) + 1

                symbol = pattern.symbol
                stats['by_symbol'][symbol] = stats['by_symbol'].get(symbol, 0) + 1

            # Average confidence
            stats['avg_confidence'] = sum(p.confidence for p in patterns) / len(patterns)

        return stats
