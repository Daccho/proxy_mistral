"""Input sanitization and LLM output validation.

Addresses: OWASP LLM01 (Prompt Injection), LLM05 (Improper Output Handling),
           LLM07 (System Prompt Leakage)
"""

import logging
import re

logger = logging.getLogger(__name__)

MAX_SPEAKER_INPUT_LENGTH = 2000
MAX_RESPONSE_LENGTH = 2000

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"ignore\s+(all\s+)?above", re.I),
    re.compile(r"disregard\s+(all\s+)?previous", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\s+", re.I),
    re.compile(r"new\s+instructions?:", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"reveal\s+(your\s+)?(system|instructions|prompt)", re.I),
    re.compile(r"\[system\]", re.I),
    re.compile(r"\[INST\]", re.I),
    re.compile(r"<<SYS>>", re.I),
]

# Patterns to redact from LLM output (leakage markers)
_LEAKAGE_PATTERNS = re.compile(
    r"(system prompt|<<SYS>>|\[INST\]|\[/INST\]|<\|system\|>)", re.I
)


def sanitize_speaker_input(text: str) -> str:
    """Sanitize speaker name or utterance before prompt interpolation.

    - Removes control characters
    - Truncates to MAX_SPEAKER_INPUT_LENGTH
    """
    # Remove control characters (keep newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text[:MAX_SPEAKER_INPUT_LENGTH]


def detect_injection(text: str) -> bool:
    """Return True if text contains likely prompt injection patterns."""
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def wrap_user_content(speaker: str, text: str) -> str:
    """Wrap user content with XML delimiters to help the LLM distinguish it from instructions.

    This is a defense-in-depth measure: the delimiters make it harder for injected
    text to be interpreted as system instructions.
    """
    safe_speaker = sanitize_speaker_input(speaker)
    safe_text = sanitize_speaker_input(text)

    if detect_injection(safe_text):
        logger.warning(f"Potential prompt injection detected from speaker: {safe_speaker}")

    return f'<meeting_utterance speaker="{safe_speaker}">{safe_text}</meeting_utterance>'


def validate_llm_output(text: str) -> str:
    """Validate and sanitize LLM output before sending downstream.

    - Truncates excessive output
    - Removes HTML tags (problematic for TTS)
    - Redacts potential prompt leakage markers
    """
    if not text or not text.strip():
        return ""

    # Truncate
    if len(text) > MAX_RESPONSE_LENGTH:
        text = text[:MAX_RESPONSE_LENGTH] + "..."

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Redact prompt leakage markers
    text = _LEAKAGE_PATTERNS.sub("[redacted]", text)

    return text.strip()
