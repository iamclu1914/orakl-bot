"""
Initialize STRAT Bot Database
Creates database tables and schema per MVP specification
"""
import os
import logging
from src.database.models import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    """Initialize database with schema"""

    # Database URL - use SQLite for development, PostgreSQL for production
    # Uncomment for PostgreSQL:
    # database_url = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/orakl_bot')

    # SQLite (development)
    database_url = os.getenv('DATABASE_URL', 'sqlite:///orakl_bot.db')

    logger.info(f"Initializing database: {database_url}")

    # Create database manager
    db_manager = DatabaseManager(database_url)

    # Create all tables
    logger.info("Creating tables...")
    db_manager.create_tables()

    logger.info("✅ Database initialized successfully!")
    logger.info("\nCreated tables:")
    logger.info("  - bars: Raw OHLCV data per timeframe")
    logger.info("  - strat_classified_bars: Classified bar types (1, 2U, 2D, 3)")
    logger.info("  - patterns: Detected STRAT patterns with metadata")
    logger.info("  - alerts: Sent alerts with deduplication")
    logger.info("  - job_runs: Job execution audit logs")

    # Test connection
    session = db_manager.get_session()
    try:
        # Simple query to verify connection
        from src.database.models import Bar
        count = session.query(Bar).count()
        logger.info(f"\n✅ Database connection verified (current bars: {count})")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
