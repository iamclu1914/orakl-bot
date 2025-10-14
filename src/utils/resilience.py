"""
Resilience utilities for ORAKL Bot
Implements retry logic, circuit breaker, and rate limiting
"""

import asyncio
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, TypeVar, Union
from collections import deque
import random

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RateLimitError(Exception):
    """Raised when rate limit is exceeded"""
    pass


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open"""
    pass


class TokenBucket:
    """Token bucket algorithm for rate limiting"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket
        
        Args:
            capacity: Maximum number of tokens
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens acquired, False otherwise
        """
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            
            # Refill tokens
            tokens_to_add = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now
            
            # Try to acquire
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def wait_for_tokens(self, tokens: int = 1) -> None:
        """Wait until tokens are available"""
        while not await self.acquire(tokens):
            wait_time = tokens / self.refill_rate
            await asyncio.sleep(wait_time)


class CircuitBreaker:
    """Circuit breaker pattern implementation"""
    
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        """
        Initialize circuit breaker
        
        Args:
            failure_threshold: Number of failures before opening
            recovery_timeout: Seconds before attempting recovery
            expected_exception: Exception type to catch
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._success_count = 0
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Call function with circuit breaker protection
        
        Args:
            func: Function to call
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: If circuit is open
        """
        async with self._lock:
            if self._state == self.OPEN:
                if self._should_attempt_reset():
                    self._state = self.HALF_OPEN
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker is OPEN. Recovery in "
                        f"{self._time_until_recovery():.0f} seconds"
                    )
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except self.expected_exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """Handle successful call"""
        async with self._lock:
            if self._state == self.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= 3:  # Require 3 successes to close
                    self._state = self.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit breaker closed after recovery")
            else:
                self._failure_count = 0
    
    async def _on_failure(self):
        """Handle failed call"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            
            if self._state == self.HALF_OPEN:
                self._state = self.OPEN
                self._success_count = 0
                logger.warning("Circuit breaker reopened after failure in HALF_OPEN state")
            elif self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                logger.error(f"Circuit breaker opened after {self._failure_count} failures")
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset the circuit"""
        return (
            self._last_failure_time and
            datetime.now() - self._last_failure_time > timedelta(seconds=self.recovery_timeout)
        )
    
    def _time_until_recovery(self) -> float:
        """Time in seconds until recovery attempt"""
        if not self._last_failure_time:
            return 0
        
        elapsed = (datetime.now() - self._last_failure_time).total_seconds()
        return max(0, self.recovery_timeout - elapsed)
    
    @property
    def state(self) -> str:
        """Current circuit breaker state"""
        return self._state
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open"""
        return self._state == self.OPEN


def exponential_backoff_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for exponential backoff retry logic
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Add random jitter to delays
        exceptions: Tuple of exceptions to catch
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for {func.__name__}: {e}"
                        )
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    # Add jitter if enabled
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {delay:.2f}s delay. Error: {e}"
                    )
                    
                    await asyncio.sleep(delay)
            
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for {func.__name__}: {e}"
                        )
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    # Add jitter if enabled
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {delay:.2f}s delay. Error: {e}"
                    )
                    
                    time.sleep(delay)
            
            raise last_exception
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class RateLimiter:
    """Rate limiter with multiple strategies"""
    
    def __init__(
        self,
        calls_per_second: Optional[float] = None,
        calls_per_minute: Optional[int] = None,
        burst_capacity: Optional[int] = None
    ):
        """
        Initialize rate limiter
        
        Args:
            calls_per_second: Maximum calls per second
            calls_per_minute: Maximum calls per minute
            burst_capacity: Maximum burst capacity
        """
        self.token_buckets = {}
        
        if calls_per_second:
            self.token_buckets['second'] = TokenBucket(
                capacity=burst_capacity or int(calls_per_second * 2),
                refill_rate=calls_per_second
            )
        
        if calls_per_minute:
            self.token_buckets['minute'] = TokenBucket(
                capacity=burst_capacity or calls_per_minute,
                refill_rate=calls_per_minute / 60.0
            )
    
    async def acquire(self):
        """Acquire permission to make a call"""
        for bucket in self.token_buckets.values():
            await bucket.wait_for_tokens(1)
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator for rate limiting"""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            await self.acquire()
            return await func(*args, **kwargs)
        return wrapper


class BoundedDeque:
    """Thread-safe bounded deque with TTL support"""
    
    def __init__(self, maxlen: int, ttl_seconds: Optional[int] = None):
        """
        Initialize bounded deque
        
        Args:
            maxlen: Maximum length
            ttl_seconds: Time to live for items in seconds
        """
        self.maxlen = maxlen
        self.ttl_seconds = ttl_seconds
        self._deque = deque(maxlen=maxlen)
        self._timestamps = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()
    
    async def append(self, item: Any):
        """Add item to deque"""
        async with self._lock:
            self._cleanup_expired()
            self._deque.append(item)
            self._timestamps.append(time.time())
    
    async def get_all(self) -> list:
        """Get all non-expired items"""
        async with self._lock:
            self._cleanup_expired()
            return list(self._deque)
    
    def _cleanup_expired(self):
        """Remove expired items"""
        if not self.ttl_seconds:
            return
        
        now = time.time()
        while self._timestamps and now - self._timestamps[0] > self.ttl_seconds:
            self._deque.popleft()
            self._timestamps.popleft()
    
    async def clear(self):
        """Clear all items"""
        async with self._lock:
            self._deque.clear()
            self._timestamps.clear()
    
    def __len__(self):
        """Get current length"""
        return len(self._deque)


# Polygon API specific rate limiter (5 calls per second for free tier)
polygon_rate_limiter = RateLimiter(
    calls_per_second=5,
    burst_capacity=10
)

# Circuit breaker for API calls
api_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=(asyncio.TimeoutError, ConnectionError)
)
