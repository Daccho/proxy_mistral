import asyncio
import os
import tempfile

import pytest

from src.scheduler.meeting_state import MeetingState, MeetingStateManager


@pytest.fixture
def state_manager(tmp_path):
    """Create a MeetingStateManager with a temp database."""
    db_path = str(tmp_path / "test_context.db")
    return MeetingStateManager(db_path=db_path)


def run(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMeetingStateManager:

    def test_upsert_and_get(self, state_manager):
        run(state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/abc-defg-hij",
            title="Daily Standup",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:15:00",
            state=MeetingState.PENDING,
            meeting_type="standup",
            persona="default",
        ))

        meeting = run(state_manager.get_meeting("evt1"))
        assert meeting is not None
        assert meeting["title"] == "Daily Standup"
        assert meeting["state"] == "pending"
        assert meeting["meeting_type"] == "standup"

    def test_upsert_idempotent(self, state_manager):
        """Upserting the same event twice should update, not duplicate."""
        for title in ["Original Title", "Updated Title"]:
            run(state_manager.upsert_meeting(
                calendar_event_id="evt1",
                meet_url="https://meet.google.com/abc",
                title=title,
                start_time="2026-03-01T10:00:00",
                end_time="2026-03-01T10:15:00",
                state=MeetingState.PENDING,
            ))

        meeting = run(state_manager.get_meeting("evt1"))
        assert meeting["title"] == "Updated Title"

    def test_upsert_does_not_overwrite_active_state(self, state_manager):
        """Upsert should not change state if meeting is already ACTIVE."""
        run(state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/abc",
            title="Meeting",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:15:00",
            state=MeetingState.PENDING,
        ))
        run(state_manager.update_state("evt1", MeetingState.ACTIVE))

        # Upsert again with PENDING — should NOT change from ACTIVE
        run(state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/abc",
            title="Meeting Updated",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:15:00",
            state=MeetingState.PENDING,
        ))

        meeting = run(state_manager.get_meeting("evt1"))
        assert meeting["state"] == "active"

    def test_state_transitions(self, state_manager):
        run(state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/abc",
            title="Meeting",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:15:00",
            state=MeetingState.PENDING,
        ))

        for expected_state in [MeetingState.JOINING, MeetingState.ACTIVE, MeetingState.LEAVING, MeetingState.COMPLETED]:
            run(state_manager.update_state("evt1", expected_state))
            meeting = run(state_manager.get_meeting("evt1"))
            assert meeting["state"] == expected_state.value

    def test_update_state_with_bot_id(self, state_manager):
        run(state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/abc",
            title="Meeting",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:15:00",
            state=MeetingState.JOINING,
        ))

        run(state_manager.update_state("evt1", MeetingState.ACTIVE, bot_id="bot-123"))
        meeting = run(state_manager.get_meeting("evt1"))
        assert meeting["bot_id"] == "bot-123"

    def test_update_state_with_error(self, state_manager):
        run(state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/abc",
            title="Meeting",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:15:00",
            state=MeetingState.JOINING,
        ))

        run(state_manager.update_state("evt1", MeetingState.FAILED, error="Connection refused"))
        meeting = run(state_manager.get_meeting("evt1"))
        assert meeting["state"] == "failed"
        assert meeting["error_message"] == "Connection refused"

    def test_get_meetings_by_state(self, state_manager):
        for i, st in enumerate([MeetingState.PENDING, MeetingState.ACTIVE, MeetingState.PENDING]):
            run(state_manager.upsert_meeting(
                calendar_event_id=f"evt{i}",
                meet_url=f"https://meet.google.com/{i}",
                title=f"Meeting {i}",
                start_time="2026-03-01T10:00:00",
                end_time="2026-03-01T10:15:00",
                state=st,
            ))

        pending = run(state_manager.get_meetings_by_state(MeetingState.PENDING))
        assert len(pending) == 2

        active = run(state_manager.get_meetings_by_state(MeetingState.ACTIVE))
        assert len(active) == 1

    def test_get_active_meeting_count(self, state_manager):
        for i, st in enumerate([MeetingState.JOINING, MeetingState.ACTIVE, MeetingState.COMPLETED]):
            run(state_manager.upsert_meeting(
                calendar_event_id=f"evt{i}",
                meet_url=f"https://meet.google.com/{i}",
                title=f"Meeting {i}",
                start_time="2026-03-01T10:00:00",
                end_time="2026-03-01T10:15:00",
                state=st,
            ))

        count = run(state_manager.get_active_meeting_count())
        assert count == 2  # JOINING + ACTIVE

    def test_get_all_tracked(self, state_manager):
        for i in range(3):
            run(state_manager.upsert_meeting(
                calendar_event_id=f"evt{i}",
                meet_url=f"https://meet.google.com/{i}",
                title=f"Meeting {i}",
                start_time=f"2026-03-0{i+1}T10:00:00",
                end_time=f"2026-03-0{i+1}T10:15:00",
                state=MeetingState.COMPLETED,
            ))

        all_meetings = run(state_manager.get_all_tracked(limit=2))
        assert len(all_meetings) == 2

    def test_get_nonexistent_meeting(self, state_manager):
        meeting = run(state_manager.get_meeting("does-not-exist"))
        assert meeting is None

    def test_cleanup_stale(self, state_manager):
        # Insert a completed meeting
        run(state_manager.upsert_meeting(
            calendar_event_id="old",
            meet_url="https://meet.google.com/old",
            title="Old Meeting",
            start_time="2026-01-01T10:00:00",
            end_time="2026-01-01T10:15:00",
            state=MeetingState.COMPLETED,
        ))

        # Cleanup with 0 hours max age to remove everything
        removed = run(state_manager.cleanup_stale(max_age_hours=0))
        assert removed == 1

        meeting = run(state_manager.get_meeting("old"))
        assert meeting is None
