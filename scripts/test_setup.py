#!/usr/bin/env python3
"""
Test script to verify basic setup and configuration.
"""

import asyncio
import logging
from dotenv import load_dotenv

from src.config.settings import settings
from src.meeting.transports.meetingbaas import MeetingBaaSTransport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_config():
    """Test configuration loading."""
    logger.info("Testing configuration...")
    logger.info(f"Meeting BaaS base URL: {settings.meeting_baas.base_url}")
    logger.info(f"Mistral model: {settings.mistral.model}")
    logger.info(f"ElevenLabs model: {settings.elevenlabs.model}")
    logger.info(f"Log level: {settings.app.log_level}")
    logger.info("✓ Configuration loaded successfully")


async def test_transport():
    """Test transport initialization."""
    logger.info("Testing transport...")
    
    try:
        transport = MeetingBaaSTransport()
        logger.info(f"Transport created: {type(transport).__name__}")
        logger.info(f"API Key present: {bool(settings.meeting_baas.api_key)}")
        logger.info("✓ Transport initialized successfully")
        
    except Exception as e:
        logger.error(f"Transport test failed: {e}")
        raise


def main():
    """Run all tests."""
    load_dotenv()
    
    logger.info("Starting setup test...")
    
    try:
        # Test configuration
        test_config()
        
        # Test transport
        asyncio.run(test_transport())
        
        logger.info("✓ All setup tests passed!")
        
    except Exception as e:
        logger.error(f"Setup test failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())