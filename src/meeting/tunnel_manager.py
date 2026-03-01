import asyncio
import logging
import re
import shutil
from typing import Optional

logger = logging.getLogger(__name__)


class TunnelManager:
    """Manages a tunnel to expose a local port publicly.

    Tries cloudflared first (best WebSocket support), falls back to localtunnel.
    """

    _MAX_CLOUDFLARED_RETRIES = 3

    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._ws_url: Optional[str] = None
        self._backend: Optional[str] = None  # "cloudflared" or "localtunnel"

    async def start_tunnel(self, port: int) -> str:
        """Start a tunnel to the given local port. Returns public wss:// URL."""
        if self._process is not None:
            return self._ws_url or ""

        # Try cloudflared first
        if shutil.which("cloudflared"):
            url = await self._try_cloudflared(port)
            if url:
                self._ws_url = url
                self._backend = "cloudflared"
                logger.info("Tunnel (%s): %s", self._backend, self._ws_url)
                return self._ws_url

        # Fallback: localtunnel via npx
        if shutil.which("npx"):
            url = await self._try_localtunnel(port)
            if url:
                self._ws_url = url
                self._backend = "localtunnel"
                logger.info("Tunnel (%s): %s", self._backend, self._ws_url)
                return self._ws_url

        raise RuntimeError("No tunnel backend available. Install cloudflared or npx.")

    async def stop_tunnel(self) -> None:
        """Stop the tunnel."""
        if self._process is None:
            return

        logger.info("Stopping tunnel (%s)...", self._backend)
        try:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass
        finally:
            self._process = None
            self._ws_url = None
            self._backend = None

    def get_ws_url(self) -> Optional[str]:
        return self._ws_url

    # ── cloudflared ──────────────────────────────────────────────────

    async def _try_cloudflared(self, port: int) -> Optional[str]:
        """Try cloudflared with retries."""
        for attempt in range(1, self._MAX_CLOUDFLARED_RETRIES + 1):
            logger.info("cloudflared attempt %d/%d...", attempt, self._MAX_CLOUDFLARED_RETRIES)

            proc = await asyncio.create_subprocess_exec(
                "cloudflared", "tunnel", "--url", f"http://localhost:{port}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            url = await self._read_cloudflared_url(proc)
            if url:
                self._process = proc
                return url.replace("https://", "wss://").replace("http://", "ws://")

            # Clean up failed process
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

            if attempt < self._MAX_CLOUDFLARED_RETRIES:
                logger.warning("cloudflared failed (attempt %d/%d), retrying in 2s...",
                               attempt, self._MAX_CLOUDFLARED_RETRIES)
                await asyncio.sleep(2)

        logger.warning("cloudflared failed after %d attempts, falling back to localtunnel",
                        self._MAX_CLOUDFLARED_RETRIES)
        return None

    async def _read_cloudflared_url(self, proc: asyncio.subprocess.Process) -> Optional[str]:
        """Read stderr from cloudflared to extract the tunnel URL."""
        if not proc.stderr:
            return None

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        try:
            for _ in range(60):  # Up to ~15s (60 * 0.25s reads)
                try:
                    line = await asyncio.wait_for(proc.stderr.readline(), timeout=0.5)
                except asyncio.TimeoutError:
                    if proc.returncode is not None:
                        return None
                    continue

                if not line:
                    return None  # EOF — process exited

                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("cloudflared: %s", text)

                match = url_pattern.search(text)
                if match:
                    return match.group(0)
        except Exception as e:
            logger.error("Error reading cloudflared output: %s", e)

        return None

    # ── localtunnel ──────────────────────────────────────────────────

    async def _try_localtunnel(self, port: int) -> Optional[str]:
        """Start localtunnel via npx."""
        logger.info("Starting localtunnel on port %d...", port)

        proc = await asyncio.create_subprocess_exec(
            "npx", "localtunnel", "--port", str(port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        url = await self._read_localtunnel_url(proc)
        if url:
            self._process = proc
            return url.replace("https://", "wss://").replace("http://", "ws://")

        # Clean up
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

        return None

    async def _read_localtunnel_url(self, proc: asyncio.subprocess.Process) -> Optional[str]:
        """Read stdout from localtunnel to extract URL. Format: 'your url is: https://xxx.loca.lt'"""
        if not proc.stdout:
            return None

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.loca\.lt")

        try:
            for _ in range(60):  # Up to ~30s
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    if proc.returncode is not None:
                        return None
                    continue

                if not line:
                    return None

                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("localtunnel: %s", text)

                match = url_pattern.search(text)
                if match:
                    return match.group(0)
        except Exception as e:
            logger.error("Error reading localtunnel output: %s", e)

        return None
