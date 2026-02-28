# Meeting Proxy Agent

An AI agent that attends low-priority meetings on the user's behalf, equipped with their knowledge, personality, and cloned voice. Maximizes use of Mistral AI and ElevenLabs.

## Design Decisions

- **Platform**: Google Meet (MVP target)
- **Language**: Bilingual (English primary, Japanese supported)
- **Agent behavior**: Passive (speaks only when addressed by name; default is to listen)
- **Identity**: Impersonates the user (bot_name = user's name, cloned voice). Honestly admits to being AI if directly asked.
- **When uncertain**: Gives best-effort answer based on available context, flags uncertain parts with "I'll confirm the details"
- **Meeting types**: Switchable via persona YAML presets (standup / all-hands / 1-on-1 / default)
- **Standup progress**: Inferred from previous meeting summaries and action items

## Architecture

### Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│  Google Meet                                            │
└──────────┬──────────────────────────────────▲────────────┘
           │ audio (participants)             │ audio (agent)
           ▼                                  │
┌──────────────────────────────────────────────────────────┐
│  Meeting BaaS (cloud service, v2 API)                    │
│  - POST /v2/bots → create bot, join Google Meet          │
│  - POST /v2/bots/{id}/leave → remove bot                 │
│  - Connects TO our WebSocket server for audio streaming  │
└──────────┬──────────────────────────────────▲────────────┘
           │ WebSocket (PCM audio + JSON)     │ WebSocket (PCM audio)
           ▼                                  │
┌──────────────────────────────────────────────────────────┐
│  ngrok HTTP tunnel (free tier)                           │
│  - Exposes local WS server on port 8765                  │
│  - https://xxx.ngrok.io → wss://xxx.ngrok.io             │
└──────────┬──────────────────────────────────▲────────────┘
           │                                  │
           ▼                                  │
┌──────────────────────────────────────────────────────────┐
│  Our Server (Pipecat Pipeline + WS server on :8765)      │
│                                                          │
│  1. MeetingBaaSInputProcessor (FrameProcessor)           │
│     └→ Receive audio from WS, push InputAudioRawFrame    │
│                                                          │
│  2. VoxtralSTTProcessor (FrameProcessor) [STUB]          │
│     └→ Audio → TranscriptionFrame (not yet connected)    │
│                                                          │
│  3. MistralAgentBrain (FrameProcessor)                   │
│     └→ should_respond() judgment (heuristic + Mistral)   │
│     └→ Generate response text → TextFrame                │
│                                                          │
│  4. ElevenLabsTTSService (pipecat built-in)              │
│     └→ TextFrame → TTSAudioRawFrame (Flash v2.5)         │
│                                                          │
│  5. MeetingBaaSOutputProcessor (FrameProcessor)          │
│     └→ Send TTSAudioRawFrame back via WS → meeting       │
└──────────────────────────────────────────────────────────┘
```

### WS Server Architecture

We run a WebSocket server locally on port 8765, then expose it via pyngrok HTTP tunnel. When creating a bot, we pass our ngrok URL as both `output_url` and `input_url` in the `streaming_config`. Meeting BaaS then connects **to our server** (we do NOT connect to theirs).

**Bot creation request** (POST /v2/bots):
```json
{
  "meeting_url": "https://meet.google.com/abc-def-ghi",
  "bot_name": "ProxyBot",
  "streaming_enabled": true,
  "streaming_config": {
    "output_url": "wss://xxx.ngrok.io",
    "input_url": "wss://xxx.ngrok.io",
    "audio_frequency": 16000
  }
}
```

**Response format**:
```json
{
  "success": true,
  "data": {
    "bot_id": "abc123..."
  }
}
```

**Bot removal** (POST /v2/bots/{id}/leave):
- Header: `x-meeting-baas-api-key`

### Meeting BaaS WebSocket Messages

Meeting BaaS sends two types of messages over the WebSocket:
- **JSON strings**: Speaker metadata `[{name, id, timestamp, isSpeaking}]`
- **Binary data**: Raw PCM audio (16kHz mono 16-bit signed little-endian)

### Mistral Agent Flow

```
TranscriptionFrame received → should_respond() judgment
  ├→ NO: Consumed (not pushed downstream), continue listening
  └→ YES:
      └→ _generate_response() via Mistral chat completions
      └→ Push TextFrame downstream → TTS → audio out
```

The `should_respond()` method uses a two-tier approach:
1. **Heuristic check**: Name mention or direct question detection
2. **Mistral fallback**: Ask Mistral to decide with a lightweight prompt (max_tokens=10)

## Tech Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ (<3.14) | Rich SDK support for both Mistral and ElevenLabs |
| Package manager | uv | Fast, lockfile-based dependency management |
| Pipeline | Pipecat (`pipecat-ai[mistral,elevenlabs]>=0.0.100`) | Real-time voice pipeline framework with built-in Mistral/ElevenLabs support |
| LLM/Agent | Mistral Chat Completions (mistral-medium-2505) | 256K context, used for response judgment and generation |
| STT (real-time) | Voxtral Realtime (stub) | Sub-200ms latency target. Custom FrameProcessor wrapping Mistral SDK |
| TTS | ElevenLabs Flash v2.5 (`ElevenLabsTTSService` from pipecat) | 75ms latency, Voice Cloning support. Uses pipecat's built-in service |
| Meeting join | Meeting BaaS v2 API ($0.69/h, 4h free tier) | Google Meet bidirectional audio, per-participant audio separation |
| WS server | websockets (Python) | Local server on :8765, Meeting BaaS connects to us |
| Tunnel | pyngrok (ngrok HTTP tunnel) | Exposes local WS server to internet for Meeting BaaS |
| Config | pydantic-settings v2 (`Field(alias=...)`) + dotenv | Type-safe configuration, env var aliasing |
| CLI | click | Simple command group (`join`, `leave`, `status`) |
| HTTP client | requests (sync, in `asyncio.to_thread` where needed) | Meeting BaaS API calls |

## Core Features

### 1. User Context Management

**3-layer structure**:

**Layer 1: Business Documents (Mistral Document Library)**
- Upload PDFs, docs to Mistral Cloud
- Agent uses `document_library` tool for natural RAG search during meetings
- Managed via `scripts/upload_context.py`

**Layer 2: Persona Settings (YAML -> System Prompt)**

```yaml
# config/personas/default.yaml
name: "daccho"
communication_style:
  tone: "professional but friendly"
  verbosity: "concise"
  formality: "semi-formal"
opinions:
  - topic: "microservices vs monolith"
    stance: "prefer modular monolith for teams under 20"
  - topic: "meeting frequency"
    stance: "prefer async communication, meetings should have clear agenda"
rules:
  - "Never commit to deadlines without saying 'I'll confirm the timeline'"
  - "Always note action items assigned to me"
  - "If unsure about specifics, give best estimate and say 'I'll confirm the details'"
defer_topics:
  - "budget approvals"
  - "hiring decisions"
  - "architectural changes to core systems"
meeting_types:
  standup:
    proactivity: "high"
    prepared_update: true
  all_hands:
    proactivity: "low"
    respond_only_when: "directly_addressed"
  one_on_one:
    proactivity: "medium"
  default:
    proactivity: "low"
    respond_only_when: "directly_addressed"
```

**Layer 3: Cross-meeting Context Carryover**
- Inject past meeting summaries (same participants/project) into Mistral Agent context
- Enables responses informed by "what was decided last time"
- Search related meetings from DB -> add summaries to system prompt

### 2. Real-time Meeting Response

**Passive mode (MVP)**:
- Respond only when addressed by name
- Respond only to direct questions
- Otherwise, listen silently and record transcript

**Mistral Agent Function Calling Tools**:

| Tool | Purpose |
|---|---|
| `should_respond` | Decide whether to speak (name detection, direct question detection) |
| `lookup_document` | Search user's documents for relevant info |
| `note_action_item` | Record action items |
| `note_decision` | Record decisions |
| `defer_to_user` | Reply "I'll check with [user]" and flag for follow-up |

### 3. Post-meeting Summary

A separate Mistral Agent processes the full transcript to produce:
- Executive summary
- Action items list (with assignees and deadlines)
- Decisions list
- Deferred items (things the agent used `defer_to_user` for)
- Questions the agent couldn't answer

### 4. Voice Cloning

- ElevenLabs Instant Voice Cloning from 1-5 min audio sample
- Interactive setup via `scripts/setup_voice.py`
- Cloned voice_id saved to settings

## Project Structure (Actual)

```
proxy_mistral/
├── pyproject.toml                           # uv project config, pipecat-ai[mistral,elevenlabs]>=0.0.100
├── uv.lock                                 # lockfile
├── .env.example                             # env var template
├── .env                                     # actual keys (gitignored)
├── Makefile                                 # install, test, lint, format, run, test-setup
├── config/
│   ├── settings.yaml                        # default settings (YAML)
│   └── personas/
│       └── default.yaml                     # persona config
├── src/
│   ├── __init__.py
│   ├── main.py                              # click CLI: join, leave, status commands
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                      # pydantic-settings v2 (Field alias for env vars)
│   ├── agent/
│   │   ├── __init__.py
│   │   └── brain.py                         # MistralAgentBrain FrameProcessor
│   ├── meeting/
│   │   └── transports/
│   │       ├── __init__.py
│   │       ├── base.py                      # BaseMeetingTransport ABC
│   │       └── meetingbaas.py               # MeetingBaaSTransport (v2 API, WS server, ngrok)
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── meeting_pipeline.py              # MeetingPipeline, MeetingBaaSInputProcessor, MeetingBaaSOutputProcessor
│   │   └── meeting_processors/
│   │       ├── __init__.py
│   │       └── voxtral_stt.py               # VoxtralSTTProcessor (stub — _transcribe returns None)
│   └── proxy_mistral/
│       └── __init__.py
├── scripts/
│   └── test_setup.py                        # verify config + transport init
├── tests/
│   └── test_basic.py                        # config, transport, persona tests
└── docs/                                    # (exists but empty/not used)
```

**NOT implemented** (listed in original spec but no files exist):
- `src/agent/context_manager.py`, `tools.py`, `prompts.py`, `summarizer.py`
- `src/voice/` (entire directory — no custom TTS/STT/cloner modules)
- `src/storage/` (no database, no models)
- `src/api/` (no FastAPI app, no REST routes)
- `src/meeting/manager.py`
- `scripts/setup_voice.py`, `upload_context.py`, `test_latency.py`, `simulate_meeting.py`
- `tests/conftest.py`, `tests/unit/`, `tests/integration/`

## CLI Commands

```bash
# Join a meeting
uv run python -m src.main join "https://meet.google.com/abc-def-ghi"
uv run python -m src.main join "https://meet.google.com/abc-def-ghi" --bot-name "MyName"

# Leave a meeting
uv run python -m src.main leave

# Check status (defined but prints "not yet implemented")
uv run python -m src.main status
```

Note: The CLI uses `click` groups, invoked as `python -m src.main`, not as a `proxy` command.

## Error Handling

| Failure | Behavior |
|---|---|
| STT down | Log. Continue listening (no transcription but connection maintained) |
| LLM down | Log. STT continues accumulating transcript. Cannot respond |
| TTS down | Log. Save LLM response text to log. Cannot speak |
| WebSocket disconnect | Auto-reconnect 3 attempts. On failure, treat as meeting end -> generate summary |
| Full outage | Log everything. Attempt summary generation from collected transcript |

Failure info recorded in DB + logs. Post-meeting summary notes "partial outage occurred during some segments".

## Context / Memory Management

**256K token budget**:
- System Prompt (persona + rules): ~2K tokens (resident)
- Meeting context (agenda + past meeting summaries): ~3-5K tokens (resident)
- Real-time transcript: ~1K tokens/min (accumulating)
- 1-hour meeting ~ 60-70K tokens -> well within 256K

**Long meeting strategy** (2+ hours):
- Auto-compress at 70% context usage
- Summarize older utterances -> keep last 30 min as raw transcript
- Use separate Mistral API call for summarization

**Cost estimate** (per 1-hour meeting):
- Meeting BaaS: $0.69 + Voxtral STT: $0.36 + Mistral Agent: ~$0.03 + ElevenLabs TTS: ~$0.05
- **Total: ~$1.10/meeting** (+ ElevenLabs plan $5-22/month)

## Latency Budget

- Voxtral Realtime STT: <200ms
- Mistral Agent response: ~500-1000ms
- ElevenLabs TTS (Flash v2.5): ~75ms
- **Total: ~0.8-1.3s** (fits within natural conversational pause)

## Implementation Status

### Phase 1a: MVP Core

| # | Task | Status |
|---|---|---|
| 1 | Meeting BaaS v2 API integration (POST /v2/bots, WS server, ngrok tunnel) | Done |
| 2 | Pipecat pipeline (MeetingBaaSInput -> STT -> Brain -> TTS -> MeetingBaaSOutput) | Done |
| 3 | MistralAgentBrain FrameProcessor (should_respond + generate_response) | Done |
| 4 | ElevenLabs TTS via pipecat built-in `ElevenLabsTTSService` | Done |
| 5 | VoxtralSTTProcessor (stub — _transcribe returns None, not connected to API) | Stub |
| 6 | Persona YAML config (`config/personas/default.yaml`) | Done |
| 7 | pydantic-settings v2 config with env var aliases | Done |
| 8 | click CLI (`join`, `leave`, `status`) | Done |
| 9 | Makefile (install, test, lint, format, run, test-setup) | Done |
| 10 | Basic tests (`tests/test_basic.py`) | Done |
| 11 | Setup verification script (`scripts/test_setup.py`) | Done |
| 12 | Post-meeting summary generation | Not started |
| 13 | Mistral Agents API (persistent agent with Function Calling tools) | Not started |
| 14 | Document Library / RAG integration | Not started |
| 15 | Voice Clone setup script | Not started |
| 16 | SQLite transcript/summary storage | Not started |
| 17 | structlog logging | Not started |
| 18 | FastAPI REST API | Not started |
| 19 | Unit + integration test suite | Not started |

### Phase 1b: MVP Extended
- Google Calendar API integration
- Chat reading, screen share OCR
- Bilingual support (Japanese + English)
- REST API + OAuth2
- Cross-meeting context carryover
- Meeting-type persona switching

### Phase 2: Auto-join + Cloud Deploy
- Meeting priority auto-detection
- Auto-join low-priority meetings
- Post-meeting summary notification (email/Slack)
- Cloud deploy (Railway / Fly.io / DigitalOcean)

### Phase 3+ (Future)
- Multi-meeting simultaneous attendance
- Web UI dashboard
- Real-time user notifications during meetings
- Self-hosted browser bot (remove Meeting BaaS dependency)

## Validation

1. `scripts/test_setup.py` -- verify config and transport initialization
2. `pytest tests/` -- basic unit tests
3. Real Google Meet E2E test (manual)
4. `scripts/simulate_meeting.py` -- simulated meeting test (not yet implemented)
5. `scripts/test_latency.py` -- measure STT -> LLM -> TTS latency (not yet implemented)
