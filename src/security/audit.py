"""Audit logging and log sanitization.

Addresses: OWASP A09 (Security Logging and Monitoring Failures)
"""

import re
import logging

audit_log = logging.getLogger("audit")

# Patterns to redact from log messages
_SENSITIVE_PATTERNS = [
    # API keys and tokens in key=value or key: value style
    (
        re.compile(
            r'(api[_-]?key|token|secret|password|authorization)["\s:=]+["\']?([^\s"\',}{]{8,})',
            re.I,
        ),
        r"\1=***REDACTED***",
    ),
]


def log_api_access(
    endpoint: str,
    client_ip: str,
    api_key_prefix: str,
    status: int,
) -> None:
    """Record an API access event for audit trail."""
    safe_prefix = (api_key_prefix[:8] + "...") if api_key_prefix else "none"
    audit_log.info(
        "api_access endpoint=%s client_ip=%s api_key=%s status=%d",
        endpoint,
        client_ip,
        safe_prefix,
        status,
    )


def log_ws_connection(client_ip: str, authenticated: bool) -> None:
    """Record a WebSocket connection attempt."""
    audit_log.info(
        "ws_connection client_ip=%s authenticated=%s",
        client_ip,
        authenticated,
    )


def sanitize_log_message(message: str) -> str:
    """Redact sensitive data (keys, tokens) from a log message."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message
