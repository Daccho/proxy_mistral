import asyncio
import json
import logging
from typing import AsyncIterator, Dict, Any, Optional, List

import requests
import websockets

from pyngrok import ngrok

from .base import BaseMeetingTransport
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

    def __init__(self):
        self.api_key = settings.meeting_baas.api_key
        self.base_url = settings.meeting_baas.base_url
        self.ws_port = settings.meeting_baas.ws_port
        self.bot_id: Optional[str] = None

        # WebSocket server state
        self._ws_server = None
        self._ngrok_tunnel = None
        self._output_ws: Optional[websockets.WebSocketServerProtocol] = None
        self._input_ws: Optional[websockets.WebSocketServerProtocol] = None

        # Audio queue for get_audio_stream()
        self._audio_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        # Speaker tracking
        self._current_speakers: List[Dict[str, Any]] = []

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

        # 2. Create ngrok tunnel (HTTP, free tier compatible)
        self._ngrok_tunnel = ngrok.connect(self.ws_port, "http")
        ngrok_url = self._ngrok_tunnel.public_url
        # Convert https:// to wss:// (or http:// to ws://)
        ws_url = ngrok_url.replace("https://", "wss://").replace("http://", "ws://")
        logger.info(f"ngrok tunnel: {ws_url}")

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
        }
        if bot_image:
            bot_config["bot_image"] = bot_image

        response = requests.post(
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

        Meeting BaaS sends:
        - JSON strings: speaker metadata [{name, id, timestamp, isSpeaking}]
        - Binary data: raw PCM audio (16kHz mono 16-bit)
        """
        self._output_ws = websocket
        logger.info("Meeting BaaS connected to our WebSocket server")

        try:
            async for message in websocket:
                if isinstance(message, str):
                    # JSON: speaker metadata
                    try:
                        speakers = json.loads(message)
                        self._current_speakers = speakers
                        # Find the active speaker
                        active_speaker = next(
                            (s for s in speakers if s.get("isSpeaking")),
                            None,
                        )
                        if active_speaker:
                            logger.debug(f"Speaker: {active_speaker.get('name')}")
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from Meeting BaaS: {message[:100]}")
                else:
                    # Binary: PCM audio data
                    active_speaker = next(
                        (s for s in self._current_speakers if s.get("isSpeaking")),
                        None,
                    )
                    audio_data = {
                        "participant_id": str(active_speaker["id"]) if active_speaker else "unknown",
                        "name": active_speaker["name"] if active_speaker else "unknown",
                        "audio": message,
                        "is_host": False,
                        "timestamp": active_speaker.get("timestamp", 0) if active_speaker else 0,
                    }
                    await self._audio_queue.put(audio_data)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Meeting BaaS WebSocket disconnected")
        except Exception as e:
            logger.error(f"WebSocket handler error: {e}")
        finally:
            self._output_ws = None

    async def leave_meeting(self) -> None:
        """Leave the current meeting via v2 API."""
        if not self.bot_id:
            logger.warning("No active bot to remove")
            return

        try:
            response = requests.post(
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

        if self._ngrok_tunnel:
            ngrok.disconnect(self._ngrok_tunnel.public_url)
            self._ngrok_tunnel = None

        self.bot_id = None
        self._output_ws = None
        self._input_ws = None

    async def get_audio_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Get audio stream from the meeting.

        Yields audio data dicts as they arrive from Meeting BaaS.
        """
        while True:
            try:
                audio_data = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=1.0,
                )
                yield audio_data
            except asyncio.TimeoutError:
                # No audio received, check if still connected
                if self._output_ws is None and self.bot_id is not None:
                    logger.warning("WebSocket disconnected, ending audio stream")
                    return
                continue

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio back to the meeting."""
        if self._output_ws is None:
            raise RuntimeError("Not connected to Meeting BaaS WebSocket")

        try:
            await self._output_ws.send(audio_data)
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
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
