import asyncio
import logging
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
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from src.meeting.transports.base import BaseMeetingTransport
from src.config.settings import settings
from src.pipeline.meeting_processors.voxtral_stt import VoxtralSTTProcessor
from src.agent.brain import MistralAgentBrain

logger = logging.getLogger(__name__)


class MeetingBaaSInputProcessor(FrameProcessor):
    """Reads audio from MeetingBaaS WebSocket and pushes InputAudioRawFrame."""

    def __init__(self, *, transport: BaseMeetingTransport, **kwargs):
        super().__init__(name="MeetingBaaSInput", **kwargs)
        self._transport = transport
        self._read_task: Optional[asyncio.Task] = None

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
            logger.error(f"Transport read error: {e}")


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
                logger.info(f"Sent audio response: {len(frame.audio)} bytes")
            except Exception as e:
                logger.error(f"Error sending audio: {e}")
        else:
            await self.push_frame(frame, direction)


class MeetingPipeline:
    """Main meeting pipeline using Pipecat framework."""

    def __init__(self, transport: BaseMeetingTransport):
        self.transport = transport
        self._task: Optional[PipelineTask] = None
        self._runner: Optional[PipelineRunner] = None

    async def setup(self) -> None:
        """Set up the Pipecat pipeline."""
        logger.info("Setting up meeting pipeline...")

        input_proc = MeetingBaaSInputProcessor(transport=self.transport)

        stt_proc = VoxtralSTTProcessor(
            api_key=settings.mistral.api_key,
            sample_rate=settings.meeting_baas.sample_rate,
        )

        brain_proc = MistralAgentBrain(
            api_key=settings.mistral.api_key,
            model=settings.mistral.model,
            temperature=settings.mistral.temperature,
            max_tokens=settings.mistral.max_tokens,
        )

        tts_service = ElevenLabsTTSService(
            api_key=settings.elevenlabs.api_key,
            voice_id=settings.elevenlabs.voice_id,
            model=settings.elevenlabs.model,
            params=ElevenLabsTTSService.InputParams(
                stability=settings.elevenlabs.stability,
                similarity_boost=settings.elevenlabs.similarity_boost,
            ),
        )

        output_proc = MeetingBaaSOutputProcessor(transport=self.transport)

        pipeline = Pipeline(
            processors=[
                input_proc,
                stt_proc,
                brain_proc,
                tts_service,
                output_proc,
            ]
        )

        self._task = PipelineTask(
            pipeline=pipeline,
            idle_timeout_secs=None,
        )

        self._runner = PipelineRunner(handle_sigint=False)

        logger.info("Meeting pipeline setup complete")

    async def run(self) -> None:
        """Run the meeting pipeline."""
        if not self._task or not self._runner:
            raise RuntimeError("Pipeline not set up")

        logger.info("Starting meeting pipeline...")
        await self._task.queue_frame(StartFrame())
        await self._runner.run(self._task)

    async def stop(self) -> None:
        """Stop the meeting pipeline."""
        if self._task:
            await self._task.queue_frame(EndFrame())
            logger.info("Meeting pipeline stopped")
