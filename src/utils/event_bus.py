import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Awaitable[None]]


class EventBus:
    """Simple in-memory async pub/sub helper for cross-bot coordination."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register an async handler for the supplied event name."""
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("event handler must be an async function")

        async with self._lock:
            if handler not in self._handlers[event_name]:
                self._handlers[event_name].append(handler)

    async def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        async with self._lock:
            handlers = self._handlers.get(event_name)
            if handlers and handler in handlers:
                handlers.remove(handler)
                if not handlers:
                    self._handlers.pop(event_name, None)

    async def publish(self, event_name: str, **payload: Any) -> None:
        """
        Fire an event by scheduling each registered handler on the current loop.

        Handlers are executed asynchronously (fire-and-forget). Exceptions are
        logged but do not propagate back to the publisher.
        """
        async with self._lock:
            handlers = list(self._handlers.get(event_name, ()))

        if not handlers:
            return

        loop = asyncio.get_running_loop()
        for handler in handlers:
            loop.create_task(self._run_handler(handler, payload))

    async def _run_handler(self, handler: EventHandler, payload: Dict[str, Any]) -> None:
        try:
            await handler(**payload)
        except Exception:
            logger.exception("event handler %s failed", getattr(handler, "__name__", handler))


event_bus = EventBus()
