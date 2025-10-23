"""
Database Models for STRAT Pattern Detection
SQLAlchemy models for persistent storage per MVP specification
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, JSON,
    ForeignKey, Enum, Index, UniqueConstraint, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import enum

Base = declarative_base()


class TimeframeEnum(enum.Enum):
    """Enum for bar timeframes"""
    SIXTY_MIN = '60m'
    FOUR_HOUR = '4h'
    TWELVE_HOUR = '12h'


class PatternTypeEnum(enum.Enum):
    """Enum for STRAT pattern types"""
    THREE_TWO_TWO = '3-2-2'
    TWO_TWO = '2-2'
    ONE_THREE_ONE = '1-3-1'


class BarTypeEnum(enum.Enum):
    """Enum for STRAT bar types"""
    INSIDE = '1'
    UP = '2U'
    DOWN = '2D'
    OUTSIDE = '3'


class JobStatusEnum(enum.Enum):
    """Enum for job run statuses"""
    SUCCESS = 'success'
    PARTIAL = 'partial'
    FAILED = 'failed'


class Bar(Base):
    """
    Raw OHLCV bar data from Polygon

    Stores bars for all timeframes (60m, 4h, 12h)
    Indexed for fast lookups by symbol, timeframe, and timestamp
    """
    __tablename__ = 'bars'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    timeframe = Column(Enum(TimeframeEnum), nullable=False, index=True)

    # Bar time boundaries (UTC)
    t_start_utc = Column(DateTime(timezone=True), nullable=False, index=True)
    t_end_utc = Column(DateTime(timezone=True), nullable=False)

    # OHLCV data
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Indexes for fast queries
    __table_args__ = (
        Index('ix_bars_symbol_tf_time', 'symbol', 'timeframe', 't_start_utc'),
        UniqueConstraint('symbol', 'timeframe', 't_start_utc', name='uq_bar_identity'),
    )

    def __repr__(self):
        return (f"<Bar(symbol='{self.symbol}', timeframe='{self.timeframe.value}', "
                f"start={self.t_start_utc}, OHLC={self.open}/{self.high}/{self.low}/{self.close})>")


class ClassifiedBar(Base):
    """
    STRAT-classified bars (bar type: 1, 2U, 2D, 3)

    Links to raw Bar data and stores classification result
    Used for pattern detection and historical analysis
    """
    __tablename__ = 'strat_classified_bars'

    id = Column(Integer, primary_key=True, autoincrement=True)
    bar_id = Column(Integer, ForeignKey('bars.id'), nullable=False, index=True)

    # STRAT classification
    bar_type = Column(Enum(BarTypeEnum), nullable=False)

    # Reference to previous bar used for classification
    previous_bar_id = Column(Integer, ForeignKey('bars.id'), nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    bar = relationship("Bar", foreign_keys=[bar_id])
    previous_bar = relationship("Bar", foreign_keys=[previous_bar_id])

    __table_args__ = (
        Index('ix_classified_bar_id', 'bar_id'),
    )

    def __repr__(self):
        return f"<ClassifiedBar(bar_id={self.bar_id}, type='{self.bar_type.value}')>"


class Pattern(Base):
    """
    Detected STRAT patterns (3-2-2, 2-2, 1-3-1)

    Stores pattern metadata, confidence score, and related bars
    Used for alert generation and backtesting
    """
    __tablename__ = 'patterns'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    pattern_type = Column(Enum(PatternTypeEnum), nullable=False, index=True)
    timeframe = Column(Enum(TimeframeEnum), nullable=False, index=True)

    # Pattern completion time (UTC)
    completion_bar_start_utc = Column(DateTime(timezone=True), nullable=False, index=True)

    # Pattern metadata (entry, stop, target, bars involved, etc.)
    meta = Column(JSON, nullable=False)

    # Confidence score (0.0 - 1.0)
    confidence = Column(Float, nullable=False)

    # Trade direction ('CALL' or 'PUT')
    direction = Column(String(4), nullable=False)

    # Entry/Stop/Target prices
    entry_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    alerts = relationship("Alert", back_populates="pattern")

    __table_args__ = (
        Index('ix_pattern_symbol_type_time', 'symbol', 'pattern_type', 'completion_bar_start_utc'),
    )

    def __repr__(self):
        return (f"<Pattern(symbol='{self.symbol}', type='{self.pattern_type.value}', "
                f"confidence={self.confidence:.2f}, direction='{self.direction}')>")


class Alert(Base):
    """
    Sent alerts with deduplication

    Stores all sent alerts with deduplication key
    Prevents duplicate alerts for same pattern on same trading day
    """
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern_id = Column(Integer, ForeignKey('patterns.id'), nullable=False, index=True)

    # Alert identification
    symbol = Column(String(10), nullable=False, index=True)
    pattern_type = Column(Enum(PatternTypeEnum), nullable=False)
    timeframe = Column(Enum(TimeframeEnum), nullable=False)

    # Alert timing (UTC)
    alert_ts_utc = Column(DateTime(timezone=True), nullable=False)

    # Complete alert payload (for audit and debugging)
    payload = Column(JSON, nullable=False)

    # Deduplication key: {symbol}|{pattern}|{timeframe}|{trading_date}
    dedup_key = Column(String(100), unique=True, nullable=False, index=True)

    # Metadata
    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    pattern = relationship("Pattern", back_populates="alerts")

    __table_args__ = (
        UniqueConstraint('dedup_key', name='uq_alert_dedup'),
        Index('ix_alert_symbol_time', 'symbol', 'alert_ts_utc'),
    )

    def __repr__(self):
        return (f"<Alert(symbol='{self.symbol}', pattern='{self.pattern_type.value}', "
                f"dedup_key='{self.dedup_key}')>")


class JobRun(Base):
    """
    Job run audit logs

    Tracks bot scan cycles for monitoring and debugging
    Records symbols scanned, patterns found, alerts sent, and errors
    """
    __tablename__ = 'job_runs'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Job identification
    job_type = Column(Enum(TimeframeEnum), nullable=False, index=True)  # Which timeframe was scanned

    # Job timing
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Job results
    symbols_scanned = Column(Integer, default=0)
    patterns_found = Column(Integer, default=0)
    alerts_sent = Column(Integer, default=0)

    # Errors encountered (list of error messages)
    errors = Column(JSON, nullable=True)

    # Job status
    status = Column(Enum(JobStatusEnum), nullable=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index('ix_job_run_type_time', 'job_type', 'started_at'),
    )

    def __repr__(self):
        return (f"<JobRun(type='{self.job_type.value}', status='{self.status.value}', "
                f"patterns={self.patterns_found}, alerts={self.alerts_sent})>")


# Database connection utilities
class DatabaseManager:
    """Database connection and session management"""

    def __init__(self, database_url: str):
        """
        Initialize database connection

        Args:
            database_url: SQLAlchemy database URL
                - SQLite: 'sqlite:///orakl_bot.db'
                - PostgreSQL: 'postgresql://user:pass@localhost/orakl_bot'
        """
        self.engine = create_engine(database_url, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self):
        """Create all tables if they don't exist"""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop all tables (WARNING: deletes all data!)"""
        Base.metadata.drop_all(bind=self.engine)

    def get_session(self):
        """Get a new database session"""
        return self.SessionLocal()
