import asyncio
import logging
from typing import Optional

from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
    StartFrame,
    EndFrame,
    CancelFrame,
)
from mistralai import Mistral

from src.config.settings import settings

logger = logging.getLogger(__name__)


class VoxtralSTTProcessor(FrameProcessor):
    """Voxtral Realtime STT processor using Mistral SDK directly.

    Receives InputAudioRawFrame, sends audio to Voxtral Realtime API,
    and emits TranscriptionFrame downstream.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "mistral-voice-latest",
        language: str = "en",
        sample_rate: int = 16000,
        **kwargs,
    ):
        super().__init__(name="VoxtralSTT", **kwargs)
        self._api_key = api_key
        self._model = model
        self._language = language
        self._sample_rate = sample_rate
        self._client: Optional[Mistral] = None
        self._current_speaker: Optional[str] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._client = Mistral(api_key=self._api_key)
            logger.info("VoxtralSTT initialized")
            await self.push_frame(frame, direction)

        elif isinstance(frame, InputAudioRawFrame):
            speaker_name = frame.metadata.get("name", "unknown") if frame.metadata else "unknown"
            participant_id = frame.metadata.get("participant_id", "unknown") if frame.metadata else "unknown"
            timestamp = str(frame.metadata.get("timestamp", "")) if frame.metadata else ""

            try:
                result = await self._transcribe(frame.audio)
                if result and result.get("text"):
                    tf = TranscriptionFrame(
                        text=result["text"],
                        user_id=participant_id,
                        timestamp=timestamp,
                    )
                    tf.metadata = {
                        "speaker": speaker_name,
                        "participant_id": participant_id,
                        "source": "voxtral_stt",
                        "is_final": result.get("is_final", False),
                    }
                    await self.push_frame(tf)
            except Exception as e:
                logger.error(f"STT processing error: {e}")

        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._client = None
            logger.info("VoxtralSTT stopped")
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    async def _transcribe(self, audio: bytes) -> Optional[dict]:
        """Send audio to Voxtral Realtime API and return transcription result.

        TODO: Implement actual Voxtral Realtime WebSocket streaming.
        For now, this is a stub that will be connected to the Mistral
        Voxtral Realtime endpoint when available.
        """
        if not self._client:
            return None

        # TODO: Replace with actual Voxtral Realtime API call.
        # The Mistral SDK's realtime STT API is expected to provide
        # a streaming WebSocket interface. For now, return None to
        # allow the pipeline to load without errors.
        return None

    async def set_language(self, language: str) -> None:
        """Set the language for STT."""
        self._language = language
