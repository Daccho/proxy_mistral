# E2E Manual Test Guide

## Prerequisites

### System Requirements
- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- [ngrok](https://ngrok.com/) — `brew install ngrok`
- Google Chrome (Google Meet用)

### API Keys

| Service | Env Var | 取得先 |
|---|---|---|
| Mistral AI | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai/) |
| ElevenLabs | `ELEVENLABS_API_KEY` | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) |
| ElevenLabs Voice | `ELEVENLABS_VOICE_ID` | ElevenLabs Voice Library から取得 |
| Meeting BaaS | `MEETING_BAAS_API_KEY` | [meetingbaas.com](https://meetingbaas.com/) v2 dashboard |

## Environment Setup

```bash
# 1. Install dependencies
uv sync

# 2. .env を作成
cp .env.example .env
# .env を編集して API キーを設定:
#   MISTRAL_API_KEY=...
#   ELEVENLABS_API_KEY=...
#   ELEVENLABS_VOICE_ID=...
#   MEETING_BAAS_API_KEY=...
#   ENVIRONMENT=development

# 3. ngrok authtoken を設定 (初回のみ)
ngrok config add-authtoken <YOUR_TOKEN>
# ※ ngrok は pyngrok が自動起動するので手動起動は不要
```

## Pre-flight Checks

テスト前にAPIキーの疎通を確認する。

```bash
# Mistral API
uv run python -c "
from mistralai import Mistral
c = Mistral(api_key='YOUR_KEY')
print(c.models.list())
"

# ElevenLabs voices
uv run python -c "
from elevenlabs import ElevenLabs
c = ElevenLabs(api_key='YOUR_KEY')
for v in c.voices.get_all().voices[:5]:
    print(v.name, v.voice_id)
"

# Meeting BaaS
uv run python -c "
import requests
r = requests.get('https://api.meetingbaas.com/v2/bots', headers={'x-meeting-baas-api-key': 'YOUR_KEY'})
print(r.status_code, r.text[:200])
"

# Configuration validation
uv run python scripts/test_setup.py
```

## E2E Manual Test Procedure

### Step 1: Google Meet を作成

1. [Google Meet](https://meet.google.com/) で新しいミーティングを作成
2. ミーティングURLをコピー (例: `https://meet.google.com/abc-defg-hij`)
3. 自分がミーティングに参加した状態にしておく

### Step 2: Bot を参加させる

```bash
uv run python -m src.main join "https://meet.google.com/abc-defg-hij" --bot-name "daccho-proxy"
```

**確認ポイント (ログ)**:
```
Starting proxy mistral...
WebSocket server started on port 8765
ngrok tunnel: wss://xxxx.ngrok-free.app
Bot created: <bot_id>
Joined meeting: {...}
Setting up meeting pipeline...
Meeting pipeline setup complete (meeting_id=...)
Starting meeting pipeline...
MistralAgentBrain initialized (persona=daccho, meeting_type=default)
```

**確認ポイント (Google Meet 画面)**:
- Bot が参加者リストに表示される
- チャットに `"This meeting is being recorded by an AI assistant."` が表示される
- `Meeting BaaS connected to our WebSocket server` がログに出る

### Step 3: STT テスト (音声→テキスト)

1. マイクをONにして何か話す (例: "Hello, can you hear me?")
2. ログを確認:

```
First audio chunk received (3200 bytes)          ← meetingbaas.py
First audio frame received from: <your_name>     ← MeetingBaaSInputProcessor
VoxtralSTT: receiving audio from pipeline        ← VoxtralSTTProcessor
VoxtralSTT started (model=..., delay=1000ms)     ← 初回のみ
Voxtral Realtime session created                 ← API接続成功
STT final: [<your_name>] Hello, can you hear me? ← 最終認識結果
```

**確認ポイント**:
- `First audio chunk received` が出る → Meeting BaaS からバイナリ音声が到着
- `First audio frame received` が出る → InputProcessor がパイプラインにフレームを送信
- `VoxtralSTT: receiving audio from pipeline` が出る → STTが音声を受信
- `Voxtral Realtime session created` が出る → Voxtral API に接続成功
- `STT final:` が出る → 文字起こし成功

**ログが途中で止まる場合**:
- `First audio chunk` が出ない → Meeting BaaS WebSocket は接続されたが音声が来ていない (マイクON確認)
- `First audio frame` が出ない → `get_audio_stream()` がブロックしている
- `VoxtralSTT: receiving audio` が出ない → Pipecat パイプラインのフレーム伝搬に問題
- `Voxtral Realtime session` が出ない → Mistral API key か Voxtral エンドポイントに問題

### Step 4: Agent Brain テスト (応答判定 + 生成)

Bot に直接話しかけて応答を確認する。

**テストケース A: 名前で呼ぶ**
> "daccho, what do you think about this?"

期待: Bot が応答する (名前一致で `_should_respond` → `True`)

**テストケース B: 一般的な質問**
> "Can you summarize what we discussed?"

期待: `direct_markers` に "can you" が含まれるので応答する

**テストケース C: Bot に関係ない発言**
> "I had lunch at the new ramen place."

期待: 応答しない (`_should_respond` → `False`)

**テストケース D: defer_topics**
> "daccho, can you approve the budget for this project?"

期待: `defer_to_user` ツールが呼ばれ、「確認して折り返します」的な応答

**確認ポイント (ログ)**:
```
# 応答時
Recorded action item: ... (assigned to: ...)   ← note_action_item ツール
Recorded decision: ...                          ← note_decision ツール
Deferred question: ... (reason: ...)            ← defer_to_user ツール
```

### Step 5: TTS テスト (テキスト→音声)

Agent が応答を生成すると、ElevenLabs TTS で音声に変換されてミーティングに送信される。

**確認ポイント**:
- Bot の音声が Google Meet で聞こえる
- 音質が自然で聞き取れる
- レイテンシが許容範囲内 (2秒以内)
- `Sent audio response: <N> bytes` がログに出る

### Step 6: ミーティング終了

`Ctrl+C` でプロセスを停止する。

```
Received keyboard interrupt, leaving meeting...
Meeting pipeline stopped
```

**Post-meeting summary が生成される**:
```
Generated summary for meeting: Meeting https://meet.google.com/...
Post-meeting summary generated:
# Meeting https://meet.google.com/...
**Meeting ID:** <uuid>
**Date:** ...
**Participants:** ...

## Executive Summary
...

## Action Items
- ...

## Decisions
- ...
```

**確認ポイント**:
- `MeetingSummarizer` が Mistral AI を呼んでサマリーを生成
- アクションアイテム・決定事項が正しく抽出されている
- Bot が `leave_meeting` APIを呼んで正常退出
- ngrok tunnel がクリーンアップされる

## Post-meeting Verification

### SQLite データ確認

```bash
# ミーティング履歴
sqlite3 data/context.db "SELECT id, title, summary FROM meetings ORDER BY created_at DESC LIMIT 5;"

# 文字起こし
sqlite3 data/context.db "SELECT speaker, text FROM transcripts WHERE meeting_id='<meeting_id>' LIMIT 20;"

# CLI での確認
uv run python -m src.main status
```

### ログの全体フロー

正常なE2Eフローでは以下の順でログが出る:

1. `Starting proxy mistral...`
2. `WebSocket server started on port 8765`
3. `ngrok tunnel: wss://...`
4. `Bot created: <bot_id>`
5. `Meeting pipeline setup complete`
6. `MistralAgentBrain initialized`
7. `Meeting BaaS connected to our WebSocket server`
8. `VoxtralSTT: Connecting to Voxtral Realtime...`
9. `VoxtralSTT: transcription_segment ...` (話すたびに)
10. `Sent audio response: <N> bytes` (応答時)
11. `Meeting pipeline stopped` (Ctrl+C)
12. `Post-meeting summary generated: ...`
13. `Bot <bot_id> removed`
14. `Left meeting successfully`

## Latency Targets

| Component | Target | Acceptable |
|---|---|---|
| Voxtral Realtime STT | <200ms | <300ms |
| Mistral Agent response | <1000ms | <1500ms |
| ElevenLabs TTS (Flash v2.5) | <75ms | <150ms |
| **Total E2E** | **<1.3s** | **<2.0s** |

## Troubleshooting

### Bot がミーティングに参加しない
- `MEETING_BAAS_API_KEY` が正しいか確認
- Google Meet のURLが正しく、ミーティングがアクティブか確認
- [Meeting BaaS dashboard](https://meetingbaas.com/) でエラーログ確認
- ngrok authtoken が設定されているか: `ngrok config check`

### WebSocket に接続されない
- `streaming_config` の `output_url` / `input_url` がngrokのWSS URLか確認
- ファイアウォールでポート8765がブロックされていないか確認
- `Meeting BaaS connected to our WebSocket server` が出ない場合はngrokトンネルに問題がある

### STT が動作しない
- `MISTRAL_API_KEY` が有効か確認
- Voxtral Realtime API のエンドポイントがアクセス可能か確認
- 音声フォーマットが16kHz mono S16LE PCMか確認
- マイクがONになっているか

### TTS で音声が出ない
- `ELEVENLABS_API_KEY` と `ELEVENLABS_VOICE_ID` が正しいか確認
- ElevenLabs の使用量クォータを確認
- まずデフォルトvoiceで試して問題を切り分ける

### Agent が応答しない
- ペルソナ名 (`config/personas/default.yaml` の `name`) で呼びかけているか確認
- "Can you..." など `direct_markers` に含まれるフレーズで話しかけてみる
- Mistral API のレスポンスがログに出ているか確認
- `_should_respond` が `False` を返していないか確認

### レイテンシが高い (>2s)
- ネットワーク環境を確認
- TTS モデルが `eleven_flash_v2_5` になっているか確認
- Mistral モデルを `mistral-small-latest` に変更して試す

### Echo / Feedback loop
- Meeting BaaS v2 streaming がBot自身の音声を入力から除外しているか確認
- VAD が Bot の音声を除外しているか確認

## Architecture Overview

```
Google Meet
    ↓ (Meeting BaaS v2 WebSocket)
MeetingBaaSTransport (WS Server on :8765 via ngrok)
    ↓ audio_queue
MeetingBaaSInputProcessor (Pipecat FrameProcessor)
    ↓ InputAudioRawFrame
VoxtralSTTProcessor (Voxtral Realtime API)
    ↓ TranscriptionFrame
MistralAgentBrain (Mistral chat.complete + function calling)
    ↓ TextFrame
ElevenLabsTTSService (ElevenLabs Flash v2.5)
    ↓ TTSAudioRawFrame
MeetingBaaSOutputProcessor → send_audio() → Meeting → Google Meet
```

**Post-meeting:**
```
MistralAgentBrain.get_transcript() + get_recorded_data()
    ↓
MeetingSummarizer (Mistral AI)
    ↓
DocumentContextManager (SQLite + FTS5)
```

## Cost Estimates (per 1h meeting)

| Service | Estimate | Notes |
|---|---|---|
| Meeting BaaS | $0.69/h (有料時) | 最初4hは無料 |
| Mistral AI | ~$0.50-2.00 | モデルとトークン量による |
| ElevenLabs | ~30K chars | Starter plan: 30K chars/月 |
