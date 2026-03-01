"""API Key authentication and WebSocket token verification.

Addresses: OWASP A01 (Broken Access Control), A07 (Auth Failures), A10 (SSRF)
"""

import hmac
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from src.config.settings import settings

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str = Depends(API_KEY_HEADER),
) -> str:
    """FastAPI dependency that validates the API key from request header.

    Raises HTTPException 403 if the key is missing or invalid.
    Uses constant-time comparison to prevent timing attacks.
    """
    expected_key = settings.security.api_key
    if not expected_key:
        # If no API key is configured, skip auth (development mode)
        logger.warning("No PROXY_MISTRAL_API_KEY configured — authentication disabled")
        return ""
    if not api_key or not hmac.compare_digest(api_key, expected_key):
        logger.warning("Rejected request with invalid or missing API key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key",
        )
    return api_key


def verify_ws_token(token: str) -> bool:
    """Validate a WebSocket connection token.

    Returns True if valid, False otherwise.
    """
    expected = settings.security.ws_token
    if not expected:
        # If no token configured, allow all (development mode)
        logger.warning("No PROXY_MISTRAL_WS_TOKEN configured — WS auth disabled")
        return True
    if not token:
        return False
    return hmac.compare_digest(token, expected)
