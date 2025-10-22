"""
Kafka Consumer Base Class for Real-Time Data Streaming
Consumes from your existing Polygon → Kafka pipeline
"""
import asyncio
import json
import os
from typing import List, Set, Dict
from datetime import datetime
import pytz
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from src.utils.logger import logger


class KafkaConsumerBase:
    """Base class for consuming Polygon data from Kafka topics"""

    def __init__(self, bot_name: str, topics: List[str]):
        self.bot_name = bot_name
        self.topics = topics

        # Kafka configuration from environment
        self.bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(',')
        self.consumer_group = os.getenv('KAFKA_CONSUMER_GROUP', 'orakl-bot-consumers')

        # Authentication (if needed)
        self.kafka_username = os.getenv('KAFKA_USERNAME')
        self.kafka_password = os.getenv('KAFKA_PASSWORD')

        # Consumer instance
        self.consumer = None
        self.running = False

        # Market hours
        self.tz = pytz.timezone('America/New_York')

        # Deduplication cache
        self.seen_signals: Set[str] = set()
        self.cache_clear_interval = 300  # Clear cache every 5 minutes

    def is_market_hours(self) -> bool:
        """Check if market is open (9:30 AM - 4:00 PM ET, Mon-Fri)"""
        now = datetime.now(self.tz)

        # Check if weekend
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Check if within trading hours
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

        return market_open <= now <= market_close

    def connect(self):
        """Connect to Kafka and subscribe to topics"""
        try:
            logger.info(f"[{self.bot_name}] Connecting to Kafka: {self.bootstrap_servers}")
            logger.info(f"[{self.bot_name}] Topics: {', '.join(self.topics)}")
            logger.info(f"[{self.bot_name}] Consumer Group: {self.consumer_group}")

            # Build consumer config for Confluent Cloud
            config = {
                'bootstrap_servers': self.bootstrap_servers,
                'group_id': self.consumer_group,
                'auto_offset_reset': 'latest',  # Start from latest messages
                'enable_auto_commit': True,
                'value_deserializer': lambda m: json.loads(m.decode('utf-8')),
                'session_timeout_ms': 45000,
                'heartbeat_interval_ms': 3000,
                'max_poll_interval_ms': 300000,
                'max_poll_records': 500,
            }

            # Confluent Cloud requires SASL_SSL authentication
            if self.kafka_username and self.kafka_password:
                config.update({
                    'security_protocol': 'SASL_SSL',
                    'sasl_mechanism': 'PLAIN',
                    'sasl_plain_username': self.kafka_username,
                    'sasl_plain_password': self.kafka_password,
                })
                logger.info(f"[{self.bot_name}] Using Confluent Cloud SASL_SSL authentication")
            else:
                logger.warning(f"[{self.bot_name}] No Kafka credentials - connection may fail")

            # Create consumer
            self.consumer = KafkaConsumer(*self.topics, **config)
            self.running = True

            logger.info(f"[{self.bot_name}] ✅ Connected to Kafka successfully")
            logger.info(f"[{self.bot_name}] Listening for messages...")

            return True

        except KafkaError as e:
            logger.error(f"[{self.bot_name}] ❌ Kafka connection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"[{self.bot_name}] ❌ Unexpected error: {e}")
            return False

    async def consume(self):
        """Consume messages from Kafka topics"""
        if not self.consumer:
            logger.error(f"[{self.bot_name}] Consumer not connected")
            return

        try:
            # Start cache clearing task
            asyncio.create_task(self.clear_cache_periodically())

            logger.info(f"[{self.bot_name}] Starting message consumption...")

            # Consume messages
            for message in self.consumer:
                if not self.running:
                    break

                try:
                    # Parse message
                    data = message.value
                    topic = message.topic

                    # Log every 100 messages
                    if not hasattr(self, '_msg_count'):
                        self._msg_count = 0
                    self._msg_count += 1

                    if self._msg_count % 100 == 0:
                        logger.info(f"[{self.bot_name}] Processed {self._msg_count} messages from {topic}")

                    # Process message (override in subclasses)
                    await self.process_message(data, topic)

                except json.JSONDecodeError as e:
                    logger.error(f"[{self.bot_name}] JSON decode error: {e}")
                    continue
                except Exception as e:
                    logger.error(f"[{self.bot_name}] Message processing error: {e}")
                    continue

        except Exception as e:
            logger.error(f"[{self.bot_name}] Consume loop error: {e}")
        finally:
            self.close()

    async def process_message(self, data: Dict, topic: str):
        """Process individual message - override in subclasses"""
        raise NotImplementedError("Subclasses must implement process_message()")

    def generate_signal_id(self, symbol: str, timestamp: int, trade_type: str) -> str:
        """Generate unique signal ID for deduplication"""
        return f"{symbol}_{timestamp}_{trade_type}"

    def is_duplicate_signal(self, signal_id: str) -> bool:
        """Check if signal already processed"""
        if signal_id in self.seen_signals:
            return True
        self.seen_signals.add(signal_id)
        return False

    async def clear_cache_periodically(self):
        """Clear signal cache every 5 minutes"""
        while self.running:
            await asyncio.sleep(self.cache_clear_interval)
            cache_size = len(self.seen_signals)
            self.seen_signals.clear()
            logger.info(f"[{self.bot_name}] Cleared signal cache ({cache_size} entries)")

    def close(self):
        """Close Kafka consumer"""
        self.running = False
        if self.consumer:
            logger.info(f"[{self.bot_name}] Closing Kafka consumer...")
            self.consumer.close()
            logger.info(f"[{self.bot_name}] Consumer closed")

    async def run(self):
        """Main run loop"""
        try:
            # Connect to Kafka
            if not self.connect():
                logger.error(f"[{self.bot_name}] Failed to connect to Kafka")
                return

            # Start consuming
            await self.consume()

        except KeyboardInterrupt:
            logger.info(f"[{self.bot_name}] Shutdown requested")
        except Exception as e:
            logger.error(f"[{self.bot_name}] Run error: {e}")
        finally:
            self.close()
