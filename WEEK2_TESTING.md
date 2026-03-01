# Week 2 Manual Testing Guide

This guide provides step-by-step instructions for manually testing the Week 2 implementation of Proxy Mistral.

## Prerequisites

1. **API Keys Required**:
   - Meeting BaaS API key (v2)
   - Mistral AI API key
   - ElevenLabs API key
   - ngrok auth token (optional, but recommended)

2. **Software Requirements**:
   - Python 3.11+
   - uv (package manager)
   - ngrok (for tunneling)

## Setup

### 1. Install Dependencies

```bash
# Install dependencies using uv
uv sync
```

### 2. Configure Environment

```bash
# Copy and edit the .env file
cp .env.example .env

# Edit .env and add your API keys:
MEETING_BAAS_API_KEY=your_meeting_baas_api_key
MISTRAL_API_KEY=your_mistral_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
ELEVENLABS_VOICE_ID=your_voice_id
NGROK_AUTH_TOKEN=your_ngrok_auth_token  # Optional
```

## Testing Components

### 1. WebSocket Server Test

```bash
# Test the WebSocket server directly
python -c "
from src.meeting.ws_server import MeetingBaaSWebSocketServer
import asyncio

async def test_ws_server():
    server = MeetingBaaSWebSocketServer(port=8766)  # Use different port for testing
    await server.start()
    print(f'WebSocket server running on port 8766')
    await asyncio.sleep(5)  # Let it run for 5 seconds
    await server.stop()
    print('WebSocket server stopped')

asyncio.run(test_ws_server())
"
```

**Expected Output**:
- Server starts successfully
- No errors during operation
- Server stops cleanly

### 2. ngrok Tunnel Test

```bash
# Test ngrok tunnel creation
python -c "
from src.meeting.ngrok_tunnel import NgrokTunnelManager
import asyncio

async def test_ngrok():
    manager = NgrokTunnelManager()
    manager.configure()  # Uses NGROK_AUTH_TOKEN from .env if available
    url = await manager.start_tunnel(8765)
    print(f'ngrok tunnel URL: {url}')
    await manager.stop_tunnel()
    print('ngrok tunnel stopped')

asyncio.run(test_ngrok())
"
```

**Expected Output**:
- ngrok tunnel starts successfully
- Public URL is displayed (e.g., `https://abc123.ngrok.io`)
- Tunnel stops cleanly

### 3. Meeting BaaS Transport Test

```bash
# Test Meeting BaaS transport initialization
python -c "
from src.meeting.transports.meetingbaas import MeetingBaaSTransport
import asyncio

async def test_transport():
    transport = MeetingBaaSTransport()
    print(f'Transport initialized: {type(transport).__name__}')
    print(f'API Key configured: {bool(transport.api_key)}')
    print(f'Base URL: {transport.base_url}')

asyncio.run(test_transport())
"
```

**Expected Output**:
- Transport initializes without errors
- API key and base URL are correctly loaded from settings

### 4. Pipeline Components Test

```bash
# Test individual pipeline processors
python -c "
from src.pipeline.meeting_processors.voxtral_stt import VoxtralSTTProcessor
from src.pipeline.meeting_processors.meetingbaas_input import MeetingBaaSInputProcessor
from src.pipeline.meeting_processors.meetingbaas_output import MeetingBaaSOutputProcessor
from src.agent.brain import MistralAgentBrain
from src.config.settings import settings

# Test processor initialization
stt_proc = VoxtralSTTProcessor(
    api_key=settings.mistral.api_key,
    sample_rate=settings.meeting_baas.sample_rate
)
print('VoxtralSTTProcessor initialized')

brain_proc = MistralAgentBrain(
    api_key=settings.mistral.api_key,
    model=settings.mistral.model
)
print('MistralAgentBrain initialized')

print('All pipeline components initialized successfully')
"
```

**Expected Output**:
- All processors initialize without errors
- No exception messages

## End-to-End Testing

### 1. Start the Meeting Pipeline

```bash
# Run the main application (this will start the WebSocket server and ngrok tunnel)
python -m src.main join "https://meet.google.com/test-meeting" --bot-name "TestBot"
```

**Expected Behavior**:
1. WebSocket server starts on port 8765
2. ngrok tunnel is created and URL is displayed
3. Meeting BaaS bot is created via v2 API
4. Pipeline components are initialized
5. Application waits for WebSocket connections

### 2. Verify WebSocket Connection

You can test the WebSocket connection using a tool like `wscat`:

```bash
# Install wscat if needed
npm install -g wscat

# Connect to the local WebSocket server (use the ngrok URL in production)
wscat -c ws://localhost:8765
```

**Expected Behavior**:
- Connection is established successfully
- Server logs show new connection

### 3. Test Audio Processing (Simulated)

```bash
# Create a test script to simulate audio input
python -c "
import asyncio
import websockets
import json
import base64

async def test_audio_input():
    uri = 'ws://localhost:8765'
    async with websockets.connect(uri) as websocket:
        # Send speaker metadata
        metadata = [{
            'id': 'participant1',
            'name': 'Test User',
            'isSpeaking': True,
            'timestamp': 1234567890
        }]
        await websocket.send(json.dumps(metadata))
        print('Sent speaker metadata')
        
        # Send binary audio data (simulated)
        audio_data = b'\\x00\\x01\\x02\\x03' * 100  # Simulated PCM audio
        await websocket.send(audio_data)
        print(f'Sent {len(audio_data)} bytes of audio')

asyncio.run(test_audio_input())
"
```

**Expected Behavior**:
- Server receives and processes metadata
- Server receives and processes audio data
- Pipeline processes the audio through STT → Agent → TTS
- No errors in the logs

## Troubleshooting

### Common Issues

1. **ngrok Authentication Failed**:
   - Ensure `NGROK_AUTH_TOKEN` is set in `.env`
   - Run `ngrok config add-authtoken YOUR_TOKEN` manually

2. **WebSocket Connection Failed**:
   - Check that the server is running on the correct port
   - Verify firewall settings
   - Test with local connection first before using ngrok

3. **API Key Errors**:
   - Double-check all API keys in `.env`
   - Ensure keys have the required permissions

4. **Port Conflicts**:
   - Change the port in `config/settings.yaml` if port 8765 is in use
   - Update both WebSocket server and ngrok tunnel ports

### Logs

For detailed debugging, set the log level to DEBUG:

```bash
export LOG_LEVEL=DEBUG
python -m src.main join "https://meet.google.com/test-meeting"
```

## Verification Checklist

- [ ] WebSocket server starts successfully
- [ ] ngrok tunnel is created and accessible
- [ ] Meeting BaaS v2 API calls succeed
- [ ] Pipeline components initialize without errors
- [ ] WebSocket connections are handled properly
- [ ] Audio data flows through the pipeline
- [ ] Error handling works correctly
- [ ] Clean shutdown on Ctrl+C

## Notes

1. **Voxtral STT is a Stub**: The VoxtralSTTProcessor returns `None` for transcriptions. This will be connected to the actual Mistral Voxtral Realtime API in future weeks.

2. **ElevenLabs TTS**: Uses the built-in Pipecat service with Flash v2.5 model for low-latency responses.

3. **Response Logic**: The MistralAgentBrain uses heuristic checks (name mention, question detection) to decide when to respond.

4. **Meeting BaaS v2 API**: The implementation follows the v2 API specification with WebSocket streaming.

5. **Architecture**: The system runs a local WebSocket server that Meeting BaaS connects to, with ngrok providing the public tunnel.

## Next Steps

After successful testing:

1. Implement actual Voxtral Realtime STT connection
2. Add document context management
3. Implement post-meeting summary generation
4. Add error recovery and reconnection logic
5. Create comprehensive integration tests