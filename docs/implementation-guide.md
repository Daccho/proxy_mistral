# Implementation Guide

This guide provides practical implementation patterns for integrating the APIs documented in [api-guide.md](./api-guide.md). It focuses on how the pieces fit together and common patterns for building a real-time meeting AI assistant.

---

## Architecture Overview

```
Meeting (Google Meet / Zoom / Teams)
    |
    v
Meeting BaaS Bot  <-- POST /v2/bots with streaming_config
    |
    | Meeting BaaS connects TO our WebSocket server
    | JSON: speaker metadata [{name, id, timestamp, isSpeaking}]
    | Binary: raw PCM audio (16kHz mono S16LE)
    v
Your WS Server (local)  <--- exposed via ngrok tunnel
    |
    +---> Voxtral Realtime STT (streaming transcription)
    |         |
    |         v
    |     Mistral Agent (conversation + tools + document library)
    |         |
    |         v
    +---> ElevenLabs TTS (streaming speech synthesis)
    |         |
    |         v
    +---> WebSocket send (binary PCM back to meeting)
```

> **Local development:** An ngrok tunnel is required to expose your local WebSocket
> server to the internet so that Meeting BaaS can connect to it. The `MeetingBaaSTransport`
> class handles this automatically via `pyngrok`.

---

## 1. End-to-End Pipeline with Pipecat

The recommended approach uses Pipecat to orchestrate the full audio pipeline.

### 1.1 Full Pipeline Setup

```python
import os
import asyncio
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.services.mistral.llm import MistralLLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.deepgram import DeepgramSTTService
from pipecat.processors.aggregators.llm_context import (
    LLMContext,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame


async def run_pipeline(transport):
    # STT: Deepgram (or replace with Voxtral for Mistral-native STT)
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    # LLM: Mistral
    llm = MistralLLMService(
        api_key=os.getenv("MISTRAL_API_KEY"),
        model="mistral-medium-latest",
    )

    # TTS: ElevenLabs Flash v2.5
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="JBFqnCBsd6RMkjVDRZzb",
        model="eleven_flash_v2_5",
        sample_rate=16000,
    )

    # Conversation context
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful meeting assistant. "
                "Listen to the conversation and provide useful input when asked."
            ),
        },
    ]

    context = LLMContext(messages)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # Build the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
```

### 1.2 Alternative: Voxtral Realtime for STT

If you want to use Mistral's own Voxtral for STT instead of Deepgram, you can
create a custom Pipecat processor that wraps the Voxtral realtime client:

```python
import asyncio
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, AudioRawFrame, TranscriptionFrame
from mistralai import Mistral
from mistralai.models import (
    AudioFormat,
    TranscriptionStreamTextDelta,
    TranscriptionStreamDone,
)


class VoxtralRealtimeSTT(FrameProcessor):
    """Custom Pipecat processor wrapping Voxtral Realtime STT."""

    def __init__(self, api_key: str):
        super().__init__()
        self._client = Mistral(api_key=api_key)
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._transcription_task = None

    async def _audio_generator(self):
        """Yield audio chunks from the internal queue."""
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                break
            yield chunk

    async def _run_transcription(self):
        """Background task that runs the Voxtral streaming transcription."""
        audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)

        async for event in self._client.audio.realtime.transcribe_stream(
            audio_stream=self._audio_generator(),
            model="voxtral-mini-transcribe-realtime-2602",
            audio_format=audio_format,
            target_streaming_delay_ms=500,
        ):
            if isinstance(event, TranscriptionStreamTextDelta):
                # Push transcription downstream
                await self.push_frame(
                    TranscriptionFrame(text=event.text, user_id="", timestamp=""),
                    FrameDirection.DOWNSTREAM,
                )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, AudioRawFrame):
            # Start transcription on first audio frame
            if self._transcription_task is None:
                self._transcription_task = asyncio.create_task(
                    self._run_transcription()
                )
            # Feed audio into the queue
            await self._audio_queue.put(frame.audio)
        else:
            await self.push_frame(frame, direction)
```

---

## 2. Meeting BaaS Integration

### 2.1 Deploy a Bot to a Meeting (v2 API)

Our implementation uses the v2 API with `streaming_config`. The bot streams audio
over a WebSocket connection rather than using the v1 `audio_separate_raw` webhook approach.

```python
import requests
import os


def deploy_bot(meeting_url: str, ws_url: str) -> dict:
    """Deploy a Meeting BaaS bot to the specified meeting.

    Args:
        meeting_url: The meeting URL to join (Google Meet, Zoom, or Teams).
        ws_url: The WebSocket URL that Meeting BaaS will connect to
                (e.g. an ngrok wss:// URL for local dev).

    Returns:
        Response dict: {"success": true, "data": {"bot_id": "..."}}
    """
    headers = {
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": os.getenv("MEETING_BAAS_API_KEY"),
    }

    config = {
        "meeting_url": meeting_url,
        "bot_name": "AI Assistant",
        "bot_image": "https://example.com/bot-avatar.png",
        "streaming_enabled": True,
        "streaming_config": {
            "output_url": ws_url,   # Meeting BaaS sends audio here
            "input_url": ws_url,    # Meeting BaaS reads audio from here
            "audio_frequency": 16000,
        },
    }

    response = requests.post(
        "https://api.meetingbaas.com/v2/bots",
        json=config,
        headers=headers,
    )
    response.raise_for_status()
    return response.json()
```

> **ngrok requirement:** For local development, you need an ngrok tunnel to expose
> your WebSocket server. Our `MeetingBaaSTransport` handles this automatically:
> it starts a local WS server, creates an ngrok tunnel, converts the URL to `wss://`,
> and passes it as the `output_url`/`input_url` in the bot config.

### 2.2 Deploy a Speaking Bot (v2 Streaming)

Our speaking bot uses the same v2 streaming API as the regular bot. The difference
is in the pipeline: we process incoming audio with STT, pass it through the Mistral
agent, generate responses with ElevenLabs TTS, and send the audio back over WebSocket.

```python
import requests
import os


def deploy_speaking_bot(meeting_url: str, ws_url: str) -> dict:
    """Deploy a speaking bot using v2 streaming API.

    This is functionally the same as deploy_bot() -- the 'speaking' behavior
    comes from our pipeline processing, not from a different Meeting BaaS endpoint.
    """
    headers = {
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": os.getenv("MEETING_BAAS_API_KEY"),
    }

    payload = {
        "meeting_url": meeting_url,
        "bot_name": "AI Meeting Assistant",
        "bot_image": "https://example.com/bot-avatar.png",
        "streaming_enabled": True,
        "streaming_config": {
            "output_url": ws_url,
            "input_url": ws_url,
            "audio_frequency": 16000,
        },
    }

    response = requests.post(
        "https://api.meetingbaas.com/v2/bots",
        json=payload,
        headers=headers,
    )
    response.raise_for_status()
    return response.json()
```

**Removing a bot from a meeting:**

```python
def leave_meeting(bot_id: str) -> None:
    """Remove a bot from the meeting via v2 API."""
    response = requests.post(
        f"https://api.meetingbaas.com/v2/bots/{bot_id}/leave",
        headers={
            "Content-Type": "application/json",
            "x-meeting-baas-api-key": os.getenv("MEETING_BAAS_API_KEY"),
        },
    )
    response.raise_for_status()
```

### 2.3 WebSocket Audio Receiver (v2 Streaming Protocol)

With the v2 streaming API, Meeting BaaS connects to our WebSocket server and sends
a mix of JSON text messages (speaker metadata) and binary messages (raw PCM audio).
This is different from the v1 `audio_separate_raw` format which wrapped everything
in a JSON envelope with base64-encoded audio.

```python
import asyncio
import json
from typing import Optional, Dict, Any, List
import websockets


class MeetingAudioProcessor:
    """Receives audio from Meeting BaaS v2 streaming WebSocket.

    Protocol:
    - JSON text messages: speaker metadata
      [{"name": "John", "id": 1, "timestamp": 12345, "isSpeaking": true}, ...]
    - Binary messages: raw PCM audio (16kHz mono 16-bit S16LE)

    The speaker metadata arrives interleaved with audio, so we track the
    current active speaker and associate it with incoming audio chunks.
    """

    def __init__(self):
        self.current_speakers: List[Dict[str, Any]] = []
        self.audio_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    async def handle_connection(self, websocket, path=""):
        """Handle incoming WebSocket from Meeting BaaS."""
        print("Meeting BaaS connected")

        try:
            async for message in websocket:
                if isinstance(message, str):
                    # JSON: speaker metadata
                    try:
                        self.current_speakers = json.loads(message)
                    except json.JSONDecodeError:
                        pass
                else:
                    # Binary: raw PCM audio
                    active = next(
                        (s for s in self.current_speakers if s.get("isSpeaking")),
                        None,
                    )
                    audio_data = {
                        "participant_id": str(active["id"]) if active else "unknown",
                        "name": active["name"] if active else "unknown",
                        "audio": message,  # raw bytes, NOT base64
                        "timestamp": active.get("timestamp", 0) if active else 0,
                    }
                    await self.audio_queue.put(audio_data)
                    await self.process_audio(audio_data)

        except websockets.exceptions.ConnectionClosed:
            print("Meeting BaaS WebSocket disconnected")

    async def process_audio(self, audio_data: Dict[str, Any]):
        """Override this to process audio chunks."""
        print(
            f"Audio: {len(audio_data['audio'])} bytes from "
            f"{audio_data['name']}"
        )

    async def start(self, host="0.0.0.0", port=8765):
        async with websockets.serve(self.handle_connection, host, port):
            print(f"WebSocket server listening on {host}:{port}")
            await asyncio.Future()  # Run forever
```

> **Sending audio back:** To speak in the meeting, send binary PCM data on the
> same WebSocket connection: `await websocket.send(pcm_bytes)`. No MP3 encoding
> or REST API calls are needed with the v2 streaming approach.

---

## 3. Mistral Agent with Document Library

### 3.1 Setting Up an Agent with RAG

```python
import os
import json
from mistralai import Mistral, FunctionResultEntry

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])


def setup_agent_with_documents(document_paths: list[str]) -> str:
    """Create a library, upload documents, and create an agent. Returns agent_id."""

    # Create a library
    library = client.beta.libraries.create(
        name="Meeting Context",
        description="Documents relevant to the meeting",
    )

    # Upload documents
    for path in document_paths:
        client.beta.libraries.documents.upload(
            library_id=library.id,
            file={
                "file_name": os.path.basename(path),
                "content": open(path, "rb"),
            },
        )

    # Create agent with document library + function calling
    agent = client.beta.agents.create(
        model="mistral-medium-2505",
        name="Meeting Assistant Agent",
        description="AI assistant for meetings with access to company documents",
        instructions=(
            "You are a meeting assistant. Use the document library to find "
            "relevant information. Use function calling to perform actions. "
            "Keep responses concise and conversational."
        ),
        tools=[
            {"type": "document_library", "library_ids": [library.id]},
            {
                "type": "function",
                "function": {
                    "name": "create_action_item",
                    "description": "Create an action item from the meeting discussion",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "assignee": {"type": "string"},
                            "task": {"type": "string"},
                            "due_date": {"type": "string"},
                        },
                        "required": ["assignee", "task"],
                    },
                },
            },
        ],
        completion_args={
            "temperature": 0.3,
            "top_p": 0.95,
        },
    )

    return agent.id
```

### 3.2 Conversation Loop with Function Calling

```python
import json
from mistralai import Mistral, FunctionResultEntry


class AgentConversation:
    """Manages an ongoing conversation with a Mistral agent."""

    def __init__(self, client: Mistral, agent_id: str):
        self.client = client
        self.agent_id = agent_id
        self.conversation_id = None
        self.function_handlers = {}

    def register_function(self, name: str, handler):
        """Register a local function handler."""
        self.function_handlers[name] = handler

    def send_message(self, message: str) -> str:
        """Send a message and get a response, handling any function calls."""
        if self.conversation_id is None:
            response = self.client.beta.conversations.start(
                agent_id=self.agent_id,
                inputs=message,
            )
            self.conversation_id = response.conversation_id
        else:
            response = self.client.beta.conversations.append(
                conversation_id=self.conversation_id,
                inputs=message,
            )

        # Handle function calls in a loop
        while response.outputs and response.outputs[-1].type == "function.call":
            output = response.outputs[-1]
            func_name = output.name
            func_args = json.loads(output.arguments)

            if func_name in self.function_handlers:
                result = self.function_handlers[func_name](**func_args)
                func_result = json.dumps(result)
            else:
                func_result = json.dumps({"error": f"Unknown function: {func_name}"})

            entry = FunctionResultEntry(
                tool_call_id=output.tool_call_id,
                result=func_result,
            )

            response = self.client.beta.conversations.append(
                conversation_id=self.conversation_id,
                inputs=[entry],
            )

        # Return the final text response
        if response.outputs:
            return str(response.outputs[-1])
        return ""


# Usage
def create_action_item(assignee: str, task: str, due_date: str = None) -> dict:
    """Example function handler."""
    return {
        "status": "created",
        "assignee": assignee,
        "task": task,
        "due_date": due_date,
    }


client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
conversation = AgentConversation(client, agent_id="your-agent-id")
conversation.register_function("create_action_item", create_action_item)

reply = conversation.send_message("Create an action item for John to review the Q4 report by Friday.")
print(reply)
```

---

## 4. ElevenLabs Voice Cloning + Streaming TTS

### 4.1 Clone a Voice and Stream TTS

```python
import os
from elevenlabs.client import ElevenLabs
from elevenlabs import stream


def setup_cloned_voice(sample_paths: list[str]) -> str:
    """Clone a voice from audio samples. Returns voice_id."""
    client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

    voice = client.voices.ivc.create(
        name="Meeting Bot Voice",
        description="Professional, clear speaking voice for meeting bot.",
        files=sample_paths,
    )

    return voice.voice_id


def stream_speech(text: str, voice_id: str):
    """Stream TTS using the cloned voice with Flash v2.5."""
    client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

    audio_stream = client.text_to_speech.stream(
        text=text,
        voice_id=voice_id,
        model_id="eleven_flash_v2_5",
    )

    # Collect raw audio bytes for sending to a meeting
    audio_chunks = []
    for chunk in audio_stream:
        if isinstance(chunk, bytes):
            audio_chunks.append(chunk)

    return b"".join(audio_chunks)
```

### 4.2 PCM Output for Real-Time Pipelines

```python
from elevenlabs.client import ElevenLabs

client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Use PCM format for direct pipeline integration (no MP3 decoding needed)
audio = client.text_to_speech.convert(
    text="This is optimized for real-time pipelines.",
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    model_id="eleven_flash_v2_5",
    output_format="pcm_16000",  # 16kHz PCM, matches Voxtral/Meeting BaaS format
)
```

---

## 5. Voxtral Realtime Streaming STT

### 5.1 Standalone Transcription Server (Reference Implementation)

> **Note:** This is a reference implementation showing how Voxtral Realtime STT could
> be used as a standalone transcription server. Our actual `VoxtralSTTProcessor`
> (in `src/pipeline/meeting_processors/voxtral_stt.py`) is currently a **stub** -- the
> `_transcribe()` method returns `None` and needs to be connected to the Voxtral Realtime
> WebSocket API. The code below shows the intended integration pattern.

```python
import asyncio
import json
from mistralai import Mistral
from mistralai.models import (
    AudioFormat,
    TranscriptionStreamTextDelta,
    TranscriptionStreamDone,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
)
from mistralai.extra.realtime import UnknownRealtimeEvent


class TranscriptionServer:
    """WebSocket server that receives meeting audio and transcribes it with Voxtral."""

    def __init__(self, mistral_api_key: str):
        self.client = Mistral(api_key=mistral_api_key)
        self.audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)

    async def transcribe_audio_stream(self, audio_generator):
        """Run Voxtral realtime transcription on an audio stream."""
        transcript_parts = []

        async for event in self.client.audio.realtime.transcribe_stream(
            audio_stream=audio_generator,
            model="voxtral-mini-transcribe-realtime-2602",
            audio_format=self.audio_format,
            target_streaming_delay_ms=500,
        ):
            if isinstance(event, RealtimeTranscriptionSessionCreated):
                print("Voxtral session created")
            elif isinstance(event, TranscriptionStreamTextDelta):
                transcript_parts.append(event.text)
                yield event.text
            elif isinstance(event, TranscriptionStreamDone):
                print("Transcription complete")
            elif isinstance(event, RealtimeTranscriptionError):
                print(f"Transcription error: {event}")
            elif isinstance(event, UnknownRealtimeEvent):
                continue

    async def handle_meeting_audio(self, websocket):
        """Receive meeting audio via v2 WebSocket, transcribe, and respond.

        With v2 streaming, audio arrives as binary PCM frames (not the v1
        audio_separate_raw JSON envelope), so we can feed it directly to Voxtral.
        """
        audio_queue = asyncio.Queue()

        async def audio_generator():
            while True:
                chunk = await audio_queue.get()
                if chunk is None:
                    break
                yield chunk

        # Start transcription in background
        transcription_task = asyncio.create_task(
            self._process_transcription(audio_generator())
        )

        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    # v2: binary PCM audio directly
                    await audio_queue.put(message)
                # JSON messages (speaker metadata) can be handled separately
        finally:
            await audio_queue.put(None)
            await transcription_task

    async def _process_transcription(self, audio_generator):
        async for text_delta in self.transcribe_audio_stream(audio_generator):
            print(text_delta, end="", flush=True)
```

---

## Common Gotchas and Tips

### Audio Format Compatibility

All components in the pipeline need compatible audio formats:

| Component                        | Expected Format                         |
| -------------------------------- | --------------------------------------- |
| Meeting BaaS v2 streaming output | 16kHz mono S16LE PCM (raw binary)       |
| Meeting BaaS v2 streaming input  | 16kHz mono S16LE PCM (raw binary)       |
| Voxtral Realtime input           | 16kHz mono S16LE PCM (`pcm_s16le`)      |
| ElevenLabs output                | Configurable; use `pcm_16000` for match  |
| Pipecat default                  | Configurable via TransportParams         |

With the v2 streaming API, there is no format mismatch: both input and output use raw
PCM over WebSocket. No MP3 encoding/decoding is needed (unlike the v1 `output_audio` REST
endpoint which required base64-encoded MP3).

### Rate Limits and Concurrency

- **Mistral Agents API**: Rate limits apply per API key. The conversation history is stored server-side, so you do not need to resend the full context.
- **Voxtral Realtime**: One WebSocket connection per transcription session. For multiple participants, run parallel sessions.
- **ElevenLabs Flash v2.5**: Optimized for low latency (~75ms). Character limits apply per request (40,000 chars for Flash).
- **Meeting BaaS**: Supports up to 16 concurrent per-participant audio streams on Google Meet and Zoom, 9 on Teams.

### Environment Variables

```bash
# .env file
MISTRAL_API_KEY=your_mistral_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key       # if using Deepgram STT
MEETING_BAAS_API_KEY=your_meetingbaas_api_key # from dashboard.meetingbaas.com
NGROK_AUTHTOKEN=your_ngrok_authtoken         # required for local WS tunnel
```

### Python Dependencies

```
# requirements.txt
mistralai[agents,realtime]
elevenlabs
pipecat-ai[mistral,elevenlabs,daily,silero]
websockets
requests
python-dotenv
pyaudio          # for microphone input
```

---

## Sources

- [Mistral Agents & Conversations](https://docs.mistral.ai/agents/agents)
- [Mistral Function Calling](https://docs.mistral.ai/agents/tools/function_calling)
- [Mistral Document Library](https://docs.mistral.ai/agents/tools/built-in/document_library)
- [Mistral Beta Libraries API](https://docs.mistral.ai/api/endpoint/beta/libraries)
- [Mistral Realtime Transcription](https://docs.mistral.ai/capabilities/audio_transcription/realtime_transcription)
- [Mistral Python SDK](https://github.com/mistralai/client-python)
- [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python)
- [ElevenLabs Models](https://elevenlabs.io/docs/overview/models)
- [ElevenLabs Streaming](https://elevenlabs.io/docs/api-reference/streaming)
- [ElevenLabs Instant Voice Cloning](https://elevenlabs.io/docs/developers/guides/cookbooks/voices/instant-voice-cloning)
- [Meeting BaaS Bots API](https://www.meetingbaas.com/en/api/bots-api)
- [Meeting BaaS Speaking Bots API](https://www.meetingbaas.com/en/api/speaking-bots-api)
- [Meeting BaaS Speaking Bots Docs](https://docs.meetingbaas.com/speaking-bots)
- [Recall.ai Per-Participant Audio](https://docs.recall.ai/docs/how-to-get-separate-audio-per-participant-realtime)
- [Recall.ai Output Audio](https://docs.recall.ai/docs/output-audio-in-meetings)
- [Pipecat Introduction](https://docs.pipecat.ai/getting-started/introduction)
- [Pipecat Quickstart](https://docs.pipecat.ai/getting-started/quickstart)
- [Pipecat GitHub](https://github.com/pipecat-ai/pipecat)
- [Pipecat MistralLLMService Source](https://reference-server.pipecat.ai/en/latest/_modules/pipecat/services/mistral/llm.html)
- [Pipecat ElevenLabsTTSService Source](https://reference-server.pipecat.ai/en/latest/_modules/pipecat/services/elevenlabs/tts.html)
- [Meeting BaaS Speaking Bot GitHub](https://github.com/Meeting-Baas/speaking-meeting-bot)
