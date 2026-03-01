# API Reference Guide

This document provides accurate, working code examples for each API used in this project, sourced from official documentation.

---

## 1. Mistral Agents API (Python SDK `mistralai`)

**Install:**

```bash
uv add "mistralai[agents]"
```

> Requires Python 3.10+. The `[agents]` extra is required for agents-related features.

**Official docs:** [Agents & Conversations](https://docs.mistral.ai/agents/agents) | [Function Calling](https://docs.mistral.ai/agents/tools/function_calling) | [Document Library](https://docs.mistral.ai/agents/tools/built-in/document_library)

### 1.1 Creating an Agent

```python
import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)

# Simple agent
simple_agent = client.beta.agents.create(
    model="mistral-medium-2505",
    description="A simple Agent with persistent state.",
    name="Simple Agent",
)

# Agent with web search tool
websearch_agent = client.beta.agents.create(
    model="mistral-medium-2505",
    description="Agent able to search information over the web",
    name="Websearch Agent",
    instructions="You have the ability to perform web searches with `web_search`",
    tools=[{"type": "web_search"}],
    completion_args={
        "temperature": 0.3,
        "top_p": 0.95,
    },
)
```

### 1.2 Starting a Conversation

```python
# Start conversation with an agent
response = client.beta.conversations.start(
    agent_id=simple_agent.id,
    inputs="Who is Albert Einstein?",
)

# You can also pass structured messages:
response = client.beta.conversations.start(
    agent_id=simple_agent.id,
    inputs=[{"role": "user", "content": "Who is Albert Einstein?"}],
)

# Or start without an agent (using a model directly):
response = client.beta.conversations.start(
    model="mistral-medium-latest",
    inputs=[{"role": "user", "content": "Who is Albert Einstein?"}],
)

# Opt out of cloud storage with store=False
response = client.beta.conversations.start(
    agent_id=simple_agent.id,
    inputs="Hello",
    store=False,
)
```

### 1.3 Appending Messages to an Ongoing Conversation

```python
# Continue a conversation by referencing its conversation_id
response = client.beta.conversations.append(
    conversation_id=response.conversation_id,
    inputs="Translate to French.",
)

# The conversation history is automatically maintained server-side
# Each append returns a new response with the same conversation_id
print(response.outputs[-1])
```

### 1.4 Function Calling (Tool Definitions and Handling Tool Calls)

```python
from typing import Dict
from mistralai import Mistral, FunctionResultEntry
import json
import os

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)


# Step 1: Define your local function
def get_european_central_bank_interest_rate(date: str) -> Dict[str, str]:
    """
    Retrieve the real interest rate of the European Central Bank for a given date.
    """
    interest_rate = "2.5%"
    return {
        "date": date,
        "interest_rate": interest_rate,
    }


# Step 2: Create an agent with a function tool
ecb_interest_rate_agent = client.beta.agents.create(
    model="mistral-medium-2505",
    description="Can find the current interest rate of the European central bank",
    name="ecb-interest-rate-agent",
    tools=[
        {
            "type": "function",
            "function": {
                "name": "get_european_central_bank_interest_rate",
                "description": "Retrieve the real interest rate of European central bank.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                        },
                    },
                    "required": ["date"],
                },
            },
        },
    ],
)

# Step 3: Start the conversation
response = client.beta.conversations.start(
    agent_id=ecb_interest_rate_agent.id,
    inputs=[{"role": "user", "content": "Whats the current 2025 real interest rate?"}],
)

# Step 4: Handle the function call
if (
    response.outputs[-1].type == "function.call"
    and response.outputs[-1].name == "get_european_central_bank_interest_rate"
):
    # Execute the local function with the model's arguments
    function_result = json.dumps(
        get_european_central_bank_interest_rate(
            **json.loads(response.outputs[-1].arguments)
        )
    )

    # Provide the result back to the agent
    user_function_calling_entry = FunctionResultEntry(
        tool_call_id=response.outputs[-1].tool_call_id,
        result=function_result,
    )

    # Retrieve the final response
    response = client.beta.conversations.append(
        conversation_id=response.conversation_id,
        inputs=[user_function_calling_entry],
    )
    print(response.outputs[-1])
else:
    print(response.outputs[-1])
```

### 1.5 Document Library: Creating Libraries and Uploading Files

```python
import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)

# Step 1: Create a library
new_library = client.beta.libraries.create(
    name="My Research Library",
    description="Documents for research queries",
    # chunk_size=1024,  # optional: control document chunking
)

# Step 2: Upload a file to the library
res = client.beta.libraries.documents.upload(
    library_id=new_library.id,
    file={
        "file_name": "research_paper.pdf",
        "content": open("research_paper.pdf", "rb"),
    },
)

# Step 3: List libraries
libraries = client.beta.libraries.list()

# Step 4: Create an agent with document library access
library_agent = client.beta.agents.create(
    model="mistral-medium-2505",
    name="Document Library Agent",
    description="Agent used to access documents from the document library.",
    instructions="Use the library tool to access external documents.",
    tools=[{"type": "document_library", "library_ids": [new_library.id]}],
    completion_args={
        "temperature": 0.3,
        "top_p": 0.95,
    },
)

# Step 5: Query the agent about uploaded documents
response = client.beta.conversations.start(
    agent_id=library_agent.id,
    inputs="How does the vision encoder for pixtral 12b work",
)
print(response.outputs[-1])
```

### 1.6 File Management

```python
from mistralai import Mistral
import os

with Mistral(api_key=os.getenv("MISTRAL_API_KEY", "")) as mistral:
    # Upload a file (max 512 MB)
    res = mistral.files.upload(file={
        "file_name": "example.pdf",
        "content": open("example.pdf", "rb"),
    })

    # List files
    res = mistral.files.list(page=0, page_size=100, include_total=True)

    # Retrieve file metadata
    res = mistral.files.retrieve(file_id="<file-uuid>")

    # Download a file
    res = mistral.files.download(file_id="<file-uuid>")

    # Get a signed URL (expires in 24h by default)
    res = mistral.files.get_signed_url(file_id="<file-uuid>", expiry=24)

    # Delete a file
    res = mistral.files.delete(file_id="<file-uuid>")
```

### Key Notes - Mistral Agents API

- Agents are persistent configurations (model + tools + instructions + completion_args)
- Conversations maintain server-side history; use `conversation_id` to continue
- Use `store=False` to prevent conversation history from being stored on Mistral's cloud
- Built-in tools: `web_search`, `code_interpreter`, `image_generation`, `document_library`
- Custom functions require you to handle the function call locally and return results via `FunctionResultEntry`
- File uploads to libraries are recommended as streams for large files to avoid memory issues

---

## 2. Mistral Voxtral Realtime (Streaming STT)

**Install:**

```bash
uv add "mistralai[realtime]"
```

**Official docs:** [Realtime Transcription](https://docs.mistral.ai/capabilities/audio_transcription/realtime_transcription)

### 2.1 WebSocket Connection for Streaming Audio to Text

```python
import asyncio
from mistralai import Mistral
from mistralai.extra.realtime import UnknownRealtimeEvent
from mistralai.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
)

api_key = "YOUR_MISTRAL_API_KEY"
client = Mistral(api_key=api_key)


async def main():
    audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)
    audio_stream = ...  # your audio source (AsyncIterator[bytes])

    try:
        async for event in client.audio.realtime.transcribe_stream(
            audio_stream=audio_stream,
            model="voxtral-mini-transcribe-realtime-2602",
            audio_format=audio_format,
        ):
            if isinstance(event, RealtimeTranscriptionSessionCreated):
                print("Session created.")
            elif isinstance(event, TranscriptionStreamTextDelta):
                print(event.text, end="", flush=True)
            elif isinstance(event, TranscriptionStreamDone):
                print("\nTranscription done.")
            elif isinstance(event, RealtimeTranscriptionError):
                print(f"Error: {event}")
            elif isinstance(event, UnknownRealtimeEvent):
                continue
    except KeyboardInterrupt:
        print("Stopping...")


asyncio.run(main())
```

### 2.2 Audio Format Requirements

| Parameter      | Value            |
| -------------- | ---------------- |
| Encoding       | `pcm_s16le`      |
| Sample Rate    | 16000 Hz (16kHz) |
| Channels       | 1 (mono)         |
| Bit Depth      | 16-bit signed    |
| Byte Order     | Little-endian    |

```python
from mistralai.models import AudioFormat

audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)
```

### 2.3 Microphone Input (PyAudio)

```python
import asyncio
from typing import AsyncIterator
import pyaudio


async def iter_microphone(
    sample_rate: int,
    chunk_duration_ms: int,
) -> AsyncIterator[bytes]:
    """Captures microphone PCM chunks (16-bit mono)."""
    p = pyaudio.PyAudio()
    chunk_samples = int(sample_rate * chunk_duration_ms / 1000)

    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=chunk_samples,
    )

    loop = asyncio.get_running_loop()
    try:
        while True:
            data = await loop.run_in_executor(
                None, stream.read, chunk_samples, False
            )
            yield data
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
```

### 2.4 Full Example with Microphone

```python
import asyncio
from mistralai import Mistral
from mistralai.extra.realtime import UnknownRealtimeEvent
from mistralai.models import (
    AudioFormat,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
    RealtimeTranscriptionError,
)

client = Mistral(api_key="YOUR_MISTRAL_API_KEY")


async def main():
    audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)
    audio_stream = iter_microphone(sample_rate=16000, chunk_duration_ms=480)

    async for event in client.audio.realtime.transcribe_stream(
        audio_stream=audio_stream,
        model="voxtral-mini-transcribe-realtime-2602",
        audio_format=audio_format,
        target_streaming_delay_ms=1000,  # Balance speed vs accuracy
    ):
        if isinstance(event, TranscriptionStreamTextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, TranscriptionStreamDone):
            print("\n[Done]")


asyncio.run(main())
```

### Key Notes - Voxtral Realtime

- Model: `voxtral-mini-transcribe-realtime-2602`
- `target_streaming_delay_ms` controls the latency/accuracy tradeoff (lower = faster but potentially less accurate; configurable down to sub-200ms)
- At 480ms delay, word error rate stays within 1-2% of offline accuracy
- Natively supports 13 languages: English, Chinese, Hindi, Spanish, Arabic, French, Portuguese, Russian, German, Japanese, Korean, Italian, Dutch
- Open weights available under Apache 2.0 license on Hugging Face
- Event types: `RealtimeTranscriptionSessionCreated`, `TranscriptionStreamTextDelta`, `TranscriptionStreamDone`, `RealtimeTranscriptionError`

---

## 3. ElevenLabs Python SDK (`elevenlabs`)

**Install:**

```bash
uv add elevenlabs
```

**Official docs:** [GitHub](https://github.com/elevenlabs/elevenlabs-python) | [Streaming](https://elevenlabs.io/docs/api-reference/streaming) | [Models](https://elevenlabs.io/docs/overview/models)

### 3.1 Basic Text-to-Speech

```python
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play

load_dotenv()

elevenlabs = ElevenLabs()  # Uses ELEVENLABS_API_KEY env var

audio = elevenlabs.text_to_speech.convert(
    text="The first move is what sets everything in motion.",
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    model_id="eleven_flash_v2_5",
    output_format="mp3_44100_128",
)

play(audio)
```

### 3.2 Streaming TTS with Flash v2.5

```python
from elevenlabs import stream
from elevenlabs.client import ElevenLabs

elevenlabs = ElevenLabs(api_key="YOUR_API_KEY")

audio_stream = elevenlabs.text_to_speech.stream(
    text="This is a test of streaming text to speech.",
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    model_id="eleven_flash_v2_5",
)

# Option 1: Play directly
stream(audio_stream)

# Option 2: Process chunks manually
for chunk in audio_stream:
    if isinstance(chunk, bytes):
        # Process raw audio bytes (e.g., send to WebSocket, write to file)
        process_audio(chunk)
```

### 3.3 Async Streaming

```python
import asyncio
from elevenlabs.client import AsyncElevenLabs

elevenlabs = AsyncElevenLabs(api_key="YOUR_API_KEY")


async def stream_tts():
    audio_stream = await elevenlabs.text_to_speech.stream(
        text="Hello from the async client.",
        voice_id="JBFqnCBsd6RMkjVDRZzb",
        model_id="eleven_flash_v2_5",
    )
    async for chunk in audio_stream:
        if isinstance(chunk, bytes):
            process_audio(chunk)


asyncio.run(stream_tts())
```

### 3.4 Instant Voice Cloning

```python
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play

elevenlabs = ElevenLabs(api_key="YOUR_API_KEY")

# Upload audio samples and create a cloned voice
voice = elevenlabs.voices.ivc.create(
    name="Alex",
    description="An old American male voice with a slight hoarseness in his throat. Perfect for news.",
    files=["./sample_0.mp3", "./sample_1.mp3", "./sample_2.mp3"],
)

# Use the cloned voice for TTS
audio = elevenlabs.text_to_speech.convert(
    text="Hello, this is my cloned voice speaking.",
    voice_id=voice.voice_id,
    model_id="eleven_flash_v2_5",
)

play(audio)
```

### 3.5 Model IDs

| Model ID                   | Name                  | Latency    | Languages | Best For                              |
| -------------------------- | --------------------- | ---------- | --------- | ------------------------------------- |
| `eleven_flash_v2_5`        | Flash v2.5            | ~75ms      | 32        | Real-time agents, low-latency apps    |
| `eleven_turbo_v2_5`        | Turbo v2.5            | ~250-300ms | 32        | Quality/speed balance                 |
| `eleven_multilingual_v2`   | Multilingual v2       | Moderate   | 29        | Highest quality, audiobooks, pro use  |
| `eleven_v3`                | V3                    | Moderate   | 70+       | Human-like, expressive generation     |

### 3.6 Output Format Options

| Format              | Description                          | Requirements         |
| ------------------- | ------------------------------------ | -------------------- |
| `mp3_22050_32`      | MP3 22.05kHz, 32kbps                 | Free tier            |
| `mp3_44100_32`      | MP3 44.1kHz, 32kbps                  | Free tier            |
| `mp3_44100_64`      | MP3 44.1kHz, 64kbps                  | Free tier            |
| `mp3_44100_96`      | MP3 44.1kHz, 96kbps                  | Free tier            |
| `mp3_44100_128`     | MP3 44.1kHz, 128kbps (default)       | Free tier            |
| `mp3_44100_192`     | MP3 44.1kHz, 192kbps                 | Creator tier+        |
| `pcm_16000`         | PCM 16kHz, 16-bit                    | Free tier            |
| `pcm_22050`         | PCM 22.05kHz, 16-bit                 | Free tier            |
| `pcm_24000`         | PCM 24kHz, 16-bit                    | Free tier            |
| `pcm_44100`         | PCM 44.1kHz, 16-bit                  | Pro tier+            |
| `ulaw_8000`         | mu-law 8kHz                          | Free tier            |

### 3.7 Voice Settings

When using the API directly (not the SDK helper), voice settings can be configured:

- **stability** (0.0-1.0): Voice consistency. Higher = more consistent, lower = more expressive.
- **similarity_boost** (0.0-1.0): How closely to match the original voice.
- **style** (0.0-1.0): Expressive style variation.
- **use_speaker_boost** (bool): Enhancement toggle for clarity.
- **speed** (0.7-1.2): Speech rate adjustment.

### Key Notes - ElevenLabs

- Flash v2.5 (`eleven_flash_v2_5`) is the fastest model at ~75ms latency and 50% lower cost per character
- Default output format is `mp3_44100_128` if not specified
- For real-time applications, use `pcm_16000` or `pcm_24000` to avoid MP3 decoding overhead
- The `stream()` helper uses chunked transfer encoding over HTTP
- Voice cloning requires at least one audio sample; more samples improve quality
- The SDK auto-reads the `ELEVENLABS_API_KEY` environment variable if no key is passed

---

## 4. Meeting BaaS API

**Official docs:** [Bots API](https://www.meetingbaas.com/en/api/bots-api) | [Speaking Bots API](https://www.meetingbaas.com/en/api/speaking-bots-api) | [Speaking Bots Docs](https://docs.meetingbaas.com/speaking-bots)

### 4.1 Creating/Joining a Bot to Google Meet (v2 API)

> **API keys:** Obtain your API key from [dashboard.meetingbaas.com](https://dashboard.meetingbaas.com) (v2 dashboard).

```python
import requests

url = "https://api.meetingbaas.com/v2/bots"
headers = {
    "Content-Type": "application/json",
    "x-meeting-baas-api-key": "YOUR-API-KEY",
}
config = {
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "bot_name": "AI Assistant",
    "bot_image": "https://example.com/bot-avatar.jpg",
    "streaming_enabled": True,
    "streaming_config": {
        "output_url": "wss://your-server.example.com/ws",
        "input_url": "wss://your-server.example.com/ws",
        "audio_frequency": 16000,
    },
}
response = requests.post(url, json=config, headers=headers)
print(response.json())
# Response: {"success": true, "data": {"bot_id": "..."}}
```

**Removing a bot from a meeting (v2 API):**

```python
bot_id = "your-bot-id"
response = requests.post(
    f"https://api.meetingbaas.com/v2/bots/{bot_id}/leave",
    headers={
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": "YOUR-API-KEY",
    },
)
print(response.json())
```

### 4.2 Speaking Bot (v2 API with Streaming)

Our implementation uses the v2 streaming API to create a speaking bot. Instead of using
the hosted Pipecat-based speaking bot endpoint, we deploy a bot with `streaming_enabled`
and handle audio I/O ourselves via WebSocket:

```python
import requests


def deploy_speaking_bot(meeting_url: str, ws_url: str):
    """Deploy a speaking bot using v2 streaming API.

    Args:
        meeting_url: The meeting URL to join.
        ws_url: Your WebSocket server URL (e.g. ngrok wss:// URL).
    """
    url = "https://api.meetingbaas.com/v2/bots"
    headers = {
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": "YOUR-API-KEY",
    }

    payload = {
        "meeting_url": meeting_url,
        "bot_name": "Meeting Assistant",
        "bot_image": "https://example.com/bot-avatar.png",
        "streaming_enabled": True,
        "streaming_config": {
            "output_url": ws_url,  # Meeting BaaS sends audio here
            "input_url": ws_url,   # Meeting BaaS reads audio from here
            "audio_frequency": 16000,
        },
    }

    response = requests.post(url, headers=headers, json=payload)
    return response.json()
    # Response: {"success": true, "data": {"bot_id": "..."}}
```

### 4.3 WebSocket Streaming Protocol (v2 `streaming_config`)

With the v2 API, Meeting BaaS connects **to your WebSocket server** and streams data
in a simple binary + JSON format (not the `audio_separate_raw` JSON envelope):

- **JSON text messages:** Speaker metadata arrays, e.g. `[{"name": "John", "id": 1, "timestamp": 12345, "isSpeaking": true}]`
- **Binary messages:** Raw PCM audio data (16kHz mono 16-bit signed little-endian)

**WebSocket receiver for v2 streaming:**

```python
import asyncio
import json
import websockets


async def handle_meeting_audio(websocket, path=""):
    """Handle incoming WebSocket connection from Meeting BaaS v2.

    Meeting BaaS sends:
    - JSON strings: speaker metadata [{name, id, timestamp, isSpeaking}]
    - Binary data: raw PCM audio (16kHz mono 16-bit)
    """
    current_speakers = []

    async for message in websocket:
        if isinstance(message, str):
            # JSON: speaker metadata
            try:
                current_speakers = json.loads(message)
                active = next(
                    (s for s in current_speakers if s.get("isSpeaking")), None
                )
                if active:
                    print(f"Speaker: {active['name']}")
            except json.JSONDecodeError:
                pass
        else:
            # Binary: PCM audio data (16kHz mono S16LE)
            active = next(
                (s for s in current_speakers if s.get("isSpeaking")), None
            )
            speaker_name = active["name"] if active else "unknown"
            print(f"Audio: {len(message)} bytes from {speaker_name}")

            # Process audio (feed to STT, etc.)


async def main():
    async with websockets.serve(handle_meeting_audio, "0.0.0.0", 8765):
        print("WebSocket server listening on 0.0.0.0:8765")
        await asyncio.Future()  # run forever


asyncio.run(main())
```

To send audio **back** to the meeting, write binary PCM data to the same WebSocket connection.

---

#### v1 Alternative: `audio_separate_raw` Protocol (Reference)

> **Note:** This section documents the v1 `audio_separate_raw` approach. Our implementation
> uses the v2 `streaming_config` approach described above instead. This is kept here as a
> reference for the v1 API.

**Bot creation with v1 per-participant audio streaming:**

```python
import requests

url = "https://api.meetingbaas.com/bots"  # v1 endpoint
headers = {
    "Content-Type": "application/json",
    "x-meeting-baas-api-key": "YOUR-API-KEY",
}
config = {
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "bot_name": "Audio Bot",
    "recording_config": {
        "audio_separate_raw": {},
        "realtime_endpoints": [
            {
                "type": "websocket",
                "url": "wss://your-server.com/ws/audio",
                "events": ["audio_separate_raw.data"],
            }
        ],
    },
}
response = requests.post(url, json=config, headers=headers)
```

**v1 WebSocket message format received:**

```json
{
  "event": "audio_separate_raw.data",
  "data": {
    "data": {
      "buffer": "<base64-encoded raw audio: 16kHz mono S16LE>",
      "timestamp": {
        "relative": 12.345,
        "absolute": "2025-01-15T10:30:00Z"
      },
      "participant": {
        "id": 1,
        "name": "John Doe",
        "is_host": true,
        "platform": "web",
        "extra_data": {},
        "email": "john@example.com"
      }
    },
    "realtime_endpoint": { "id": "...", "metadata": {} },
    "bot": { "id": "...", "metadata": {} }
  }
}
```

**v1 WebSocket receiver example:**

```python
import asyncio
import json
import base64
import websockets


async def audio_receiver(websocket):
    async for message in websocket:
        data = json.loads(message)

        if data["event"] == "audio_separate_raw.data":
            audio_data = data["data"]["data"]
            participant = audio_data["participant"]
            raw_audio = base64.b64decode(audio_data["buffer"])

            print(
                f"Received {len(raw_audio)} bytes from "
                f"{participant['name']} (id={participant['id']})"
            )

            # raw_audio is 16kHz mono S16LE PCM
            # Process it (e.g., feed to STT, save to file, etc.)


async def main():
    async with websockets.serve(audio_receiver, "0.0.0.0", 8765):
        await asyncio.Future()  # run forever


asyncio.run(main())
```

### 4.4 Sending Audio Back to the Meeting

**v2 approach (our implementation):** With `streaming_config`, audio is sent directly
as binary PCM data over the same WebSocket connection that receives audio:

```python
# Send raw PCM audio bytes directly over the WebSocket
await websocket.send(pcm_audio_bytes)  # 16kHz mono S16LE PCM
```

This is the approach our `MeetingBaaSTransport.send_audio()` method uses.

---

#### v1 Approach: `output_audio` REST Endpoint (Reference)

> **Note:** This section documents the v1 REST-based approach for sending audio.
> Our implementation sends audio directly via WebSocket instead.

```python
import requests
import base64

bot_id = "your-bot-id"

# Audio must be MP3 encoded as base64
with open("greeting.mp3", "rb") as f:
    b64_audio = base64.b64encode(f.read()).decode("utf-8")

# Option 1: On-demand audio output
response = requests.post(
    f"https://api.meetingbaas.com/api/v1/bot/{bot_id}/output_audio/",
    headers={
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": "YOUR-API-KEY",
    },
    json={
        "kind": "mp3",
        "b64_data": b64_audio,
    },
)

# Option 2: Configure automatic audio on bot creation
config = {
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "bot_name": "Speaking Bot",
    "automatic_audio_output": {
        "in_call_recording": {
            "data": {
                "kind": "mp3",
                "b64_data": b64_audio,
            },
            "replay_on_participant_join": {
                "debounce_mode": "trailing",  # or "leading"
                "debounce_interval": 10,
                "disable_after": 60,
            },
        },
    },
}
```

### 4.5 Bot Customization Options

| Parameter             | Type    | Description                                     |
| --------------------- | ------- | ----------------------------------------------- |
| `bot_name`            | string  | Display name shown to meeting participants       |
| `bot_image`           | string  | URL to avatar image                              |
| `entry_message`       | string  | Text announced when bot joins                    |
| `recording_mode`      | string  | `speaker_view`, `gallery_view`, or `audio-only`  |
| `reserved`            | boolean | Schedule vs. immediate deployment                |
| `personas`            | array   | Personality definitions (speaking bots)          |
| `enable_tools`        | boolean | Enable bot tool capabilities (speaking bots)     |
| `prompt`              | string  | Custom system prompt (speaking bots)             |
| `extra`               | object  | Additional context data (speaking bots)          |

### 4.6 Webhook Events

| Event                    | Description                                         |
| ------------------------ | --------------------------------------------------- |
| `complete`               | Recording finished, transcript and MP4 ready        |
| `failed`                 | Bot could not join/record, includes error details    |
| `transcription_complete` | Transcription processing finished                   |
| `bot.status_change`      | Status updates: joining, in_call, recording, ended   |

### Key Notes - Meeting BaaS

- **v2 API:** Use `POST /v2/bots` to create bots and `POST /v2/bots/{id}/leave` to remove them
- **v2 Streaming:** Set `streaming_enabled: true` with a `streaming_config` containing `output_url`, `input_url`, and `audio_frequency`
- **v2 WebSocket protocol:** Meeting BaaS connects to your WS server and sends JSON (speaker metadata) + binary (PCM audio)
- **v2 Audio output:** Send raw PCM bytes directly over the WebSocket (no MP3 encoding needed)
- API keys are obtained from [dashboard.meetingbaas.com](https://dashboard.meetingbaas.com)
- Audio format: mono 16-bit signed little-endian PCM at 16kHz
- WebSocket endpoint URLs must use `ws://` or `wss://` protocol, not HTTP
- Per-participant audio is supported on Google Meet (16 streams), Zoom (16 streams), Teams (9 streams)
- Muted participants produce no audio data; silent unmuted participants generate empty packets
- Screenshare audio is not captured in real-time streams (only in final recording)
- v1 `output_audio` REST endpoint requires MP3 base64 encoding; v2 streaming uses raw PCM over WebSocket

---

## 5. Pipecat Framework (`pipecat-ai`)

**Install:**

```bash
uv add "pipecat-ai[mistral,elevenlabs]"
```

**Official docs:** [Introduction](https://docs.pipecat.ai/getting-started/introduction) | [Quickstart](https://docs.pipecat.ai/getting-started/quickstart) | [GitHub](https://github.com/pipecat-ai/pipecat)

### 5.1 Basic Pipeline Creation

```python
import os
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.services.deepgram import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.processors.aggregators.llm_context import (
    LLMContext,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame

# Create AI services
stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
tts = CartesiaTTSService(
    api_key=os.getenv("CARTESIA_API_KEY"),
    voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",
)
llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

# Set up conversation context
messages = [
    {
        "role": "system",
        "content": "You are a friendly AI assistant. Respond naturally and keep your answers conversational.",
    },
]

context = LLMContext(messages)
user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(),
    ),
)

# Create the pipeline
pipeline = Pipeline(
    [
        transport.input(),       # Receive audio from client
        stt,                     # Speech-to-text
        user_aggregator,         # Add user message to context
        llm,                     # Language model
        tts,                     # Text-to-speech
        transport.output(),      # Send audio back to client
        assistant_aggregator,    # Add bot response to context
    ]
)

# Create and run the task
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

### 5.2 Mistral LLM Service

```python
from pipecat.services.mistral.llm import MistralLLMService

# MistralLLMService extends OpenAILLMService using Mistral's
# OpenAI-compatible endpoint
llm = MistralLLMService(
    api_key=os.getenv("MISTRAL_API_KEY"),
    model="mistral-small-latest",  # default
    # base_url="https://api.mistral.ai/v1",  # default
)
```

**Available Mistral models for Pipecat:**
- `mistral-small-latest`
- `mistral-medium-latest`
- `mistral-large-latest`

**Important:** MistralLLMService applies several Mistral-specific fixups:
- Ensures tool responses precede assistant messages
- Repositions system messages to conversation start
- Handles function call detection differences from OpenAI
- Maps `random_seed` parameter (Mistral's equivalent of OpenAI's `seed`)

### 5.3 ElevenLabs TTS Service

```python
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

tts = ElevenLabsTTSService(
    api_key=os.getenv("ELEVENLABS_API_KEY"),
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    model="eleven_flash_v2_5",       # default: "eleven_turbo_v2_5"
    sample_rate=16000,                # optional
    # params=ElevenLabsTTSService.InputParams(
    #     stability=0.5,
    #     similarity_boost=0.75,
    #     style=0.0,
    #     use_speaker_boost=True,
    #     speed=1.0,
    #     enable_ssml_parsing=False,
    # ),
)
```

**Supported PCM output formats (auto-selected by sample_rate):**
- `pcm_8000`, `pcm_16000`, `pcm_22050`, `pcm_24000`, `pcm_44100`

**Multilingual models** (support language codes):
- `eleven_flash_v2_5`, `eleven_turbo_v2_5`

### 5.4 Custom Processor / Service Implementation

```python
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TextFrame, AudioRawFrame


class CustomProcessor(FrameProcessor):
    """Example custom processor that transforms text frames."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, TextFrame):
            # Transform the text
            modified_text = frame.text.upper()
            await self.push_frame(TextFrame(text=modified_text), direction)
        else:
            # Pass through all other frames unmodified
            await self.push_frame(frame, direction)


class AudioLogger(FrameProcessor):
    """Example processor that logs audio frame metadata."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, AudioRawFrame):
            print(
                f"Audio frame: {len(frame.audio)} bytes, "
                f"sample_rate={frame.sample_rate}"
            )
        # Always pass the frame through
        await self.push_frame(frame, direction)
```

**Using custom processors in a pipeline:**

```python
pipeline = Pipeline(
    [
        transport.input(),
        stt,
        user_aggregator,
        CustomProcessor(),       # Insert your custom processor
        llm,
        tts,
        AudioLogger(),           # Log audio before output
        transport.output(),
        assistant_aggregator,
    ]
)
```

### 5.5 Frame Types and Pipeline Flow

**Frame categories:**

| Category       | Examples                                            | Priority | Description                     |
| -------------- | --------------------------------------------------- | -------- | ------------------------------- |
| **SystemFrame**| `StartFrame`, `EndFrame`, `CancelFrame`             | High     | Lifecycle control signals       |
| **DataFrame**  | `AudioRawFrame`, `TextFrame`, `TranscriptionFrame`  | Normal   | Audio, text, and media data     |
| **ControlFrame**| `LLMContextFrame`, `LLMRunFrame`                   | Normal   | Configuration and triggers      |

**Frame flow direction:**
- **DOWNSTREAM**: Source -> Sink (normal processing: audio in -> STT -> LLM -> TTS -> audio out)
- **UPSTREAM**: Sink -> Source (feedback, events, control signals)

**Typical pipeline flow:**

```
Transport Input -> STT -> User Aggregator -> LLM -> TTS -> Transport Output
                                                              |
                                                    Assistant Aggregator
```

### 5.6 Transport Configuration

```python
from pipecat.transports.base_transport import TransportParams

params = TransportParams(
    audio_in_enabled=True,
    audio_out_enabled=True,
    audio_in_sample_rate=16000,
    audio_out_sample_rate=24000,
)
```

### 5.7 Event Handlers

```python
@transport.event_handler("on_client_connected")
async def on_client_connected(transport, client):
    print("Client connected")
    messages.append({
        "role": "system",
        "content": "Say hello and briefly introduce yourself.",
    })
    await task.queue_frames([LLMRunFrame()])


@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    print("Client disconnected")
    await task.cancel()
```

### Key Notes - Pipecat

- Pipecat uses a pipeline-of-processors architecture where data flows as immutable Frame objects
- Each FrameProcessor runs its own async task, guaranteeing frame ordering
- System frames are processed with higher priority than data frames
- The framework supports 60+ AI service integrations through a uniform adapter pattern
- MistralLLMService wraps Mistral's API using the OpenAI-compatible interface
- ElevenLabsTTSService uses WebSocket streaming for real-time audio with word-level timestamps
- Processors can push frames both downstream and upstream
- PipelineTask manages lifecycle; PipelineRunner executes the task
- Install only the extras you need: `uv add "pipecat-ai[mistral,elevenlabs]"`
