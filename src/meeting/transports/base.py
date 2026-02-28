from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any
import json
import logging

logger = logging.getLogger(__name__)


class BaseMeetingTransport(ABC):
    """Abstract base class for meeting transport layers."""

    @abstractmethod
    async def join_meeting(self, meeting_url: str, bot_name: str = "ProxyBot", bot_image: str = "") -> Dict[str, Any]:
        """Join a meeting and return meeting info."""
        pass

    @abstractmethod
    async def leave_meeting(self) -> None:
        """Leave the current meeting."""
        pass

    @abstractmethod
    async def get_audio_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Get audio stream from the meeting.
        
        Yields dicts with structure:
        {
            "participant_id": str,
            "name": str,
            "audio": bytes,  # PCM audio data
            "is_host": bool,
            "timestamp": float
        }
        """
        pass

    @abstractmethod
    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio to the meeting."""
        pass

    @abstractmethod
    async def get_participants(self) -> list[Dict[str, Any]]:
        """Get list of current participants."""
        pass

    @abstractmethod
    async def send_chat_message(self, message: str) -> None:
        """Send a chat message to the meeting."""
        pass