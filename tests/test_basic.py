import pytest
from src.config.settings import settings
from src.meeting.transports.meetingbaas import MeetingBaaSTransport


def test_config_loading():
    """Test that configuration loads correctly."""
    assert settings.meeting_baas.base_url == "https://api.meetingbaas.com/v1"
    assert settings.mistral.model == "mistral-medium-2505"
    assert settings.elevenlabs.model == "eleven_turbo_v2_5"
    assert settings.app.log_level == "INFO"


def test_transport_initialization():
    """Test that transport can be initialized."""
    transport = MeetingBaaSTransport()
    assert transport is not None
    assert transport.api_key == settings.meeting_baas.api_key
    assert transport.base_url == settings.meeting_baas.base_url
    assert transport.websocket is None
    assert transport.meeting_id is None


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])