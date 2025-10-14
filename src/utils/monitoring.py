"""
Monitoring utilities for ORAKL Bot
Implements metrics collection and Prometheus integration
"""

import time
import asyncio
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, field
import logging
from functools import wraps

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """Single metric data point"""
    timestamp: float
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


class MetricCollector:
    """Base metric collector"""
    
    def __init__(self, name: str, description: str, labels: List[str] = None):
        self.name = name
        self.description = description
        self.labels = labels or []
        self._values = defaultdict(lambda: deque(maxlen=1000))
    
    def observe(self, value: float, labels: Dict[str, str] = None):
        """Record a metric observation"""
        label_key = self._make_label_key(labels or {})
        self._values[label_key].append(MetricPoint(
            timestamp=time.time(),
            value=value,
            labels=labels or {}
        ))
    
    def get_current(self, labels: Dict[str, str] = None) -> Optional[float]:
        """Get most recent value"""
        label_key = self._make_label_key(labels or {})
        if label_key in self._values and self._values[label_key]:
            return self._values[label_key][-1].value
        return None
    
    def get_all(self) -> Dict[str, List[MetricPoint]]:
        """Get all metric points"""
        return dict(self._values)
    
    def _make_label_key(self, labels: Dict[str, str]) -> str:
        """Create consistent key from labels"""
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


class Counter(MetricCollector):
    """Counter metric (monotonically increasing)"""
    
    def __init__(self, name: str, description: str, labels: List[str] = None):
        super().__init__(name, description, labels)
        self._totals = defaultdict(float)
    
    def inc(self, value: float = 1.0, labels: Dict[str, str] = None):
        """Increment counter"""
        if value < 0:
            raise ValueError("Counter can only increase")
        
        label_key = self._make_label_key(labels or {})
        self._totals[label_key] += value
        self.observe(self._totals[label_key], labels)
    
    def get_total(self, labels: Dict[str, str] = None) -> float:
        """Get current total"""
        label_key = self._make_label_key(labels or {})
        return self._totals.get(label_key, 0.0)


class Gauge(MetricCollector):
    """Gauge metric (can go up or down)"""
    
    def set(self, value: float, labels: Dict[str, str] = None):
        """Set gauge value"""
        self.observe(value, labels)
    
    def inc(self, value: float = 1.0, labels: Dict[str, str] = None):
        """Increment gauge"""
        current = self.get_current(labels) or 0
        self.set(current + value, labels)
    
    def dec(self, value: float = 1.0, labels: Dict[str, str] = None):
        """Decrement gauge"""
        current = self.get_current(labels) or 0
        self.set(current - value, labels)


class Histogram(MetricCollector):
    """Histogram metric for distributions"""
    
    def __init__(self, name: str, description: str, buckets: List[float] = None, labels: List[str] = None):
        super().__init__(name, description, labels)
        self.buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        self._bucket_counts = defaultdict(lambda: defaultdict(int))
        self._sums = defaultdict(float)
        self._counts = defaultdict(int)
    
    def observe(self, value: float, labels: Dict[str, str] = None):
        """Record histogram observation"""
        super().observe(value, labels)
        
        label_key = self._make_label_key(labels or {})
        
        # Update buckets
        for bucket in self.buckets:
            if value <= bucket:
                self._bucket_counts[label_key][bucket] += 1
        
        # Update sum and count
        self._sums[label_key] += value
        self._counts[label_key] += 1
    
    def get_percentile(self, percentile: float, labels: Dict[str, str] = None) -> Optional[float]:
        """Get percentile value"""
        if not 0 <= percentile <= 100:
            raise ValueError("Percentile must be between 0 and 100")
        
        label_key = self._make_label_key(labels or {})
        values = [p.value for p in self._values.get(label_key, [])]
        
        if not values:
            return None
        
        sorted_values = sorted(values)
        index = int(len(sorted_values) * (percentile / 100))
        return sorted_values[min(index, len(sorted_values) - 1)]
    
    def get_summary(self, labels: Dict[str, str] = None) -> Dict[str, float]:
        """Get summary statistics"""
        label_key = self._make_label_key(labels or {})
        
        if label_key not in self._counts or self._counts[label_key] == 0:
            return {}
        
        return {
            'count': self._counts[label_key],
            'sum': self._sums[label_key],
            'mean': self._sums[label_key] / self._counts[label_key],
            'p50': self.get_percentile(50, labels) or 0,
            'p95': self.get_percentile(95, labels) or 0,
            'p99': self.get_percentile(99, labels) or 0
        }


class MetricsRegistry:
    """Central metrics registry"""
    
    def __init__(self):
        self._metrics = {}
        self._collectors = {}
    
    def register_counter(self, name: str, description: str, labels: List[str] = None) -> Counter:
        """Register a counter metric"""
        if name in self._metrics:
            raise ValueError(f"Metric {name} already registered")
        
        counter = Counter(name, description, labels)
        self._metrics[name] = counter
        return counter
    
    def register_gauge(self, name: str, description: str, labels: List[str] = None) -> Gauge:
        """Register a gauge metric"""
        if name in self._metrics:
            raise ValueError(f"Metric {name} already registered")
        
        gauge = Gauge(name, description, labels)
        self._metrics[name] = gauge
        return gauge
    
    def register_histogram(self, name: str, description: str, buckets: List[float] = None, labels: List[str] = None) -> Histogram:
        """Register a histogram metric"""
        if name in self._metrics:
            raise ValueError(f"Metric {name} already registered")
        
        histogram = Histogram(name, description, buckets, labels)
        self._metrics[name] = histogram
        return histogram
    
    def get_metric(self, name: str) -> Optional[MetricCollector]:
        """Get metric by name"""
        return self._metrics.get(name)
    
    def get_all_metrics(self) -> Dict[str, MetricCollector]:
        """Get all registered metrics"""
        return self._metrics.copy()
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []
        
        for name, metric in self._metrics.items():
            # Add help text
            lines.append(f"# HELP {name} {metric.description}")
            
            # Add type
            if isinstance(metric, Counter):
                lines.append(f"# TYPE {name} counter")
            elif isinstance(metric, Gauge):
                lines.append(f"# TYPE {name} gauge")
            elif isinstance(metric, Histogram):
                lines.append(f"# TYPE {name} histogram")
            
            # Add metric values
            if isinstance(metric, (Counter, Gauge)):
                for label_key, points in metric.get_all().items():
                    if points:
                        latest = points[-1]
                        label_str = self._format_labels(latest.labels)
                        lines.append(f"{name}{label_str} {latest.value}")
            
            elif isinstance(metric, Histogram):
                for label_key, summary in metric._counts.items():
                    if summary > 0:
                        labels = self._parse_label_key(label_key)
                        label_str = self._format_labels(labels)
                        
                        # Bucket counts
                        for bucket, count in sorted(metric._bucket_counts[label_key].items()):
                            bucket_labels = {**labels, 'le': str(bucket)}
                            bucket_label_str = self._format_labels(bucket_labels)
                            lines.append(f"{name}_bucket{bucket_label_str} {count}")
                        
                        # +Inf bucket
                        inf_labels = {**labels, 'le': '+Inf'}
                        inf_label_str = self._format_labels(inf_labels)
                        lines.append(f"{name}_bucket{inf_label_str} {metric._counts[label_key]}")
                        
                        # Sum and count
                        lines.append(f"{name}_sum{label_str} {metric._sums[label_key]}")
                        lines.append(f"{name}_count{label_str} {metric._counts[label_key]}")
            
            lines.append("")  # Empty line between metrics
        
        return "\n".join(lines)
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        """Format labels for Prometheus"""
        if not labels:
            return ""
        
        label_parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(label_parts) + "}"
    
    def _parse_label_key(self, label_key: str) -> Dict[str, str]:
        """Parse label key back to dict"""
        if not label_key:
            return {}
        
        labels = {}
        for part in label_key.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                labels[k] = v
        return labels


# Global metrics registry
metrics = MetricsRegistry()

# Pre-defined metrics
request_counter = metrics.register_counter(
    "orakl_http_requests_total",
    "Total HTTP requests",
    labels=["method", "endpoint", "status"]
)

request_duration = metrics.register_histogram(
    "orakl_http_request_duration_seconds",
    "HTTP request duration in seconds",
    labels=["method", "endpoint"]
)

active_bots = metrics.register_gauge(
    "orakl_active_bots",
    "Number of active bots",
    labels=["bot_type"]
)

signals_generated = metrics.register_counter(
    "orakl_signals_generated_total",
    "Total signals generated",
    labels=["bot", "signal_type"]
)

api_errors = metrics.register_counter(
    "orakl_api_errors_total",
    "Total API errors",
    labels=["api", "error_type"]
)

cache_hits = metrics.register_counter(
    "orakl_cache_hits_total",
    "Total cache hits",
    labels=["cache_name"]
)

cache_misses = metrics.register_counter(
    "orakl_cache_misses_total",
    "Total cache misses",
    labels=["cache_name"]
)


def timed(metric: Histogram = None):
    """Decorator to time function execution"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if metric:
                    metric.observe(duration)
                else:
                    logger.debug(f"{func.__name__} took {duration:.3f}s")
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if metric:
                    metric.observe(duration)
                else:
                    logger.debug(f"{func.__name__} took {duration:.3f}s")
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


def counted(metric: Counter = None, labels: Dict[str, str] = None):
    """Decorator to count function calls"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if metric:
                metric.inc(labels=labels)
            return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if metric:
                metric.inc(labels=labels)
            return func(*args, **kwargs)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator
