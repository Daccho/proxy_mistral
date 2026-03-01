import asyncio
import json
import logging
from typing import AsyncIterator, Dict, Any, Optional, List

import requests
import websockets

from .base import BaseMeetingTransport
from src.meeting.tunnel_manager import TunnelManager
from src.config.settings import settings

logger = logging.getLogger(__name__)


class MeetingBaaSTransport(BaseMeetingTransport):
    """Meeting BaaS transport implementation (v2 API).

    Architecture:
    - We start a local WebSocket server
    - We expose it via ngrok
    - We POST /v2/bots to Meeting BaaS with our ngrok WS URL
    - Meeting BaaS connects TO our WS server and streams audio
    """

    def __init__(self, ws_port: Optional[int] = None, public_ws_url: Optional[str] = None):
        self.api_key = settings.meeting_baas.api_key
        self.base_url = settings.meeting_baas.base_url
        self.ws_port = ws_port or settings.meeting_baas.ws_port
        self.bot_id: Optional[str] = None
        # Production: use direct public URL (K8s Ingress); dev: use ngrok
        self._public_ws_url = public_ws_url or settings.meeting_baas.public_ws_url or None

        # WebSocket server state
        self._ws_server = None
        self._tunnel_manager: Optional[TunnelManager] = None
        self._output_ws: Optional[websockets.WebSocketServerProtocol] = None
        self._input_ws: Optional[websockets.WebSocketServerProtocol] = None

        # Track all WebSocket connections for input/output detection
        self._all_ws_connections: set = set()

        # Audio queue for get_audio_stream()
        self._audio_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        # Speaker tracking
        self._current_speakers: List[Dict[str, Any]] = []
        self._last_known_speaker: Optional[Dict[str, Any]] = None

        # Audio chunk counter for trace logging
        self._audio_chunk_count: int = 0

        # Track whether any WS connection was ever established
        self._ws_ever_connected: bool = False

    async def join_meeting(
        self,
        meeting_url: str,
        bot_name: str = "ProxyBot",
        bot_image: str = "",
    ) -> Dict[str, Any]:
        """Join a meeting via Meeting BaaS API."""
        logger.info(f"Joining meeting: {meeting_url}")

        # 1. Start WebSocket server
        self._ws_server = await websockets.serve(
            self._handle_ws_connection,
            "0.0.0.0",
            self.ws_port,
        )
        logger.info(f"WebSocket server started on port {self.ws_port}")

        # 2. Determine public WebSocket URL
        if self._public_ws_url:
            # Production: use K8s Ingress URL directly (no ngrok)
            ws_url = self._public_ws_url
            logger.info(f"Using direct public WS URL: {ws_url}")
        else:
            # Development: create tunnel (cloudflared → localtunnel fallback)
            self._tunnel_manager = TunnelManager()
            ws_url = await self._tunnel_manager.start_tunnel(self.ws_port)

        # 3. Create bot via Meeting BaaS v2 API
        bot_config: Dict[str, Any] = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "streaming_enabled": True,
            "streaming_config": {
                "output_url": ws_url,
                "input_url": ws_url,
                "audio_frequency": 16000,
            },
            "entry_message": "This meeting is being recorded by an AI assistant.",
        }
        if bot_image:
            bot_config["bot_image"] = bot_image

        response = await asyncio.to_thread(
            requests.post,
            f"{self.base_url}/v2/bots",
            json=bot_config,
            headers={
                "Content-Type": "application/json",
                "x-meeting-baas-api-key": self.api_key,
            },
        )
        response.raise_for_status()

        result = response.json()
        self.bot_id = str(result["data"]["bot_id"])
        logger.info(f"Bot created: {self.bot_id}")

        return result

    async def _handle_ws_connection(
        self,
        websocket: websockets.WebSocketServerProtocol,
        path: str = "",
    ):
        """Handle incoming WebSocket connection from Meeting BaaS.

        Meeting BaaS opens multiple connections. We auto-detect which one
        sends binary audio (output channel) and which doesn't (input channel).
        """
        logger.info("Meeting BaaS connected (path=%s)", path)

        # Track whether this connection has sent binary audio
        is_audio_source = False
        self._all_ws_connections.add(websocket)

        try:
            async for message in websocket:
                if isinstance(message, str):
                    # JSON: speaker metadata or other control messages
                    try:
                        data = json.loads(message)
                        if isinstance(data, list) and all(isinstance(s, dict) for s in data):
                            self._current_speakers = data
                            active_speaker = next(
                                (s for s in data if s.get("isSpeaking")),
                                None,
                            )
                            if active_speaker:
                                self._last_known_speaker = active_speaker
                                logger.info("Speaker: %s", active_speaker.get("name"))
                        elif isinstance(data, dict) and "protocol_version" in data:
                            logger.info("Meeting BaaS JSON message: %s", str(data)[:200])
                            # If output already identified & this isn't it, it's the input channel
                            if self._input_ws is None and not is_audio_source and self._output_ws is not None:
                                self._input_ws = websocket
                                logger.info("Meeting BaaS input channel identified (late)")
                        else:
                            logger.info("Meeting BaaS JSON message: %s", str(data)[:200])
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from Meeting BaaS: %s", message[:100])
                else:
                    # Binary: PCM audio data — this is the output channel
                    if not is_audio_source:
                        is_audio_source = True
                        self._output_ws = websocket
                        self._ws_ever_connected = True
                        logger.info("Meeting BaaS audio source identified")
                        # Identify input channel from other connections
                        if self._input_ws is None:
                            for ws in self._all_ws_connections:
                                if ws != websocket and not ws.closed:
                                    self._input_ws = ws
                                    logger.info("Meeting BaaS input channel identified")
                                    break

                    self._audio_chunk_count += 1
                    if self._audio_chunk_count == 1:
                        logger.info("First audio chunk received (%d bytes)", len(message))
                    elif self._audio_chunk_count % 500 == 0:
                        logger.info("Audio chunks received: %d", self._audio_chunk_count)

                    active_speaker = next(
                        (s for s in self._current_speakers if s.get("isSpeaking")),
                        None,
                    )
                    speaker = active_speaker or self._last_known_speaker
                    audio_data = {
                        "participant_id": str(speaker["id"]) if speaker else "unknown",
                        "name": speaker["name"] if speaker else "unknown",
                        "audio": message,
                        "is_host": False,
                        "timestamp": speaker.get("timestamp", 0) if speaker else 0,
                    }
                    await self._audio_queue.put(audio_data)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Meeting BaaS WebSocket disconnected (audio_source=%s)", is_audio_source)
        except Exception as e:
            logger.error("WebSocket handler error: %s", e)
        finally:
            self._all_ws_connections.discard(websocket)
            if is_audio_source:
                self._output_ws = None
            elif self._input_ws == websocket:
                self._input_ws = None

    async def leave_meeting(self) -> None:
        """Leave the current meeting via v2 API."""
        if not self.bot_id:
            logger.warning("No active bot to remove")
            return

        try:
            response = await asyncio.to_thread(
                requests.post,
                f"{self.base_url}/v2/bots/{self.bot_id}/leave",
                headers={
                    "Content-Type": "application/json",
                    "x-meeting-baas-api-key": self.api_key,
                },
            )
            response.raise_for_status()
            logger.info(f"Bot {self.bot_id} removed")
        except Exception as e:
            logger.error(f"Error removing bot: {e}")
        finally:
            await self._cleanup()

    async def _cleanup(self):
        """Clean up all resources."""
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
            self._ws_server = None

        if self._tunnel_manager:
            await self._tunnel_manager.stop_tunnel()
            self._tunnel_manager = None

        self.bot_id = None
        self._output_ws = None
        self._input_ws = None
        self._all_ws_connections.clear()

    async def get_audio_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Get audio stream from the meeting.

        Yields audio data dicts as they arrive from Meeting BaaS.
        Waits for the first connection before considering disconnection.
        """
        while True:
            try:
                audio_data = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=1.0,
                )
                yield audio_data
            except asyncio.TimeoutError:
                # Only end stream if a connection was previously established and then lost
                if (
                    self._ws_ever_connected
                    and self._output_ws is None
                    and self.bot_id is not None
                ):
                    # Wait up to 30 seconds for Meeting BaaS to reconnect
                    logger.info("WebSocket disconnected, waiting for reconnection...")
                    for i in range(30):
                        await asyncio.sleep(1)
                        if self._output_ws is not None:
                            logger.info("WebSocket reconnected after %ds", i + 1)
                            break
                    else:
                        logger.warning("WebSocket not reconnected after 30s, stopping")
                        return
                continue

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio back to the meeting via the bidirectional connection."""
        ws = self._output_ws
        if ws is None:
            # Wait briefly for WS reconnection instead of dropping audio
            logger.warning("No WebSocket available, waiting up to 3s...")
            for _ in range(30):
                await asyncio.sleep(0.1)
                ws = self._output_ws
                if ws is not None:
                    break
            if ws is None:
                logger.warning("WebSocket not available after 3s, dropping audio")
                return

        try:
            await ws.send(audio_data)
        except Exception as e:
            logger.error("Error sending audio: %s", e)
            raise

    async def get_participants(self) -> list[Dict[str, Any]]:
        """Get list of current participants from speaker tracking."""
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "is_speaking": s.get("isSpeaking", False),
            }
            for s in self._current_speakers
        ]

    async def send_chat_message(self, message: str) -> None:
        """Send a chat message to the meeting.

        Note: Meeting BaaS supports entry_message at bot creation time.
        Runtime chat sending may not be supported via the streaming API.
        """
        logger.warning("Runtime chat messages are not supported via Meeting BaaS streaming API")
