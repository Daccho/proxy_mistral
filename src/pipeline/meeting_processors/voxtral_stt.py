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
from mistralai.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamLanguage,
    TranscriptionStreamTextDelta,
)
from mistralai.extra.realtime import UnknownRealtimeEvent
from mistralai.extra.realtime.connection import RealtimeConnection

logger = logging.getLogger(__name__)


class VoxtralSTTProcessor(FrameProcessor):
    """Voxtral Realtime STT processor.

    Receives InputAudioRawFrame from the pipeline, buffers audio into an
    asyncio.Queue, and streams it to Voxtral Realtime API via
    client.audio.realtime.connect(). Transcription events are
    converted to TranscriptionFrame and pushed downstream.

    Uses the low-level connect() API instead of transcribe_stream()
    because transcribe_stream() auto-terminates on transcription.done,
    which is unsuitable for continuous meeting transcription.
    """

    _MAX_RETRIES = 5

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "voxtral-mini-transcribe-realtime-2602",
        language: str = "en",
        sample_rate: int = 16000,
        target_streaming_delay_ms: int = 1000,
        **kwargs,
    ):
        super().__init__(name="VoxtralSTT", **kwargs)
        self._api_key = api_key
        self._model = model
        self._language = language
        self._sample_rate = sample_rate
        self._target_streaming_delay_ms = target_streaming_delay_ms

        self._client: Optional[Mistral] = None
        self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._stream_task: Optional[asyncio.Task] = None
        self._current_text = ""
        self._current_speaker: Optional[str] = None
        self._current_participant_id: Optional[str] = None
        self._audio_chunk_count: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            if self._stream_task is not None:
                logger.warning("VoxtralSTT: duplicate StartFrame ignored")
                await self.push_frame(frame, direction)
                return
            self._client = Mistral(api_key=self._api_key)
            self._audio_queue = asyncio.Queue()
            self._stream_task = asyncio.create_task(self._run_transcription())
            logger.info(
                "VoxtralSTT started (model=%s, delay=%dms)",
                self._model,
                self._target_streaming_delay_ms,
            )
            await self.push_frame(frame, direction)

        elif isinstance(frame, InputAudioRawFrame):
            self._audio_chunk_count += 1
            if self._audio_chunk_count == 1:
                logger.info(
                    "VoxtralSTT: first audio frame received (%d bytes)",
                    len(frame.audio),
                )
            elif self._audio_chunk_count % 500 == 0:
                logger.info(
                    "VoxtralSTT: audio frames received: %d (queue: %d)",
                    self._audio_chunk_count,
                    self._audio_queue.qsize(),
                )

            if frame.metadata:
                self._current_speaker = frame.metadata.get("name", "unknown")
                self._current_participant_id = frame.metadata.get(
                    "participant_id", "unknown"
                )

            await self._audio_queue.put(frame.audio)

        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_stream()
            logger.info("VoxtralSTT stopped")
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    async def _stop_stream(self):
        """Signal end-of-stream and wait for the transcription task to finish."""
        await self._audio_queue.put(None)
        if self._stream_task:
            try:
                await asyncio.wait_for(self._stream_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._stream_task.cancel()
            self._stream_task = None
        self._client = None

    async def _run_transcription(self):
        """Background task: connect to Voxtral Realtime with auto-reconnection."""
        retry_count = 0

        while self._client and retry_count < self._MAX_RETRIES:
            try:
                await self._run_transcription_session()
                # Clean exit (None sentinel received) — don't retry
                break
            except asyncio.CancelledError:
                logger.debug("Voxtral transcription task cancelled")
                break
            except Exception as e:
                retry_count += 1
                wait_time = min(2**retry_count, 30)
                logger.error(
                    "Voxtral Realtime stream error (attempt %d/%d): %s. "
                    "Retrying in %ds...",
                    retry_count,
                    self._MAX_RETRIES,
                    e,
                    wait_time,
                )
                await asyncio.sleep(wait_time)

        if retry_count >= self._MAX_RETRIES:
            logger.error("VoxtralSTT: max retries exceeded, transcription stopped")

    async def _run_transcription_session(self):
        """Single transcription session using the low-level connect() API."""
        if not self._client:
            return

        audio_format = AudioFormat(
            encoding="pcm_s16le", sample_rate=self._sample_rate
        )

        async with await self._client.audio.realtime.connect(
            model=self._model,
            audio_format=audio_format,
            target_streaming_delay_ms=self._target_streaming_delay_ms,
        ) as connection:
            send_task = asyncio.create_task(self._send_audio_loop(connection))

            try:
                async for event in connection:
                    if isinstance(event, RealtimeTranscriptionSessionCreated):
                        logger.info("Voxtral Realtime session created")

                    elif isinstance(event, TranscriptionStreamTextDelta):
                        self._current_text += event.text
                        tf = TranscriptionFrame(
                            text=self._current_text,
                            user_id=self._current_participant_id or "unknown",
                            timestamp="",
                        )
                        tf.metadata = {
                            "speaker": self._current_speaker or "unknown",
                            "participant_id": self._current_participant_id
                            or "unknown",
                            "source": "voxtral_realtime",
                            "is_final": False,
                        }
                        await self.push_frame(tf)

                    elif isinstance(event, TranscriptionStreamDone):
                        if self._current_text:
                            tf = TranscriptionFrame(
                                text=self._current_text,
                                user_id=self._current_participant_id or "unknown",
                                timestamp="",
                            )
                            tf.metadata = {
                                "speaker": self._current_speaker or "unknown",
                                "participant_id": self._current_participant_id
                                or "unknown",
                                "source": "voxtral_realtime",
                                "is_final": True,
                            }
                            logger.info(
                                "STT final: [%s] %s",
                                self._current_speaker or "unknown",
                                self._current_text,
                            )
                            await self.push_frame(tf)
                        self._current_text = ""

                    elif isinstance(event, TranscriptionStreamLanguage):
                        logger.info(
                            "Voxtral detected language: %s",
                            event.audio_language,
                        )

                    elif isinstance(event, RealtimeTranscriptionError):
                        logger.error("Voxtral Realtime error: %s", event)

                    elif isinstance(event, UnknownRealtimeEvent):
                        logger.debug("Unknown Voxtral event: %s", event)

            finally:
                send_task.cancel()
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass

    async def _send_audio_loop(self, connection: RealtimeConnection):
        """Send audio chunks from the queue to the Voxtral connection."""
        chunks_sent = 0
        try:
            while True:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    await connection.flush_audio()
                    await connection.end_audio()
                    break
                if connection.is_closed:
                    break
                await connection.send_audio(chunk)
                chunks_sent += 1
                # Flush periodically (~1.6s of audio) to trigger transcription
                if chunks_sent % 160 == 0:
                    await connection.flush_audio()
                if chunks_sent == 1:
                    logger.info("VoxtralSTT: first audio chunk sent to API")
                elif chunks_sent % 500 == 0:
                    logger.info(
                        "VoxtralSTT: audio chunks sent to API: %d", chunks_sent
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("VoxtralSTT: error sending audio: %s", e)

    async def set_language(self, language: str) -> None:
        """Set the language for STT."""
        self._language = language
