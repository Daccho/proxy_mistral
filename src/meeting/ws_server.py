import asyncio
import json
import logging
import base64
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, parse_qs
import websockets
from websockets.server import WebSocketServerProtocol

from src.config.settings import settings
from src.security.auth import verify_ws_token

logger = logging.getLogger(__name__)


class MeetingBaaSWebSocketServer:
    """WebSocket server for Meeting BaaS v2 API integration."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.server: Optional[websockets.server.WebSocketServer] = None
        self.connected_clients: List[WebSocketServerProtocol] = []
        self._running = False
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the WebSocket server."""
        if self._running:
            logger.warning("WebSocket server is already running")
            return

        logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
        
        self.server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
            ping_interval=None,
            close_timeout=5
        )
        
        self._running = True
        logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return

        logger.info("Stopping WebSocket server...")
        
        # Close all client connections
        for client in self.connected_clients:
            try:
                await client.close()
            except Exception as e:
                logger.debug(f"Error closing client connection: {e}")
        
        self.connected_clients.clear()
        
        # Stop the server
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        
        self._running = False
        self._stop_event.set()
        logger.info("WebSocket server stopped")

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket connection with token authentication."""
        client_addr = websocket.remote_address
        logger.info(f"New WebSocket connection attempt from {client_addr}")

        # A01/A10: Validate connection token from query parameter
        parsed = urlparse(path)
        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0]
        if not verify_ws_token(token or ""):
            logger.warning(f"Rejected WS connection from {client_addr}: invalid token")
            await websocket.close(1008, "Invalid or missing token")
            return

        logger.info(f"Authenticated WS connection from {client_addr}")

        try:
            self.connected_clients.append(websocket)
            
            # Handle messages from Meeting BaaS
            async for message in websocket:
                if isinstance(message, str):
                    # JSON message (speaker metadata)
                    await self._handle_json_message(message, websocket)
                elif isinstance(message, bytes):
                    # Binary message (PCM audio)
                    await self._handle_binary_message(message, websocket)
                else:
                    logger.warning(f"Unknown message type: {type(message)}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {websocket.remote_address}")
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
        finally:
            if websocket in self.connected_clients:
                self.connected_clients.remove(websocket)

    async def _handle_json_message(self, message: str, websocket: WebSocketServerProtocol) -> None:
        """Handle JSON messages (speaker metadata)."""
        try:
            data = json.loads(message)
            logger.debug(f"Received JSON message: {data}")
            
            # This would be processed by the pipeline
            # For now, just log it
            if isinstance(data, list):
                for speaker in data:
                    logger.info(f"Speaker: {speaker.get('name', 'unknown')} - Speaking: {speaker.get('isSpeaking', False)}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message: {e}")
        except Exception as e:
            logger.error(f"Error handling JSON message: {e}")

    async def _handle_binary_message(self, message: bytes, websocket: WebSocketServerProtocol) -> None:
        """Handle binary messages (PCM audio)."""
        try:
            # This would be sent to the STT processor
            # For now, just log the size
            logger.debug(f"Received binary audio: {len(message)} bytes")

        except Exception as e:
            logger.error(f"Error handling binary message: {e}")

    async def send_audio_response(self, audio_data: bytes) -> None:
        """Send audio response to all connected clients."""
        if not self.connected_clients:
            logger.warning("No connected clients to send audio to")
            return

        try:
            for client in self.connected_clients:
                await client.send(audio_data)
            
            logger.debug(f"Sent audio response to {len(self.connected_clients)} clients")

        except Exception as e:
            logger.error(f"Error sending audio response: {e}")

    async def send_speaker_metadata(self, metadata: List[Dict[str, Any]]) -> None:
        """Send speaker metadata to all connected clients."""
        if not self.connected_clients:
            logger.warning("No connected clients to send metadata to")
            return

        try:
            message = json.dumps(metadata)
            for client in self.connected_clients:
                await client.send(message)
            
            logger.debug(f"Sent speaker metadata to {len(self.connected_clients)} clients")

        except Exception as e:
            logger.error(f"Error sending speaker metadata: {e}")

    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running