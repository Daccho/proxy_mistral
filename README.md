# Proxy Mistral - Meeting Proxy Agent

An AI agent that attends low-priority meetings on your behalf, equipped with your knowledge, personality, and cloned voice.

## Prerequisites

- Python 3.11+ (< 3.14)
- [uv](https://docs.astral.sh/uv/) (package manager)
- [ngrok](https://ngrok.com/) account + authtoken configured (`ngrok config add-authtoken <token>`)
- API keys:
  - [Meeting BaaS](https://meetingbaas.com/) (v2 API key)
  - [Mistral AI](https://console.mistral.ai/)
  - [ElevenLabs](https://elevenlabs.io/) (API key + voice ID)

## Setup

1. Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

2. Install dependencies:

```bash
make install
```

3. Verify the setup:

```bash
make test-setup
```

## Usage

Join a meeting:

```bash
uv run python -m src.main join "https://meet.google.com/abc-def-ghi"
uv run python -m src.main join "https://meet.google.com/abc-def-ghi" --bot-name "YourName"
```

Leave a meeting:

```bash
uv run python -m src.main leave
```

## Architecture

```
Google Meet
    |
Meeting BaaS (v2 API)
    |  connects TO our server
    v
ngrok HTTP tunnel (wss://xxx.ngrok.io)
    |
    v
Local WS server (:8765) + Pipecat Pipeline
    |
    v
┌────────────────────────────────────────────────────────┐
│  MeetingBaaSInputProcessor  (WS audio -> frames)       │
│       |                                                │
│  VoxtralSTTProcessor        (STT stub, not connected)  │
│       |                                                │
│  MistralAgentBrain          (response judgment + gen)   │
│       |                                                │
│  ElevenLabsTTSService       (pipecat built-in, Flash)   │
│       |                                                │
│  MeetingBaaSOutputProcessor (frames -> WS audio out)   │
└────────────────────────────────────────────────────────┘
```

When `join` is called, the server:
1. Starts a WebSocket server on port 8765
2. Opens an ngrok HTTP tunnel to expose it
3. Calls Meeting BaaS `POST /v2/bots` with `streaming_config.output_url` and `input_url` set to the ngrok wss:// URL
4. Meeting BaaS joins Google Meet and connects back to our WS server
5. Audio flows through the Pipecat pipeline: input -> STT -> Agent -> TTS -> output

## Components

| File | Description |
|---|---|
| `src/main.py` | click CLI entry point (`join`, `leave`, `status`) |
| `src/config/settings.py` | pydantic-settings v2 config with env var aliases |
| `src/agent/brain.py` | `MistralAgentBrain` -- response decision and generation via Mistral chat completions |
| `src/meeting/transports/base.py` | `BaseMeetingTransport` abstract base class |
| `src/meeting/transports/meetingbaas.py` | `MeetingBaaSTransport` -- v2 API, WS server, ngrok, speaker tracking |
| `src/pipeline/meeting_pipeline.py` | `MeetingPipeline`, `MeetingBaaSInputProcessor`, `MeetingBaaSOutputProcessor` |
| `src/pipeline/meeting_processors/voxtral_stt.py` | `VoxtralSTTProcessor` -- stub, `_transcribe()` returns None |
| `config/personas/default.yaml` | Persona configuration (name, style, rules, opinions, meeting types) |
| `config/settings.yaml` | Default application settings |
| `scripts/test_setup.py` | Verify config loading and transport initialization |
| `tests/test_basic.py` | Basic unit tests |

## Configuration

Application settings are loaded from environment variables (via `.env`) with `pydantic-settings` v2 `Field(alias=...)` pattern:

| Env Var | Description |
|---|---|
| `MEETING_BAAS_API_KEY` | Meeting BaaS API key |
| `MEETING_BAAS_BASE_URL` | Meeting BaaS base URL (default: `https://api.meetingbaas.com`) |
| `MISTRAL_API_KEY` | Mistral AI API key |
| `ELEVENLABS_API_KEY` | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice ID (use a cloned voice for impersonation) |

Persona behavior is configured in `config/personas/default.yaml`. See [SPEC.md](SPEC.md) for the full schema.

## Development

```bash
make test        # run tests
make lint        # run ruff linter
make format      # format with black + isort
make test-setup  # verify config + transport
```

## Current Status

The core pipeline skeleton is implemented and wired together. The following are working:

- Meeting BaaS v2 integration (bot creation, WS server, ngrok tunnel, bot removal)
- Pipecat pipeline with custom FrameProcessors for input/output
- MistralAgentBrain with should_respond heuristic + Mistral-based judgment
- ElevenLabs TTS via pipecat's built-in `ElevenLabsTTSService`
- click CLI, pydantic-settings config, persona YAML

Not yet functional:

- VoxtralSTTProcessor (`_transcribe()` is a stub returning None -- needs Voxtral Realtime API connection)
- No database/storage layer
- No REST API
- No post-meeting summaries
- No voice clone setup script

See [SPEC.md](SPEC.md) for the full roadmap and implementation status table.

## License

MIT
