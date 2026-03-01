# Proxy Mistral - Meeting Proxy Agent

An AI agent that attends low-priority meetings on your behalf, equipped with your knowledge, personality, and cloned voice.

低優先度のミーティングに代理出席するAIエージェント。あなたの知識・性格・声で会議に参加します。

**Tech Stack**: Python 3.11+ · Mistral AI · ElevenLabs · Pipecat · Meeting BaaS · FastAPI

## Features / 主な機能

- **AI-powered meeting attendance** — Responds naturally using Mistral AI with function calling (Mistral AIによる自然な応答)
- **Voice cloning** — Speaks with your voice via ElevenLabs Flash v2.5 (ElevenLabsによる声のクローン)
- **Persona system** — Configurable personality, opinions, rules, and meeting behavior via YAML (YAML設定可能なペルソナ)
- **Google Calendar integration** — Auto-detects and joins meetings from your calendar (Googleカレンダー連携で自動参加)
- **Post-meeting summaries** — Generates structured summaries with action items and decisions (議事録自動生成)
- **REST API** — FastAPI server for programmatic control (FastAPI REST API)
- **Security** — OWASP-compliant: input sanitization, rate limiting, audit logging, encrypted credentials (OWASPセキュリティ準拠)
- **Production-ready** — Multi-stage Docker build, Kubernetes support (Docker/K8s対応)
- **Bilingual** — English + Japanese support (日英バイリンガル対応)

## Architecture / アーキテクチャ

```
Google Meet
    │
Meeting BaaS (v2 API)
    │  connects TO our server
    v
ngrok tunnel (wss://xxx.ngrok.io)  ─── or ──→  K8s Ingress (PUBLIC_WS_URL)
    │
    v
Local WS server (:8765) + Pipecat Pipeline
    │
    v
┌──────────────────────────────────────────────────────────┐
│  MeetingBaaSInputProcessor   (WS audio → frames)         │
│       │                                                  │
│  VoxtralSTTProcessor         (speech → text)             │
│       │                                                  │
│  MistralAgentBrain           (判断 + 応答生成)             │
│       │                                                  │
│  ElevenLabsTTSService        (text → speech, ~75ms)      │
│       │                                                  │
│  MeetingBaaSOutputProcessor  (frames → WS audio out)     │
└──────────────────────────────────────────────────────────┘
```

**Flow**: Google Meet → Meeting BaaS → ngrok/K8s → WS server → Pipecat pipeline (STT → Agent → TTS) → audio back to meeting

## Prerequisites / 前提条件

- **Python** 3.11+ (< 3.14)
- **[uv](https://docs.astral.sh/uv/)** — package manager
- **[ngrok](https://ngrok.com/)** — account + authtoken configured (`ngrok config add-authtoken <token>`)
- **API keys**:
  - [Meeting BaaS](https://meetingbaas.com/) — v2 API key
  - [Mistral AI](https://console.mistral.ai/) — API key
  - [ElevenLabs](https://elevenlabs.io/) — API key + voice ID (cloned voice recommended)
- **Google Calendar** (optional) — OAuth2 credentials for auto-join

## Quick Start / クイックスタート

```bash
# 1. Clone and configure / クローンして設定
git clone <repo-url> && cd proxy_mistral
cp .env.example .env
# Edit .env with your API keys / APIキーを.envに記入

# 2. Install dependencies / 依存関係インストール
make install

# 3. Verify setup / セットアップ確認
make test-setup

# 4. Join a meeting / ミーティングに参加
uv run python -m src.main join "https://meet.google.com/abc-def-ghi"
uv run python -m src.main join "https://meet.google.com/abc-def-ghi" --bot-name "YourName"
```

## CLI Commands / CLIコマンド

| Command | Description |
|---|---|
| `join <url> [--bot-name NAME]` | Join a meeting / ミーティングに参加 |
| `leave` | Leave the current meeting / ミーティングから退出 |
| `status` | Show recent meeting history / 最近のミーティング履歴を表示 |
| `auth-calendar` | Set up Google Calendar OAuth2 / Googleカレンダー認証 |
| `serve [--host] [--port]` | Start API server with calendar scheduler / APIサーバー起動 |

All commands are run via `uv run python -m src.main <command>` or `proxy-mistral <command>` if installed.

## Project Structure / プロジェクト構成

```
src/
├── main.py                              # CLI entry point (Click)
├── config/settings.py                   # Pydantic Settings v2
├── agent/
│   ├── brain.py                         # MistralAgentBrain (response decision + generation)
│   ├── tools.py                         # Function calling tools
│   ├── context_manager.py               # Document/context management
│   └── summarizer.py                    # Post-meeting summary generation
├── meeting/
│   ├── transports/meetingbaas.py        # Meeting BaaS v2 API + WS server + ngrok
│   ├── tunnel_manager.py               # ngrok/cloudflare tunneling
│   └── ws_server.py                     # WebSocket server
├── pipeline/
│   ├── meeting_pipeline.py              # Pipecat pipeline orchestration
│   └── meeting_processors/
│       └── voxtral_stt.py               # Voxtral STT processor
├── integrations/google_calendar.py      # Google Calendar auto-join
├── scheduler/                           # APScheduler meeting auto-join
├── security/
│   ├── auth.py                          # API key verification
│   ├── sanitizer.py                     # Input sanitization (OWASP A05)
│   ├── crypto.py                        # Credential encryption
│   ├── rate_limiter.py                  # Rate limiting
│   └── audit.py                         # Audit logging + log sanitization
├── api/app.py                           # FastAPI REST API
└── language/japanese.py                 # Bilingual support
config/
├── personas/default.yaml                # Persona configuration
└── settings.yaml                        # Default app settings
```

## Configuration / 設定

### Environment Variables / 環境変数

Settings are loaded from `.env` via `pydantic-settings`.

| Variable | Description | Required |
|---|---|---|
| `MEETING_BAAS_API_KEY` | Meeting BaaS API key | Yes |
| `MEETING_BAAS_BASE_URL` | Meeting BaaS base URL (default: `https://api.meetingbaas.com`) | No |
| `MISTRAL_API_KEY` | Mistral AI API key | Yes |
| `ELEVENLABS_API_KEY` | ElevenLabs API key | Yes |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice ID (cloned voice recommended) | Yes |
| `LOG_LEVEL` | Logging level (default: `INFO`) | No |
| `PROXY_MISTRAL_API_KEY` | API key for REST API authentication | No |
| `PROXY_MISTRAL_WS_TOKEN` | WebSocket authentication token | No |
| `ALLOWED_ORIGINS` | CORS allowed origins | No |
| `GOOGLE_CALENDAR_CREDENTIALS` | Google Calendar OAuth2 credentials JSON | No |
| `CALENDAR_POLL_INTERVAL` | Calendar polling interval in minutes (default: `5`) | No |
| `CALENDAR_LOOKAHEAD_MINUTES` | How far ahead to look for meetings (default: `15`) | No |
| `SCHEDULER_ENABLED` | Enable auto-join scheduler (default: `true`) | No |
| `MAX_CONCURRENT_MEETINGS` | Max simultaneous meetings (default: `1`) | No |
| `JOIN_BEFORE_START_MINUTES` | Join N minutes before meeting start (default: `2`) | No |
| `AUTO_LEAVE_AFTER_END_MINUTES` | Leave N minutes after meeting end (default: `5`) | No |
| `PUBLIC_WS_URL` | Direct WS URL for K8s (skips ngrok tunnel) | No |

### Persona Configuration / ペルソナ設定

Edit `config/personas/default.yaml` to customize the agent's behavior:

```yaml
name: "mike"
communication_style:
  tone: "professional but friendly"
  verbosity: "concise"
rules:
  - "Never commit to deadlines without saying 'I'll confirm the timeline'"
  - "Always note action items assigned to me"
defer_topics:
  - "budget approvals"
  - "hiring decisions"
meeting_types:
  standup:
    proactivity: "high"
    prepared_update: true
  all_hands:
    proactivity: "low"
    respond_only_when: "directly_addressed"
auto_join:
  standup: true
  all_hands: false
```

See [SPEC.md](SPEC.md) for the full persona schema.

## Production Deployment / 本番デプロイ

### Docker

```bash
# Build / ビルド
docker build -t proxy-mistral .

# Run / 実行
docker run -d \
  --env-file .env \
  -p 8000:8000 \
  -p 8765:8765 \
  proxy-mistral
```

The image uses a multi-stage build (build tools excluded from runtime) and runs as a non-root user.

### Kubernetes

Set `PUBLIC_WS_URL` to your Ingress WebSocket endpoint to skip ngrok tunneling:

```bash
PUBLIC_WS_URL=wss://proxy-mistral.example.com/ws
```

For Google Calendar credentials:

```bash
# Generate token locally
proxy-mistral auth-calendar

# Create K8s secret
kubectl create secret generic proxy-mistral-secrets \
  --from-literal=google_calendar_credentials='<token_json>'
```

## Cost Estimate / コスト見積もり

Per 1-hour meeting / 1時間のミーティングあたり:

| Service | Cost |
|---|---|
| Meeting BaaS | $0.69 |
| Voxtral STT | ~$0.36 |
| Mistral Agent | ~$0.03 |
| ElevenLabs TTS | ~$0.05 |
| **Total** | **~$1.10** |

Plus ElevenLabs subscription ($5–22/month for voice cloning).

**Latency / レイテンシ**: End-to-end ~0.8–1.3 seconds (within natural conversational pause).

## Development / 開発

```bash
make install     # Install dependencies / 依存関係インストール
make test        # Run tests / テスト実行
make lint        # Run ruff linter / リンター実行
make format      # Format with black + isort / コードフォーマット
make test-setup  # Verify config + transport / セットアップ確認
make clean       # Clean build artifacts / ビルド成果物削除
```

## Current Status / 現在のステータス

**Implemented / 実装済み:**
- Meeting BaaS v2 integration (bot creation, WS server, ngrok tunnel)
- Pipecat pipeline with custom FrameProcessors
- MistralAgentBrain with response decision + function calling
- ElevenLabs TTS (Flash v2.5)
- Google Calendar integration + auto-join scheduler
- FastAPI REST API with security middleware
- Post-meeting summary generation
- OWASP security (auth, sanitization, rate limiting, audit, encryption)
- Click CLI (join, leave, status, auth-calendar, serve)
- Pydantic Settings + persona YAML
- Structlog logging with sensitive data redaction
- Bilingual support (English + Japanese)
- Production Docker image (multi-stage, non-root)

**Not yet functional / 未実装:**
- VoxtralSTTProcessor (`_transcribe()` is a stub — needs Voxtral Realtime API)
- SQLite storage layer
- Full test suite
- Voice clone setup script
- Meeting simulation for local testing

See [SPEC.md](SPEC.md) for the full roadmap.

## License

MIT
