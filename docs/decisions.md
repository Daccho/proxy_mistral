# Design Decisions

Architecture Decision Records (ADRs) for the Meeting Proxy Agent.

---

## ADR-001: Voxtral Realtime over ElevenLabs STT

**Status**: Accepted

**Context**: Need a real-time STT service for converting meeting audio to text. Two candidates:
- Mistral Voxtral Realtime (sub-200ms latency, $0.006/min)
- ElevenLabs Scribe (~300ms latency)

**Decision**: Use Voxtral Realtime for real-time STT.

**Rationale**:
- Lower latency (~200ms vs ~300ms) — critical for natural conversational response
- Maximizes Mistral ecosystem usage (project goal)
- Cheaper ($0.006/min vs ElevenLabs pricing)
- Keeps all AI inference on Mistral side (simpler billing, fewer API keys)

**Trade-off**: ElevenLabs STT might have better integration with their TTS pipeline, but the latency difference outweighs this convenience.

---

## ADR-002: Meeting BaaS over Self-hosted Browser Bot

**Status**: Accepted

**Context**: Need to join Google Meet programmatically with bidirectional audio. Options:
- Meeting BaaS ($0.69/h, 4h free): managed service with WebSocket audio streams
- Self-hosted headless browser bot (Puppeteer/Playwright): full control, no per-hour cost

**Decision**: Use Meeting BaaS for MVP.

**Rationale**:
- Bidirectional audio is the hardest part — Meeting BaaS handles this reliably
- v2 streaming provides per-participant speaker metadata + raw PCM audio over WebSocket (essential for speaker identification)
- Bot customization available (name, avatar, entry message)
- Dramatically reduces development time (weeks → days for meeting integration)
- $0.69/h is acceptable for MVP validation
- Self-hosted bot can be Phase 3+ when/if needed

**Trade-off**: Recurring cost and vendor dependency. If Meeting BaaS goes down or changes pricing, we need a fallback. Phase 3 plans self-hosted browser bot as an option.

---

## ADR-003: Pipecat as Pipeline Framework

**Status**: Accepted

**Context**: Need a real-time voice pipeline framework to orchestrate STT → LLM → TTS. Options:
- Pipecat: open-source, built-in Mistral & ElevenLabs support
- LiveKit Agents: alternative real-time framework
- Custom pipeline: build from scratch with asyncio

**Decision**: Use Pipecat.

**Rationale**:
- Built-in `MistralLLMService` and `ElevenLabsTTSService` processors
- Handles VAD (Silero) out of the box
- Interruption handling (critical for natural conversation)
- Frame-based architecture makes it easy to add custom processors
- Active open-source community
- `uv add "pipecat-ai[mistral,elevenlabs]"` gets everything needed

**Trade-off**: Pipecat is Python-only, which constrains our language choice. But since Mistral and ElevenLabs SDKs are Python-first, this is acceptable.

---

## ADR-004: FastAPI over Gin (Go)

**Status**: Accepted

**Context**: Need an API server for REST endpoints and WebSocket handling. Options:
- FastAPI (Python): async, WebSocket support, auto-docs
- Gin (Go): high performance, strong typing

**Decision**: Use FastAPI (Python).

**Rationale**:
- Pipecat is Python-only — using Go would require running two separate processes and cross-process communication
- Mistral Python SDK (`mistralai`) is the primary/first-class SDK
- ElevenLabs Python SDK (`elevenlabs`) is the primary/first-class SDK
- FastAPI's async support handles WebSocket and HTTP concurrently
- Single language = simpler deployment, debugging, and hiring
- Auto-generated OpenAPI docs are a bonus

**Trade-off**: Go would offer better raw performance, but the overhead of cross-language communication would negate this advantage. Python's GIL is not a concern since we're I/O-bound (waiting on API calls, WebSocket streams).

---

## ADR-005: Mistral Agents API over Raw Chat Completions

**Status**: Accepted

**Context**: Need an LLM backend for response generation. Options:
- Mistral Agents API: persistent conversations, built-in function calling, Document Library
- Raw Mistral Chat Completions: simpler, more control

**Decision**: Use Mistral Agents API.

**Rationale**:
- Server-side conversation history (no need to manage context window ourselves for normal-length meetings)
- Built-in Document Library tool for RAG (no need to build vector search infrastructure)
- Persistent agent with tools = cleaner architecture
- 256K context window on mistral-medium-2505
- Function calling for `should_respond`, `lookup_document`, `note_action_item`, etc.

**Trade-off**: Less control over conversation management. For very long meetings (2+ hours), we still need client-side context compression. But for typical 30-60 min meetings, server-side management is sufficient.

---

## ADR-006: Passive Agent Behavior (MVP)

**Status**: Accepted

**Context**: Should the agent proactively participate in meetings or only respond when addressed?

**Decision**: Passive by default — only respond when directly addressed by name or asked a direct question.

**Rationale**:
- Lower risk of embarrassment (wrong interjections)
- Simpler to implement correctly
- Users can gradually increase proactivity via persona YAML `meeting_types` settings
- Standup meetings are an exception (proactivity: "high") where the agent gives prepared updates

**Trade-off**: May seem "too quiet" in casual meetings. But better quiet than wrong. Proactivity can be tuned per meeting type.

---

## ADR-007: SQLite for MVP Storage

**Status**: Accepted

**Context**: Need to store transcripts, summaries, action items, and meeting metadata. Options:
- SQLite: zero-config, file-based, good enough for single-user
- PostgreSQL: production-grade, scalable
- Redis: fast, good for caching

**Decision**: SQLite for MVP.

**Rationale**:
- Zero configuration — just a file
- Good enough for single-user MVP (one person's meetings)
- Easy to migrate to PostgreSQL later if needed
- Python has built-in sqlite3 support
- Full SQL capabilities for querying meeting history

**Trade-off**: Not suitable for multi-user or high-concurrency scenarios. Will need migration to PostgreSQL if the tool grows beyond single-user.

---

## ADR-008: Speaker Identification via Meeting BaaS v2 Streaming

**Status**: Accepted (updated for v2 API)

**Context**: Need to know who said what during the meeting. Options:
- Meeting BaaS v2 streaming: JSON speaker metadata + binary PCM audio over WebSocket
- Speaker diarization model (pyannote, etc.): ML-based speaker separation
- Voxtral Batch diarization: built-in speaker labels

**Decision**: Use v2 streaming speaker metadata for real-time, Voxtral Batch for post-meeting.

**Rationale**:
- Real-time: v2 streaming sends JSON metadata `[{name, id, timestamp, isSpeaking}]` interleaved with binary PCM audio — we track the active speaker and associate audio chunks with them
- Post-meeting: Voxtral Batch (Transcribe V2) provides speaker diarization for higher accuracy
- No need to train or deploy a separate diarization model

**Trade-off**: Speaker attribution depends on the `isSpeaking` flag accuracy from Meeting BaaS. For overlapping speakers, only one is marked active at a time. Acceptable for MVP.

---

## ADR-009: Stealth Identity with Honest Disclosure

**Status**: Accepted

**Context**: Should the bot identify as AI or as the user?

**Decision**: Bot impersonates the user (same name, cloned voice) but honestly admits to being AI if directly asked.

**Rationale**:
- Minimizes meeting disruption — participants don't need to adjust their behavior
- Cloned voice makes the experience seamless
- Honest disclosure maintains trust if questioned
- Entry chat message "This meeting is being recorded" provides passive notice
- Ethical middle ground between full transparency and full stealth

**Trade-off**: Could be seen as deceptive. Mitigated by the recording notice and honest disclosure policy. Users should inform their teams about using this tool.

---

## ADR-010: structlog for Logging

**Status**: Accepted

**Context**: Need structured logging for debugging, monitoring, and post-incident analysis.

**Decision**: Use structlog with file-based output.

**Rationale**:
- Structured JSON logs are easily searchable and parseable
- Contextual logging (bind meeting_id, participant_id to logger)
- Python-native, lightweight
- File output sufficient for MVP (can add cloud logging later)
- No external infrastructure required

**Trade-off**: No real-time monitoring dashboard. Acceptable for MVP — cloud logging services can be added in Phase 2+.
