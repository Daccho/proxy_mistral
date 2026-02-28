import asyncio
import logging
import sys
from typing import Optional

import click
from dotenv import load_dotenv

from src.config.settings import settings
from src.meeting.transports.meetingbaas import MeetingBaaSTransport
from src.pipeline.meeting_pipeline import MeetingPipeline

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.app.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ProxyMistral:
    """Main application class."""

    def __init__(self):
        self.transport: Optional[MeetingBaaSTransport] = None
        self.pipeline: Optional[MeetingPipeline] = None

    async def join_meeting(self, meeting_url: str, bot_name: str = "ProxyBot") -> None:
        """Join a meeting."""
        try:
            logger.info(f"Starting proxy mistral...")
            
            # Initialize transport
            self.transport = MeetingBaaSTransport()
            
            # Join meeting
            meeting_info = await self.transport.join_meeting(meeting_url, bot_name)
            logger.info(f"Joined meeting: {meeting_info}")
            
            # Initialize pipeline
            self.pipeline = MeetingPipeline(self.transport)
            await self.pipeline.setup()
            
            # Send entry notification
            await self.transport.send_chat_message("This meeting is being recorded by an AI assistant")
            
            # Start pipeline
            await self.pipeline.run()
            
        except Exception as e:
            logger.error(f"Error in meeting: {e}")
            raise

    async def leave_meeting(self) -> None:
        """Leave the current meeting."""
        try:
            if self.pipeline:
                await self.pipeline.stop()
            
            if self.transport:
                await self.transport.leave_meeting()
                
            logger.info("Left meeting successfully")
            
        except Exception as e:
            logger.error(f"Error leaving meeting: {e}")
            raise

    async def cleanup(self) -> None:
        """Clean up resources."""
        try:
            await self.leave_meeting()
        except Exception:
            pass  # Ignore errors during cleanup


@click.group()
def cli():
    """Proxy Mistral CLI."""
    pass


@cli.command()
@click.argument("meeting_url")
@click.option("--bot-name", default="ProxyBot", help="Name for the bot")
def join(meeting_url: str, bot_name: str) -> None:
    """Join a meeting."""
    load_dotenv()
    
    app = ProxyMistral()
    
    try:
        asyncio.run(app.join_meeting(meeting_url, bot_name))
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, leaving meeting...")
        asyncio.run(app.cleanup())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


@cli.command()
def leave() -> None:
    """Leave the current meeting."""
    load_dotenv()
    
    app = ProxyMistral()
    
    try:
        asyncio.run(app.leave_meeting())
    except Exception as e:
        logger.error(f"Error leaving meeting: {e}")
        sys.exit(1)


@cli.command()
def status() -> None:
    """Check meeting status."""
    logger.info("Status command not yet implemented")


if __name__ == "__main__":
    cli()