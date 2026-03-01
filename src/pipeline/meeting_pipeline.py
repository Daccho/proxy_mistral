import asyncio
import logging
import uuid
from typing import Optional

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    StartFrame,
    EndFrame,
    CancelFrame,
    TTSAudioRawFrame,
)
import aiohttp
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

from src.meeting.transports.base import BaseMeetingTransport
from src.config.settings import settings
from src.pipeline.meeting_processors.voxtral_stt import VoxtralSTTProcessor
from src.agent.brain import MistralAgentBrain
from src.agent.context_manager import DocumentContextManager
from src.agent.summarizer import MeetingSummarizer

logger = logging.getLogger(__name__)


class MeetingBaaSInputProcessor(FrameProcessor):
    """Reads audio from MeetingBaaS WebSocket and pushes InputAudioRawFrame."""

    def __init__(self, *, transport: BaseMeetingTransport, **kwargs):
        super().__init__(name="MeetingBaaSInput", **kwargs)
        self._transport = transport
        self._read_task: Optional[asyncio.Task] = None
        self._frame_count: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            self._read_task = asyncio.create_task(self._read_audio_loop())

        elif isinstance(frame, (EndFrame, CancelFrame)):
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    async def _read_audio_loop(self):
        """Read audio from MeetingBaaS WebSocket and push as frames."""
        try:
            async for audio_data in self._transport.get_audio_stream():
                self._frame_count += 1
                if self._frame_count == 1:
                    logger.info("First audio frame received from: %s", audio_data.get("name", "unknown"))

                audio_frame = InputAudioRawFrame(
                    audio=audio_data["audio"],
                    sample_rate=settings.meeting_baas.sample_rate,
                    num_channels=1,
                )
                audio_frame.metadata = {
                    "participant_id": audio_data["participant_id"],
                    "name": audio_data["name"],
                    "is_host": audio_data["is_host"],
                    "timestamp": audio_data["timestamp"],
                }
                await self.push_frame(audio_frame)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Transport read error: %s", e)


class MeetingBaaSOutputProcessor(FrameProcessor):
    """Receives TTSAudioRawFrame and sends audio back to the meeting."""

    def __init__(self, *, transport: BaseMeetingTransport, **kwargs):
        super().__init__(name="MeetingBaaSOutput", **kwargs)
        self._transport = transport

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSAudioRawFrame):
            try:
                await self._transport.send_audio(frame.audio)
                logger.info("Sent audio response: %d bytes", len(frame.audio))
            except Exception as e:
                logger.error("Error sending audio: %s", e)
        else:
            await self.push_frame(frame, direction)


class MeetingPipeline:
    """Main meeting pipeline using Pipecat framework."""

    def __init__(self, transport: BaseMeetingTransport, meeting_url: str = "", bot_name: str = ""):
        self.transport = transport
        self._meeting_url = meeting_url
        self._bot_name = bot_name
        self._meeting_id = str(uuid.uuid4())
        self._task: Optional[PipelineTask] = None
        self._runner: Optional[PipelineRunner] = None
        self._brain_proc: Optional[MistralAgentBrain] = None
        self._context_manager: Optional[DocumentContextManager] = None
        self._summarizer: Optional[MeetingSummarizer] = None
        self._aiohttp_session: Optional[aiohttp.ClientSession] = None

    async def setup(self) -> None:
        """Set up the Pipecat pipeline."""
        logger.info("Setting up meeting pipeline...")

        # Initialize context manager and summarizer
        self._context_manager = DocumentContextManager()
        self._summarizer = MeetingSummarizer(
            api_key=settings.mistral.api_key,
            model=settings.mistral.model,
            context_manager=self._context_manager,
        )

        input_proc = MeetingBaaSInputProcessor(transport=self.transport)

        stt_proc = VoxtralSTTProcessor(
            api_key=settings.mistral.api_key,
            sample_rate=settings.meeting_baas.sample_rate,
        )

        self._brain_proc = MistralAgentBrain(
            api_key=settings.mistral.api_key,
            model=settings.mistral.model,
            temperature=settings.mistral.temperature,
            max_tokens=settings.mistral.max_tokens,
            context_manager=self._context_manager,
            bot_name=self._bot_name,
        )

        self._aiohttp_session = aiohttp.ClientSession()
        tts_service = ElevenLabsHttpTTSService(
            api_key=settings.elevenlabs.api_key,
            voice_id=settings.elevenlabs.voice_id,
            aiohttp_session=self._aiohttp_session,
            model=settings.elevenlabs.model,
            sample_rate=settings.meeting_baas.sample_rate,
            aggregate_sentences=False,
            params=ElevenLabsHttpTTSService.InputParams(
                stability=settings.elevenlabs.stability,
                similarity_boost=settings.elevenlabs.similarity_boost,
            ),
        )

        output_proc = MeetingBaaSOutputProcessor(transport=self.transport)

        pipeline = Pipeline(
            processors=[
                input_proc,
                stt_proc,
                self._brain_proc,
                tts_service,
                output_proc,
            ]
        )

        self._task = PipelineTask(
            pipeline=pipeline,
            idle_timeout_secs=None,
        )

        self._runner = PipelineRunner(handle_sigint=False)

        logger.info("Meeting pipeline setup complete (meeting_id=%s)", self._meeting_id)

    async def run(self) -> None:
        """Run the meeting pipeline."""
        if not self._task or not self._runner:
            raise RuntimeError("Pipeline not set up")

        logger.info("Starting meeting pipeline...")
        # PipelineRunner automatically sends StartFrame — do not send manually
        await self._runner.run(self._task)

    async def stop(self) -> None:
        """Stop the meeting pipeline and generate summary."""
        if self._task:
            await self._task.queue_frame(EndFrame())
            logger.info("Meeting pipeline stopped")

        # Generate post-meeting summary
        await self._generate_post_meeting_summary()

        # Close HTTP session
        if self._aiohttp_session:
            await self._aiohttp_session.close()
            self._aiohttp_session = None

    async def _generate_post_meeting_summary(self) -> None:
        """Generate and save post-meeting summary."""
        if not self._brain_proc or not self._summarizer:
            return

        transcript = self._brain_proc.get_transcript()
        if not transcript:
            logger.info("No transcript to summarize")
            return

        recorded_data = self._brain_proc.get_recorded_data()
        participants = list(set(entry.get("speaker", "unknown") for entry in transcript))

        try:
            summary = await self._summarizer.generate_summary(
                meeting_id=self._meeting_id,
                title=f"Meeting {self._meeting_url or self._meeting_id[:8]}",
                transcript=transcript,
                participants=participants,
                recorded_data=recorded_data,
            )

            # Save transcript to DB
            if self._context_manager:
                await self._context_manager.save_transcript(self._meeting_id, transcript)

            # Log summary
            md = self._summarizer.format_as_markdown(summary)
            logger.info("Post-meeting summary generated:\n%s", md)

        except Exception as e:
            logger.error("Failed to generate post-meeting summary: %s", e)
