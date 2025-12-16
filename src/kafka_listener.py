"""
ORAKL Kafka Flow Listener - Event-Driven Architecture

Consumes real-time options flow from the 'processed-flows' Kafka topic
(shared with Dashboard) and dispatches to League A bots with millisecond latency.

Key Features:
- Confluent Cloud SASL_SSL authentication
- Pre-filtering below premium threshold (saves CPU)
- Fire-and-forget async dispatch (non-blocking)
- Health monitoring for automatic REST fallback
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Any
from confluent_kafka import Consumer, KafkaError, KafkaException

from src.config import Config

logger = logging.getLogger(__name__)


# Dashboard Kafka message format:
# {
#     "id": "O:CRDO260618C00140000-1765378610017-236331966",  <- Contract ID (split at '-')
#     "ticker": "CRDO",                                        <- Underlying symbol
#     "premiumValue": 150000,
#     "strike": 140,
#     "exp": "2026-06-18",
#     "type": "call",
#     "size": 100,
#     "price": 1.50,
#     "timestamp": "2024-12-10T...",
#     ...
# }


class KafkaHealthMonitor:
    """
    Tracks Kafka connection health for automatic fallback triggering.
    
    If no messages received for KAFKA_FALLBACK_TIMEOUT seconds,
    signals that REST polling fallback should activate.
    """
    
    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = timeout_seconds
        self.last_message_time: Optional[float] = None
        self.connected = False
        self.total_messages = 0
        self.filtered_messages = 0
        self.errors = 0
        
    def record_message(self):
        """Record that a message was received"""
        self.last_message_time = time.time()
        self.total_messages += 1
        self.connected = True
        
    def record_filtered(self):
        """Record that a message was filtered out"""
        self.filtered_messages += 1
        
    def record_error(self):
        """Record a consumer error"""
        self.errors += 1
        
    def is_healthy(self) -> bool:
        """Check if Kafka connection is healthy"""
        if not self.connected:
            return False
        if self.last_message_time is None:
            return False
        
        elapsed = time.time() - self.last_message_time
        return elapsed < self.timeout_seconds
    
    def should_fallback(self) -> bool:
        """Check if system should fall back to REST polling"""
        if not self.connected:
            return True
        if self.last_message_time is None:
            return False  # Haven't received first message yet, don't fallback
        
        elapsed = time.time() - self.last_message_time
        return elapsed >= self.timeout_seconds
    
    def get_stats(self) -> Dict[str, Any]:
        """Get health monitor statistics"""
        return {
            'connected': self.connected,
            'healthy': self.is_healthy(),
            'total_messages': self.total_messages,
            'filtered_messages': self.filtered_messages,
            'pass_rate': (self.total_messages - self.filtered_messages) / max(1, self.total_messages),
            'errors': self.errors,
            'last_message_age': time.time() - self.last_message_time if self.last_message_time else None
        }


class KafkaFlowListener:
    """
    Real-time Kafka consumer for options flow events.
    
    Connects to Confluent Cloud's 'processed-flows' topic and dispatches
    enriched trade events to League A bots with minimal latency.
    
    Usage:
        async def handle_event(trade_data):
            await bot_manager.process_single_event(trade_data)
        
        listener = KafkaFlowListener(callback=handle_event)
        await listener.start()
    """
    
    def __init__(
        self,
        callback: Callable[[Dict], Any],
        on_disconnect: Optional[Callable[[], Any]] = None,
        on_reconnect: Optional[Callable[[], Any]] = None
    ):
        """
        Initialize Kafka listener.
        
        Args:
            callback: Async function to call with each trade event
            on_disconnect: Optional callback when Kafka disconnects (triggers fallback)
            on_reconnect: Optional callback when Kafka reconnects
        """
        self.callback = callback
        self.on_disconnect = on_disconnect
        self.on_reconnect = on_reconnect
        self.consumer: Optional[Consumer] = None
        self.running = False
        self.health = KafkaHealthMonitor(Config.KAFKA_FALLBACK_TIMEOUT)
        self._fallback_triggered = False
        self._last_stats_log_ts: float = time.time()
        self._stats_log_interval_seconds: int = int(getattr(Config, "KAFKA_STATS_LOG_INTERVAL_SECONDS", 60))
        
    def _get_kafka_config(self) -> Dict[str, str]:
        """
        Build Kafka consumer configuration for Confluent Cloud.
        
        Returns config dict compatible with confluent-kafka Consumer.
        """
        if not all([Config.KAFKA_BROKERS, Config.KAFKA_API_KEY, Config.KAFKA_API_SECRET]):
            raise ValueError("Missing Kafka credentials. Check KAFKA_BROKERS, KAFKA_API_KEY, KAFKA_API_SECRET")
        
        return {
            'bootstrap.servers': Config.KAFKA_BROKERS,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'PLAIN',
            'sasl.username': Config.KAFKA_API_KEY,
            'sasl.password': Config.KAFKA_API_SECRET,
            'group.id': Config.KAFKA_GROUP_ID,
            'auto.offset.reset': 'latest',  # Only new trades, not history
            'enable.auto.commit': True,
            'session.timeout.ms': 45000,
            'heartbeat.interval.ms': 15000,
        }
    
    def _parse_message(self, msg_value: bytes) -> Optional[Dict]:
        """
        Parse Kafka message and map to ORAKL format.
        
        Dashboard message format:
        {
            "id": "O:CRDO260618C00140000-1765378610017-236331966",  <- Contract ID with suffix
            "ticker": "CRDO",                                        <- Underlying symbol
            "premiumValue": 150000,
            "strike": 140,
            "exp": "2026-06-18",
            "type": "call",
            ...
        }
        
        Args:
            msg_value: Raw message bytes from Kafka
            
        Returns:
            Parsed trade dict in ORAKL format, or None if invalid
        """
        try:
            raw_data = json.loads(msg_value.decode('utf-8'))

            def _coerce_int(value: Any, default: int = 0) -> int:
                try:
                    if value is None:
                        return default
                    if isinstance(value, bool):
                        return default
                    if isinstance(value, (int, float)):
                        return int(value)
                    s = str(value).strip()
                    if not s:
                        return default
                    return int(float(s))
                except Exception:
                    return default

            def _coerce_float(value: Any, default: float = 0.0) -> float:
                try:
                    if value is None:
                        return default
                    if isinstance(value, bool):
                        return default
                    if isinstance(value, (int, float)):
                        return float(value)
                    s = str(value).strip()
                    if not s:
                        return default
                    return float(s)
                except Exception:
                    return default
            
            # Extract the FULL contract ID from 'id' field
            # Format: "O:CRDO260618C00140000-1765378610017-236331966"
            # We need: "O:CRDO260618C00140000" (before first hyphen)
            raw_id = raw_data.get('id', '')
            if '-' in raw_id:
                option_symbol = raw_id.split('-')[0]
            else:
                option_symbol = raw_id
            
            # Validate we have a proper contract ID
            if not option_symbol or not any(c.isdigit() for c in option_symbol):
                logger.warning(f"Invalid option symbol extracted from id: '{raw_id}' -> '{option_symbol}'")
                return None
            
            # Build trade data with CORRECT mappings
            # Kafka producers can use different field names; normalize aggressively.
            symbol_value = raw_data.get('ticker') or raw_data.get('symbol') or raw_data.get('underlying') or ''
            premium_value = _coerce_float(raw_data.get('premiumValue', 0.0), 0.0)
            strike_value = _coerce_float(raw_data.get('strike', 0.0), 0.0)
            trade_type_value = (raw_data.get('type', '') or '').lower()

            # Contract quantity may arrive under different keys depending on producer/version.
            raw_size = (
                raw_data.get('size')
                if raw_data.get('size') not in (None, "", 0, "0")
                else None
            )
            if raw_size is None:
                raw_size = raw_data.get('contracts')
            if raw_size is None:
                raw_size = raw_data.get('quantity')
            if raw_size is None:
                raw_size = raw_data.get('qty')
            if raw_size is None:
                raw_size = raw_data.get('trade_size')
            if raw_size is None:
                raw_size = raw_data.get('tradeSize')
            trade_size_value = _coerce_int(raw_size, 0)

            # Per-contract print price may also vary.
            trade_price_value = _coerce_float(
                raw_data.get('price')
                if raw_data.get('price') not in (None, "")
                else raw_data.get('tradePrice', raw_data.get('avgPrice', 0.0)),
                0.0,
            )

            trade_data = {
                'contract_ticker': option_symbol,  # FULL contract ID (e.g., "O:CRDO260618C00140000")
                'symbol': symbol_value,  # Underlying stock symbol (e.g., "CRDO")
                'premium': premium_value,
                'strike_price': strike_value,
                'expiration_date': raw_data.get('exp', ''),
                'contract_type': trade_type_value,
                'trade_size': trade_size_value,
                'trade_price': trade_price_value,
            }
            
            # Copy additional fields
            for key in ['timestamp', 'side', 'is_sweep', 'exchange', 'conditions']:
                if key in raw_data:
                    trade_data[key] = raw_data[key]
            
            # Add event timestamp
            if 'timestamp' in raw_data:
                trade_data['event_timestamp'] = raw_data['timestamp']
            else:
                trade_data['event_timestamp'] = datetime.utcnow().isoformat()
            
            logger.debug(
                f"Kafka parsed: {trade_data['symbol']} | "
                f"Contract: {trade_data['contract_ticker']} | "
                f"Premium: ${trade_data['premium']:,.0f}"
            )
            
            return trade_data
            
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to parse Kafka message: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing Kafka message: {e}")
            return None
    
    def _extract_root_symbol(self, contract_ticker: str) -> str:
        """
        Extract raw root symbol from options contract ticker for logging.
        
        NOTE: This is just for logging/display. The TradeEnricher handles
        proper parsing and index mapping for API calls.
        
        Args:
            contract_ticker: e.g., "O:AAPL240216C00185000"
            
        Returns:
            Root symbol (e.g., "AAPL", "SPXW") - NOT normalized
        """
        ticker = contract_ticker
        
        # Strip O: prefix if present
        if ticker.startswith('O:'):
            ticker = ticker[2:]
        
        # Extract letters at the beginning
        root = ''
        for char in ticker:
            if char.isalpha():
                root += char
            else:
                break
        
        return root if root else ticker[:4]
    
    def _passes_filter(self, trade_data: Dict) -> bool:
        """
        Pre-filter trades below premium threshold.
        
        This saves CPU by not processing small trades that won't
        qualify for any bot alerts anyway.
        """
        premium = trade_data.get('premium', 0)
        try:
            premium = float(premium)
        except (TypeError, ValueError):
            return False
        
        if premium < Config.KAFKA_MIN_PREMIUM_FILTER:
            self.health.record_filtered()
            return False
        
        return True
    
    async def start(self):
        """
        Start the Kafka consumer loop.
        
        This runs indefinitely, consuming messages and dispatching
        to bots via the callback. Uses fire-and-forget pattern to
        avoid blocking the consumer loop.
        """
        logger.info(f"Starting Kafka listener on topic: {Config.KAFKA_TOPIC}")
        logger.info(f"  Group ID: {Config.KAFKA_GROUP_ID}")
        logger.info(f"  Pre-filter threshold: ${Config.KAFKA_MIN_PREMIUM_FILTER:,.0f}")
        
        try:
            config = self._get_kafka_config()
            self.consumer = Consumer(config)
            self.consumer.subscribe([Config.KAFKA_TOPIC])
            self.running = True
            self.health.connected = True
            
            logger.info("Kafka consumer connected successfully")
            
            # Main consumer loop
            while self.running:
                # Non-blocking poll with short timeout
                msg = self.consumer.poll(0.1)
                
                if msg is None:
                    # CRITICAL: Yield to event loop to prevent blocking
                    await asyncio.sleep(0.01)
                    
                    # Check for fallback condition
                    if self.health.should_fallback() and not self._fallback_triggered:
                        logger.warning("Kafka connection unhealthy, triggering REST fallback")
                        self._fallback_triggered = True
                        if self.on_disconnect:
                            asyncio.create_task(self._safe_callback(self.on_disconnect))
                    continue
                
                if msg.error():
                    self._handle_error(msg.error())
                    continue
                
                # Record successful message receipt
                self.health.record_message()
                self._maybe_log_stats()
                
                # Check for reconnection after fallback
                if self._fallback_triggered:
                    logger.info("Kafka reconnected, resuming real-time mode")
                    self._fallback_triggered = False
                    if self.on_reconnect:
                        asyncio.create_task(self._safe_callback(self.on_reconnect))
                
                # Parse message
                trade_data = self._parse_message(msg.value())
                if trade_data is None:
                    continue
                
                # Apply pre-filter
                if not self._passes_filter(trade_data):
                    continue
                
                # FIRE AND FORGET: Dispatch without awaiting
                # This prevents slow enrichment from blocking the consumer
                asyncio.create_task(self._safe_dispatch(trade_data))
                
        except KafkaException as e:
            logger.error(f"Kafka exception: {e}")
            self.health.record_error()
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Kafka listener: {e}")
            self.health.record_error()
            raise
        finally:
            await self.stop()

    def _maybe_log_stats(self) -> None:
        """Periodically emit Kafka throughput + filter stats at INFO."""
        now = time.time()
        if (now - self._last_stats_log_ts) < self._stats_log_interval_seconds:
            return
        stats = self.health.get_stats()
        logger.info(
            "Kafka stats: total=%d filtered=%d pass_rate=%.1f%% last_msg_age=%ss errors=%d",
            stats.get("total_messages", 0),
            stats.get("filtered_messages", 0),
            float(stats.get("pass_rate", 0.0)) * 100.0,
            f"{stats.get('last_message_age'):.1f}" if stats.get("last_message_age") is not None else "n/a",
            stats.get("errors", 0),
        )
        self._last_stats_log_ts = now
    
    async def _safe_dispatch(self, trade_data: Dict):
        """
        Safely dispatch trade event to callback with error handling.
        """
        try:
            result = self.callback(trade_data)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Error dispatching trade event: {e}")
    
    async def _safe_callback(self, callback: Callable):
        """
        Safely call a callback function.
        """
        try:
            result = callback()
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Error in callback: {e}")
    
    def _handle_error(self, error: KafkaError):
        """Handle Kafka consumer errors"""
        self.health.record_error()
        
        if error.code() == KafkaError._PARTITION_EOF:
            # End of partition, not an error
            logger.debug(f"Reached end of partition")
        elif error.code() == KafkaError._ALL_BROKERS_DOWN:
            logger.error("All Kafka brokers are down")
            self.health.connected = False
        else:
            logger.error(f"Kafka error: {error}")
    
    async def stop(self):
        """Stop the Kafka consumer gracefully"""
        logger.info("Stopping Kafka listener...")
        self.running = False
        
        if self.consumer:
            try:
                self.consumer.close()
            except Exception as e:
                logger.warning(f"Error closing Kafka consumer: {e}")
            finally:
                self.consumer = None
        
        self.health.connected = False
        logger.info("Kafka listener stopped")
    
    def get_health(self) -> Dict[str, Any]:
        """Get listener health status"""
        return {
            'running': self.running,
            'fallback_triggered': self._fallback_triggered,
            **self.health.get_stats()
        }

