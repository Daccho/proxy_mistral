import asyncio
import logging
import os
import sys
from typing import Optional

import click
import structlog
from dotenv import load_dotenv

from src.config.settings import settings
from src.meeting.transports.meetingbaas import MeetingBaaSTransport
from src.pipeline.meeting_pipeline import MeetingPipeline

# Configure structlog logging
def configure_logging():
    """Configure structured logging with structlog."""
    
    from src.security.audit import sanitize_log_message

    def _sanitize_processor(logger, method_name, event_dict):
        """A09: Redact sensitive data (API keys, tokens) from log output."""
        if "event" in event_dict and isinstance(event_dict["event"], str):
            event_dict["event"] = sanitize_log_message(event_dict["event"])
        return event_dict

    # Shared processors for all loggers
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _sanitize_processor,
        structlog.processors.UnicodeDecoder(),
    ]
    
    # Console renderer
    console_processor = structlog.dev.ConsoleRenderer()
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.app.log_level.upper())
    )
    
    # Configure structlog
    structlog.configure(
        processors=shared_processors + [console_processor],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False
    )
    
    # Set up logging context
    structlog.contextvars.clear_contextvars()

# Configure logging
configure_logging()
logger = structlog.get_logger()


class ProxyMistral:
    """Main application class."""

    def __init__(self):
        self.transport: Optional[MeetingBaaSTransport] = None
        self.pipeline: Optional[MeetingPipeline] = None

    async def join_meeting(self, meeting_url: str, bot_name: str = "ProxyBot", bot_image: str = "") -> None:
        """Join a meeting."""
        try:
            logger.info(f"Starting proxy mistral...")

            # Initialize transport
            self.transport = MeetingBaaSTransport()

            # Join meeting
            image = bot_image or settings.meeting_baas.bot_image
            meeting_info = await self.transport.join_meeting(meeting_url, bot_name, bot_image=image)
            logger.info(f"Joined meeting: {meeting_info}")
            
            # Initialize pipeline
            self.pipeline = MeetingPipeline(self.transport, meeting_url=meeting_url, bot_name=bot_name)
            await self.pipeline.setup()

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
    load_dotenv()

    from src.agent.context_manager import DocumentContextManager

    ctx = DocumentContextManager()
    history = asyncio.run(_get_status(ctx))
    if not history:
        click.echo("No meeting history found.")
        return
    click.echo(f"Recent meetings ({len(history)}):")
    for m in history:
        click.echo(f"  [{m['created_at']}] {m['title']} — {m['summary'][:80]}...")


async def _get_status(ctx):
    return await ctx.get_meeting_history(limit=5)


@cli.command("auth-calendar")
def auth_calendar() -> None:
    """Perform Google Calendar OAuth and output token for production use."""
    load_dotenv()

    from src.integrations.google_calendar import GoogleCalendarIntegration

    cal = GoogleCalendarIntegration()
    if cal.is_authenticated():
        click.echo("Google Calendar authentication successful!")

        token_path = os.path.join(settings.app.data_dir, "google_calendar_token.json")
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                token_data = f.read()
            click.echo(f"\nToken saved to: {token_path}")
            click.echo("\nFor Kubernetes, create a secret with:")
            click.echo(
                f"  kubectl create secret generic proxy-mistral-secrets \\\n"
                f"    --from-literal=google_calendar_credentials='{token_data}'"
            )
    else:
        click.echo("Authentication failed.", err=True)
        sys.exit(1)


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind")
@click.option("--port", default=8000, type=int, help="Port to bind")
def serve(host: str, port: int) -> None:
    """Start API server with calendar scheduler."""
    load_dotenv()
    import uvicorn

    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        log_level=settings.app.log_level.lower(),
    )


if __name__ == "__main__":
    cli()