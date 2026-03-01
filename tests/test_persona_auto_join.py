import asyncio

import pytest

from src.integrations.google_calendar import GoogleCalendarIntegration


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_meeting(summary="Test Meeting", description=""):
    return {
        "id": "test123",
        "summary": summary,
        "description": description,
        "start": "2026-03-01T10:00:00Z",
        "end": "2026-03-01T10:30:00Z",
        "meet_url": "https://meet.google.com/abc-defg-hij",
        "organizer": "test@example.com",
        "attendees": [],
        "status": "confirmed",
    }


class TestDetermineMeetingType:
    """Test meeting type classification from title/description."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Create instance without initializing Google API
        self.cal = GoogleCalendarIntegration.__new__(GoogleCalendarIntegration)
        self.cal.credentials = None
        self.cal.service = None

    def test_standup(self):
        assert self.cal._determine_meeting_type(_make_meeting("Daily Standup")) == "standup"
        assert self.cal._determine_meeting_type(_make_meeting("Team Daily")) == "standup"

    def test_all_hands(self):
        assert self.cal._determine_meeting_type(_make_meeting("Q1 All Hands")) == "all_hands"
        assert self.cal._determine_meeting_type(_make_meeting("All-Hands Meeting")) == "all_hands"

    def test_one_on_one(self):
        assert self.cal._determine_meeting_type(_make_meeting("1:1 with Manager")) == "one_on_one"
        assert self.cal._determine_meeting_type(_make_meeting("One-on-one check-in")) == "one_on_one"
        assert self.cal._determine_meeting_type(_make_meeting("1on1")) == "one_on_one"

    def test_sprint_review(self):
        assert self.cal._determine_meeting_type(_make_meeting("Sprint Review")) == "sprint_review"
        assert self.cal._determine_meeting_type(_make_meeting("Sprint Demo")) == "sprint_review"

    def test_default(self):
        assert self.cal._determine_meeting_type(_make_meeting("Random Meeting")) == "default"
        assert self.cal._determine_meeting_type(_make_meeting("Project Discussion")) == "default"

    def test_missing_fields(self):
        assert self.cal._determine_meeting_type({"summary": "", "description": ""}) == "default"
        assert self.cal._determine_meeting_type({}) == "default"


class TestLoadPersonaSettings:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.cal = GoogleCalendarIntegration.__new__(GoogleCalendarIntegration)
        self.cal.credentials = None
        self.cal.service = None

    def test_load_default_persona(self):
        config = self.cal._load_persona_settings("default")
        assert "auto_join" in config
        assert config["auto_join"]["standup"] is True
        assert config["auto_join"]["all_hands"] is False
        assert config["auto_join"]["one_on_one"] is True

    def test_load_nonexistent_persona_returns_defaults(self):
        config = self.cal._load_persona_settings("nonexistent_persona_xyz")
        assert "auto_join" in config


class TestShouldAutoJoin:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.cal = GoogleCalendarIntegration.__new__(GoogleCalendarIntegration)
        self.cal.credentials = None
        self.cal.service = None

    def test_standup_joins(self):
        assert run(self.cal._should_auto_join(_make_meeting("Daily Standup"), "default")) is True

    def test_all_hands_skips(self):
        assert run(self.cal._should_auto_join(_make_meeting("Q1 All Hands"), "default")) is False

    def test_one_on_one_joins(self):
        assert run(self.cal._should_auto_join(_make_meeting("1:1 with PM"), "default")) is True

    def test_default_skips(self):
        assert run(self.cal._should_auto_join(_make_meeting("Random Meeting"), "default")) is False

    def test_priority_keyword_overrides(self):
        """Meetings with priority keywords in title should auto-join regardless of type."""
        assert run(self.cal._should_auto_join(_make_meeting("Urgent: budget review"), "default")) is True
        assert run(self.cal._should_auto_join(_make_meeting("Important planning session"), "default")) is True
        assert run(self.cal._should_auto_join(_make_meeting("Critical incident response"), "default")) is True
