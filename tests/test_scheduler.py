import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scheduler.meeting_state import MeetingState, MeetingStateManager
from src.scheduler.scheduler import MeetingScheduler


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_calendar_meeting(event_id="evt1", summary="Daily Standup",
                           start_offset_minutes=5, duration_minutes=30):
    """Create a fake calendar meeting starting `start_offset_minutes` from now."""
    now = datetime.utcnow()
    start = now + timedelta(minutes=start_offset_minutes)
    end = start + timedelta(minutes=duration_minutes)
    return {
        "id": event_id,
        "summary": summary,
        "description": "",
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "meet_url": f"https://meet.google.com/{event_id}",
        "organizer": "test@example.com",
        "attendees": [],
        "status": "confirmed",
    }


class TestSchedulerPoll:

    @pytest.fixture
    def scheduler(self, tmp_path):
        sched = MeetingScheduler()
        sched._state_manager = MeetingStateManager(db_path=str(tmp_path / "test.db"))
        # Mock calendar
        sched._calendar = MagicMock()
        sched._calendar.get_upcoming_meetings = AsyncMock(return_value=[])
        sched._calendar._determine_meeting_type = MagicMock(return_value="standup")
        sched._calendar._should_auto_join = AsyncMock(return_value=True)
        return sched

    def test_poll_empty_calendar(self, scheduler):
        """Poll with no upcoming meetings should be a no-op."""
        run(scheduler._poll_calendar())
        assert scheduler.active_meeting_count == 0

    @patch("src.scheduler.scheduler.ProxyMistral")
    def test_poll_detects_and_joins_meeting(self, mock_proxy_class, scheduler):
        """A standup within join window should be auto-joined."""
        meeting = _make_calendar_meeting(start_offset_minutes=1)
        scheduler._calendar.get_upcoming_meetings = AsyncMock(return_value=[meeting])

        mock_proxy = MagicMock()
        mock_proxy.join_meeting = AsyncMock()
        mock_proxy.cleanup = AsyncMock()
        mock_proxy_class.return_value = mock_proxy

        run(scheduler._poll_calendar())

        # Should have created a meeting record and attempted to join
        record = run(scheduler._state_manager.get_meeting("evt1"))
        assert record is not None
        # Mock join completes instantly so task finishes during poll;
        # state can be joining, active, or completed depending on timing
        assert record["state"] in ("joining", "active", "completed")
        mock_proxy_class.assert_called_once()

    def test_poll_skips_meeting_when_auto_join_false(self, scheduler):
        """A meeting that fails auto-join rules should be SKIPPED."""
        meeting = _make_calendar_meeting(start_offset_minutes=1, summary="Random Chat")
        scheduler._calendar.get_upcoming_meetings = AsyncMock(return_value=[meeting])
        scheduler._calendar._should_auto_join = AsyncMock(return_value=False)

        run(scheduler._poll_calendar())

        record = run(scheduler._state_manager.get_meeting("evt1"))
        assert record is not None
        assert record["state"] == "skipped"

    def test_poll_skips_already_active_meeting(self, scheduler):
        """A meeting already ACTIVE should not be re-joined."""
        run(scheduler._state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/evt1",
            title="Already Active",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:30:00",
            state=MeetingState.ACTIVE,
        ))

        meeting = _make_calendar_meeting(start_offset_minutes=1)
        scheduler._calendar.get_upcoming_meetings = AsyncMock(return_value=[meeting])

        run(scheduler._poll_calendar())
        # Should not create a duplicate
        assert scheduler.active_meeting_count == 0  # No ProxyMistral instance added

    def test_poll_respects_max_concurrent(self, scheduler):
        """Should not join if max concurrent meetings reached."""
        # Pre-fill with an active meeting
        run(scheduler._state_manager.upsert_meeting(
            calendar_event_id="existing",
            meet_url="https://meet.google.com/existing",
            title="Existing",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:30:00",
            state=MeetingState.ACTIVE,
        ))

        meeting = _make_calendar_meeting(event_id="new", start_offset_minutes=1)
        scheduler._calendar.get_upcoming_meetings = AsyncMock(return_value=[meeting])

        run(scheduler._poll_calendar())

        new_record = run(scheduler._state_manager.get_meeting("new"))
        # Meeting should be tracked as PENDING but not joined (max_concurrent=1)
        assert new_record is not None
        assert new_record["state"] == "pending"


class TestSchedulerMeetingEndings:

    @pytest.fixture
    def scheduler(self, tmp_path):
        sched = MeetingScheduler()
        sched._state_manager = MeetingStateManager(db_path=str(tmp_path / "test.db"))
        return sched

    def test_auto_leave_past_end_time(self, scheduler):
        """Meetings past end_time + grace should be auto-left."""
        past = datetime.utcnow() - timedelta(minutes=10)
        run(scheduler._state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/evt1",
            title="Past Meeting",
            start_time=(past - timedelta(minutes=30)).isoformat(),
            end_time=past.isoformat(),
            state=MeetingState.ACTIVE,
        ))

        mock_proxy = MagicMock()
        mock_proxy.cleanup = AsyncMock()
        scheduler._active_meetings["evt1"] = mock_proxy

        run(scheduler._check_meeting_endings())

        record = run(scheduler._state_manager.get_meeting("evt1"))
        assert record["state"] == "completed"
        assert "evt1" not in scheduler._active_meetings
        mock_proxy.cleanup.assert_called_once()

    def test_no_leave_if_within_grace(self, scheduler):
        """Meetings still within grace period should NOT be left."""
        recent_end = datetime.utcnow() - timedelta(minutes=1)  # grace is 5 min
        run(scheduler._state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/evt1",
            title="Recent Meeting",
            start_time=(recent_end - timedelta(minutes=30)).isoformat(),
            end_time=recent_end.isoformat(),
            state=MeetingState.ACTIVE,
        ))

        mock_proxy = MagicMock()
        scheduler._active_meetings["evt1"] = mock_proxy

        run(scheduler._check_meeting_endings())

        record = run(scheduler._state_manager.get_meeting("evt1"))
        assert record["state"] == "active"  # unchanged


class TestSchedulerForceActions:

    @pytest.fixture
    def scheduler(self, tmp_path):
        sched = MeetingScheduler()
        sched._state_manager = MeetingStateManager(db_path=str(tmp_path / "test.db"))
        return sched

    def test_force_skip(self, scheduler):
        run(scheduler._state_manager.upsert_meeting(
            calendar_event_id="evt1",
            meet_url="https://meet.google.com/evt1",
            title="Meeting",
            start_time="2026-03-01T10:00:00",
            end_time="2026-03-01T10:30:00",
            state=MeetingState.PENDING,
        ))

        success = run(scheduler.force_skip("evt1"))
        assert success is True

        record = run(scheduler._state_manager.get_meeting("evt1"))
        assert record["state"] == "skipped"

    def test_force_skip_nonexistent(self, scheduler):
        success = run(scheduler.force_skip("nonexistent"))
        assert success is False

    @patch("src.scheduler.scheduler.ProxyMistral")
    def test_manual_join(self, mock_proxy_class, scheduler):
        mock_proxy = MagicMock()
        mock_proxy.join_meeting = AsyncMock()
        mock_proxy_class.return_value = mock_proxy

        tracking_id = run(scheduler.manual_join("https://meet.google.com/test"))
        assert tracking_id.startswith("manual-")

        record = run(scheduler._state_manager.get_meeting(tracking_id))
        assert record is not None
