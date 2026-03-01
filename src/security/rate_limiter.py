"""In-memory rate limiter for API endpoints.

Uses a simple sliding-window counter per client IP.
No external dependencies required.

Addresses: OWASP A04 (Insecure Design), LLM10 (Unbounded Consumption)
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request


class RateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, requests_per_minute: int = 60):
        self.rpm = requests_per_minute
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, client_id: str) -> None:
        now = time.time()
        window = self._requests[client_id]
        # Evict entries older than 60 s
        self._requests[client_id] = [t for t in window if now - t < 60]
        if len(self._requests[client_id]) >= self.rpm:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        self._requests[client_id].append(now)


_limiter = RateLimiter(requests_per_minute=60)


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency that enforces per-IP rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    _limiter.check(client_ip)
