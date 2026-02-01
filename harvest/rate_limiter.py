"""Rate limiting with token bucket algorithm and exponential backoff."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from harvest.config import GITHUB_REQUESTS_PER_MINUTE, WEB_REQUESTS_PER_SECOND


@dataclass
class TokenBucket:
    """Token bucket rate limiter.

    Tokens are added at a constant rate up to a maximum capacity.
    Each request consumes one token. If no tokens are available,
    the request waits until a token becomes available.
    """

    rate: float  # Tokens per second
    capacity: float  # Maximum tokens
    tokens: float = field(init=False)
    last_update: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.last_update = time.monotonic()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def acquire(self) -> float:
        """Acquire a token, returning wait time if needed.

        Returns:
            Time to wait in seconds (0 if token available immediately)
        """
        self._refill()

        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0

        # Calculate wait time for next token
        wait_time = (1 - self.tokens) / self.rate
        return wait_time

    async def acquire_async(self) -> None:
        """Acquire a token, waiting if necessary."""
        wait_time = self.acquire()
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            # Consume the token after waiting
            self._refill()
            self.tokens -= 1


@dataclass
class ExponentialBackoff:
    """Exponential backoff for handling rate limit responses."""

    base_delay: float = 1.0  # Initial delay in seconds
    max_delay: float = 60.0  # Maximum delay
    multiplier: float = 2.0  # Delay multiplier after each failure
    current_delay: float = field(init=False)
    consecutive_failures: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.current_delay = self.base_delay

    def record_failure(self) -> float:
        """Record a failure and return the delay to wait.

        Returns:
            Delay in seconds before next retry
        """
        delay = self.current_delay
        self.consecutive_failures += 1
        self.current_delay = min(self.current_delay * self.multiplier, self.max_delay)
        return delay

    def record_success(self) -> None:
        """Record a success, resetting the backoff."""
        self.current_delay = self.base_delay
        self.consecutive_failures = 0

    async def wait_after_failure(self) -> None:
        """Wait the appropriate backoff delay after a failure."""
        delay = self.record_failure()
        await asyncio.sleep(delay)


class RateLimiter:
    """Combined rate limiter with per-source buckets and backoff."""

    def __init__(self) -> None:
        # Per-source token buckets
        self._buckets: dict[str, TokenBucket] = {
            "github": TokenBucket(
                rate=GITHUB_REQUESTS_PER_MINUTE / 60.0,  # Convert to per-second
                capacity=GITHUB_REQUESTS_PER_MINUTE,
            ),
            "web": TokenBucket(
                rate=WEB_REQUESTS_PER_SECOND,
                capacity=5,  # Allow small bursts
            ),
        }

        # Per-source backoff trackers
        self._backoffs: dict[str, ExponentialBackoff] = {}

    def get_bucket(self, source: str) -> TokenBucket:
        """Get or create a token bucket for a source."""
        if source not in self._buckets:
            # Default bucket for unknown sources
            self._buckets[source] = TokenBucket(
                rate=WEB_REQUESTS_PER_SECOND,
                capacity=5,
            )
        return self._buckets[source]

    def get_backoff(self, source: str) -> ExponentialBackoff:
        """Get or create a backoff tracker for a source."""
        if source not in self._backoffs:
            self._backoffs[source] = ExponentialBackoff()
        return self._backoffs[source]

    async def acquire(self, source: str) -> None:
        """Acquire permission to make a request to a source."""
        bucket = self.get_bucket(source)
        await bucket.acquire_async()

    async def handle_response(self, source: str, status_code: int) -> bool:
        """Handle a response status code.

        Args:
            source: The source identifier
            status_code: HTTP status code

        Returns:
            True if request should be retried, False otherwise
        """
        backoff = self.get_backoff(source)

        if status_code in (429, 503):  # Rate limited or service unavailable
            await backoff.wait_after_failure()
            return True
        elif status_code == 403:  # Forbidden - might be rate limit
            if backoff.consecutive_failures < 3:
                await backoff.wait_after_failure()
                return True
            return False
        elif 200 <= status_code < 300:  # Success
            backoff.record_success()
            return False
        else:
            # Other errors - don't retry automatically
            return False

    def wait_sync(self, source: str) -> None:
        """Synchronous wait for rate limit (blocks the thread)."""
        bucket = self.get_bucket(source)
        wait_time = bucket.acquire()
        if wait_time > 0:
            time.sleep(wait_time)


# Global rate limiter instance
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def rate_limited_request(
    source: str,
    request_func: Callable[[], Awaitable[Any]],
    max_retries: int = 3,
) -> Any:
    """Execute a request with rate limiting and retry logic.

    Args:
        source: Source identifier for rate limiting
        request_func: Async function that makes the request
        max_retries: Maximum number of retries on rate limit

    Returns:
        The result of request_func

    Raises:
        Exception from request_func if all retries exhausted
    """
    limiter = get_rate_limiter()

    for attempt in range(max_retries + 1):
        await limiter.acquire(source)

        try:
            result = await request_func()
            # If request_func returns a response with status_code, handle it
            if hasattr(result, "status_code"):
                should_retry = await limiter.handle_response(source, result.status_code)
                if should_retry and attempt < max_retries:
                    continue
            return result
        except Exception:
            if attempt == max_retries:
                raise
            backoff = limiter.get_backoff(source)
            await backoff.wait_after_failure()

    return None  # Should not reach here
