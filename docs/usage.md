# Development & Verification Guide

## Prerequisites

### Required Knowledge
- **Pipecat**: Frame-based real-time voice pipeline framework. Understand processors, pipelines, and frame types. See [Pipecat docs](https://docs.pipecat.ai/).
- **Mistral Agents API**: Agent creation, conversations, function calling, Document Library. See [Mistral docs](https://docs.mistral.ai/agents/).
- **ElevenLabs SDK**: TTS streaming, Voice Cloning. See [ElevenLabs docs](https://elevenlabs.io/docs/).
- **Meeting BaaS**: Bot creation, WebSocket audio streams. See [Meeting BaaS docs](https://docs.meetingbaas.com/).

### System Requirements
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (package manager)
- [ngrok](https://ngrok.com/) (for development tunneling)
  - Install: `brew install ngrok`
  - Sign up for an account at [dashboard.ngrok.com/signup](https://dashboard.ngrok.com/signup)
  - Add your authtoken: `ngrok config add-authtoken <YOUR_TOKEN>`
- ffmpeg (for audio format conversion)

### API Keys Required
| Service | Key | How to Get |
|---|---|---|
| Mistral AI | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai/) |
| ElevenLabs | `ELEVENLABS_API_KEY` | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) |
| Meeting BaaS | `MEETING_BAAS_API_KEY` | [dashboard.meetingbaas.com](https://dashboard.meetingbaas.com/) (v2 dashboard) |

## Environment Setup

```bash
# 1. Install dependencies
uv sync

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env with your API keys:
#   MISTRAL_API_KEY=...
#   ELEVENLABS_API_KEY=...
#   MEETING_BAAS_API_KEY=...

# 3. Set up ngrok (one-time)
#    Sign up at https://dashboard.ngrok.com/signup
#    Then add your authtoken:
ngrok config add-authtoken <YOUR_TOKEN>
#    Note: ngrok is started automatically by pyngrok — no separate terminal needed.

# 4. Verify configuration
uv run python scripts/test_setup.py

# 5. Join a meeting
uv run python -m src.main join "https://meet.google.com/xxx-xxxx-xxx"
```

## Verification Steps

### Step 1: Meeting BaaS Connection Test

Verify that a bot can join a Google Meet and that we receive audio.

```bash
# Create a test Google Meet and get the URL
# Then run:
uv run python -m src.main join "https://meet.google.com/xxx-xxxx-xxx"
```

**Expected result**: Bot joins the meeting. You see it as a participant. Console logs show WebSocket connection established and audio frames received.

**What to check**:
- Bot appears in the meeting with the configured name
- Entry message appears in chat
- Console shows `audio_separate_raw` frames arriving
- Audio format is 16kHz mono S16LE PCM (base64)

### Step 2: STT (Voxtral Realtime)

VoxtralSTTProcessor is currently a stub. It needs integration with the Voxtral Realtime API once available.

**Current state**: The STT processor exists as a placeholder FrameProcessor in the pipeline. It receives audio frames but does not yet perform real transcription.

**What to check when implemented**:
- Transcription accuracy is reasonable
- Streaming results arrive incrementally (not all at once)
- Latency from audio chunk sent to first text result
- Language detection works (English and Japanese)

### Step 3: TTS (ElevenLabs)

ElevenLabs TTS is integrated via Pipecat's built-in ElevenLabs service. Test by joining a meeting and triggering a response.

**Expected result**: Agent produces spoken audio in the meeting when it decides to respond.

**What to check**:
- Audio quality is good
- Latency from request to first audio chunk (~75ms for Flash v2.5)
- Output format matches what Meeting BaaS expects

### Step 4: Voice Clone Setup

Voice cloning is not yet implemented. This is a TODO item.

### Step 5: Pipeline Integration Test

Test the full pipeline by joining a real meeting and observing behavior.

```bash
uv run python -m src.main join "https://meet.google.com/xxx-xxxx-xxx"
```

**Expected result**: Bot joins, receives audio, processes it through the pipeline, and generates spoken responses where appropriate.

**What to check**:
- Full pipeline latency (target: <1.3s end-to-end)
- Agent correctly decides when to respond (should_respond logic)
- Agent correctly decides when to stay silent
- Response content is contextually appropriate

### Step 6: E2E Test (Real Google Meet)

Full end-to-end test with a real meeting.

```bash
uv run python -m src.main join "https://meet.google.com/xxx-xxxx-xxx"
```

**Expected result**: Bot joins, listens, responds when addressed, and generates summary after meeting ends.

**What to check**:
- Bot joins and appears in participant list
- Audio from other participants is received and transcribed
- Agent responds only when addressed (passive mode)
- Response audio plays in the meeting
- No echo or feedback loops

## Latency Targets

**Target latencies**:
| Component | Target | Acceptable |
|---|---|---|
| Voxtral Realtime STT | <200ms | <300ms |
| Mistral Agent response | <1000ms | <1500ms |
| ElevenLabs TTS (Flash v2.5) | <75ms | <150ms |
| **Total** | **<1.3s** | **<2.0s** |

## Troubleshooting

### Common Issues

**Meeting BaaS bot doesn't join**
- Check that `MEETING_BAAS_API_KEY` is valid
- Ensure the Google Meet URL is correct and the meeting is active
- Check Meeting BaaS dashboard for error logs
- Verify ngrok authtoken is configured (`ngrok config add-authtoken`)

**No audio received**
- Verify WebSocket connection is established (check logs)
- Ensure `audio_separate_raw` is configured in recording_config
- Check that participants have their microphones on
- Verify audio format expectations (16kHz mono S16LE PCM)

**STT returns empty or garbage**
- Note: VoxtralSTTProcessor is currently a stub
- Check audio format matches Voxtral requirements (16kHz mono S16LE PCM)
- Verify `MISTRAL_API_KEY` is valid

**TTS doesn't produce audio**
- Check `ELEVENLABS_API_KEY` is valid
- Check ElevenLabs usage quota
- Try with default voice first to isolate issues

**Agent doesn't respond when addressed**
- Check `should_respond` tool logic — does it detect name correctly?
- Verify persona name matches expected name
- Check Mistral Agent logs for tool call results
- Test with explicit name mention: "Hey [name], what do you think?"

**High latency (>2s)**
- Check network latency to API endpoints
- Verify you're using Flash v2.5 (not standard v2) for TTS
- Check if Mistral Agent is overloaded (try smaller model)

**Echo or feedback**
- Ensure VAD filters out the bot's own audio
- Check that Meeting BaaS `audio_separate_raw` excludes the bot's stream
- Verify audio output isn't being looped back into input

### API Rate Limits

| Service | Limit | Notes |
|---|---|---|
| Mistral API | Varies by tier | Check [console.mistral.ai](https://console.mistral.ai/) for your limits |
| ElevenLabs | Character quota per plan | Starter: 30K chars/mo, Creator: 100K chars/mo |
| Meeting BaaS | 4h free, then $0.69/h | No rate limit, but cost-aware |

### Useful Debug Commands

```bash
# Check Mistral API key validity
uv run python -c "from mistralai import Mistral; c = Mistral(); print(c.models.list())"

# List ElevenLabs voices
uv run python -c "from elevenlabs import ElevenLabs; c = ElevenLabs(); [print(v.name, v.voice_id) for v in c.voices.get_all().voices]"

# Verify ngrok authtoken is configured
ngrok config check

# Verify project configuration
uv run python scripts/test_setup.py
```
