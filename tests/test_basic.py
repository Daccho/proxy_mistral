import pytest
from src.config.settings import settings
from src.meeting.transports.meetingbaas import MeetingBaaSTransport


def test_config_loading():
    """Test that configuration loads correctly."""
    assert settings.meeting_baas.base_url == "https://api.meetingbaas.com"
    assert settings.mistral.model == "mistral-medium-2505"
    assert settings.elevenlabs.model == "eleven_flash_v2_5"
    assert settings.app.log_level == "INFO"


def test_transport_initialization():
    """Test that transport can be initialized."""
    transport = MeetingBaaSTransport()
    assert transport is not None
    assert transport.api_key == settings.meeting_baas.api_key
    assert transport.base_url == settings.meeting_baas.base_url
    assert transport.bot_id is None


def test_persona_config():
    """Test persona configuration structure."""
    persona = {
        "name": "test",
        "communication_style": {
            "tone": "professional",
            "verbosity": "concise",
            "formality": "semi-formal"
        },
        "rules": ["test rule"]
    }

    assert "name" in persona
    assert "communication_style" in persona
    assert "rules" in persona


def test_google_calendar_settings():
    """Test Google Calendar settings defaults."""
    assert settings.google_calendar.poll_interval_minutes == 5
    assert settings.google_calendar.lookahead_minutes == 15
    assert settings.google_calendar.token_path == "data/google_calendar_token.json"


def test_scheduler_settings():
    """Test scheduler settings defaults."""
    assert settings.scheduler.enabled is True
    assert settings.scheduler.max_concurrent_meetings == 1
    assert settings.scheduler.join_before_start_minutes == 2
    assert settings.scheduler.auto_leave_after_end_minutes == 5
    assert settings.scheduler.default_persona == "default"


def test_transport_public_ws_url():
    """Test transport supports public WebSocket URL for production."""
    transport = MeetingBaaSTransport(public_ws_url="wss://example.com/ws")
    assert transport._public_ws_url == "wss://example.com/ws"

    transport_dev = MeetingBaaSTransport()
    # In dev, public_ws_url is None (empty string from settings becomes None)
    assert transport_dev._public_ws_url is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])