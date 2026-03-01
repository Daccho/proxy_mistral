import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config.settings import settings
from src.integrations.google_calendar import GoogleCalendarIntegration
from src.main import ProxyMistral
from src.scheduler.meeting_state import MeetingState, MeetingStateManager

logger = logging.getLogger(__name__)


class MeetingScheduler:
    """Polls Google Calendar and auto-joins meetings based on persona rules.

    Runs alongside FastAPI via its lifespan hook, sharing the same event loop.
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._state_manager = MeetingStateManager()
        self._calendar: Optional[GoogleCalendarIntegration] = None
        self._active_meetings: Dict[str, ProxyMistral] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Initialize calendar client and start polling jobs."""
        try:
            self._calendar = GoogleCalendarIntegration()
        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar: {e}")
            logger.warning("Scheduler starting without calendar — manual join only")
            self._calendar = None

        poll_minutes = settings.google_calendar.poll_interval_minutes

        if self._calendar:
            self._scheduler.add_job(
                self._poll_calendar,
                IntervalTrigger(minutes=poll_minutes),
                id="calendar_poll",
                name="Poll Google Calendar",
                replace_existing=True,
                next_run_time=datetime.utcnow(),  # run immediately on start
            )

        self._scheduler.add_job(
            self._check_meeting_endings,
            IntervalTrigger(minutes=1),
            id="meeting_end_check",
            name="Check for meetings to leave",
            replace_existing=True,
        )

        self._scheduler.add_job(
            self._cleanup_stale,
            IntervalTrigger(hours=6),
            id="stale_cleanup",
            name="Clean up old meeting records",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "MeetingScheduler started (poll_interval=%dm, calendar=%s)",
            poll_minutes,
            "connected" if self._calendar else "unavailable",
        )

    async def stop(self) -> None:
        """Leave all active meetings and shut down."""
        self._scheduler.shutdown(wait=False)

        for event_id, proxy in list(self._active_meetings.items()):
            try:
                await self._state_manager.update_state(event_id, MeetingState.LEAVING)
                await proxy.cleanup()
                await self._state_manager.update_state(event_id, MeetingState.COMPLETED)
            except Exception as e:
                logger.error(f"Error stopping meeting {event_id}: {e}")

        self._active_meetings.clear()
        logger.info("MeetingScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._scheduler.running

    @property
    def active_meeting_count(self) -> int:
        return len(self._active_meetings)

    async def _poll_calendar(self) -> None:
        """Fetch upcoming meetings and evaluate auto-join rules."""
        if not self._calendar:
            return

        async with self._lock:
            try:
                meetings = await self._calendar.get_upcoming_meetings()
            except Exception as e:
                logger.error(f"Calendar poll failed: {e}")
                return

            now = datetime.utcnow()
            persona = settings.scheduler.default_persona
            lookahead = timedelta(minutes=settings.google_calendar.lookahead_minutes)
            join_early = timedelta(minutes=settings.scheduler.join_before_start_minutes)

            for meeting in meetings:
                event_id = meeting["id"]

                # Skip already processed meetings
                existing = await self._state_manager.get_meeting(event_id)
                if existing and existing["state"] not in (
                    MeetingState.PENDING.value,
                    MeetingState.SKIPPED.value,
                ):
                    continue

                # Parse times
                try:
                    start_time = datetime.fromisoformat(meeting["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                    end_time = datetime.fromisoformat(meeting["end"].replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Cannot parse time for event {event_id}: {e}")
                    continue

                # Only consider meetings within lookahead window
                if start_time > now + lookahead:
                    continue

                # Already past
                if now > end_time:
                    continue

                # Evaluate auto-join rules
                meeting_type = self._calendar._determine_meeting_type(meeting)
                should_join = await self._calendar._should_auto_join(meeting, persona)

                state = MeetingState.PENDING if should_join else MeetingState.SKIPPED
                await self._state_manager.upsert_meeting(
                    calendar_event_id=event_id,
                    meet_url=meeting["meet_url"],
                    title=meeting["summary"],
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    state=state,
                    meeting_type=meeting_type,
                    persona=persona,
                )

                # Join if within the join window
                if should_join and now >= (start_time - join_early):
                    await self._join_meeting(event_id, meeting)

            logger.debug("Calendar poll complete, %d active meetings", len(self._active_meetings))

    async def _join_meeting(self, event_id: str, meeting: Dict) -> None:
        """Join a single meeting via MeetingBaaS."""
        active_count = await self._state_manager.get_active_meeting_count()
        if active_count >= settings.scheduler.max_concurrent_meetings:
            logger.warning("Max concurrent meetings (%d) reached, skipping: %s",
                           settings.scheduler.max_concurrent_meetings, meeting.get("summary"))
            return

        await self._state_manager.update_state(event_id, MeetingState.JOINING)

        try:
            proxy = ProxyMistral()
            self._active_meetings[event_id] = proxy
            asyncio.create_task(self._run_meeting(event_id, proxy, meeting["meet_url"]))
            logger.info("Joining meeting: %s (%s)", meeting.get("summary"), meeting["meet_url"])
        except Exception as e:
            logger.error(f"Failed to start join for {event_id}: {e}")
            await self._state_manager.update_state(event_id, MeetingState.FAILED, error=str(e))
            self._active_meetings.pop(event_id, None)

    async def _run_meeting(self, event_id: str, proxy: ProxyMistral, meet_url: str) -> None:
        """Run a meeting session as a background task."""
        try:
            await self._state_manager.update_state(event_id, MeetingState.ACTIVE)
            bot_name = settings.scheduler.default_persona
            await proxy.join_meeting(meet_url, bot_name=bot_name, bot_image=settings.meeting_baas.bot_image)
        except Exception as e:
            logger.error(f"Meeting {event_id} error: {e}")
            await self._state_manager.update_state(event_id, MeetingState.FAILED, error=str(e))
        else:
            await self._state_manager.update_state(event_id, MeetingState.COMPLETED)
        finally:
            self._active_meetings.pop(event_id, None)

    async def _check_meeting_endings(self) -> None:
        """Leave meetings that have exceeded end_time + grace period."""
        active = await self._state_manager.get_meetings_by_state(MeetingState.ACTIVE)
        now = datetime.utcnow()
        grace = timedelta(minutes=settings.scheduler.auto_leave_after_end_minutes)

        for meeting in active:
            try:
                end_time = datetime.fromisoformat(meeting["end_time"])
            except (ValueError, KeyError):
                continue

            if now > end_time + grace:
                event_id = meeting["calendar_event_id"]
                proxy = self._active_meetings.get(event_id)
                if proxy:
                    logger.info("Auto-leaving meeting: %s (past end + %dm grace)",
                                meeting.get("title"), settings.scheduler.auto_leave_after_end_minutes)
                    await self._state_manager.update_state(event_id, MeetingState.LEAVING)
                    try:
                        await proxy.cleanup()
                    except Exception as e:
                        logger.error(f"Error leaving meeting {event_id}: {e}")
                    await self._state_manager.update_state(event_id, MeetingState.COMPLETED)
                    self._active_meetings.pop(event_id, None)

    async def _cleanup_stale(self) -> None:
        """Remove old completed/failed meeting records."""
        removed = await self._state_manager.cleanup_stale(max_age_hours=48)
        if removed:
            logger.info("Cleaned up %d stale meeting records", removed)

    async def force_join(self, event_id: str) -> bool:
        """Force-join a meeting by calendar event ID (API-triggered)."""
        meeting = await self._state_manager.get_meeting(event_id)
        if not meeting:
            return False

        await self._join_meeting(
            event_id,
            {"meet_url": meeting["meet_url"], "summary": meeting.get("title", "")},
        )
        return True

    async def force_skip(self, event_id: str) -> bool:
        """Mark a meeting as skipped (API-triggered)."""
        meeting = await self._state_manager.get_meeting(event_id)
        if not meeting:
            return False
        await self._state_manager.update_state(event_id, MeetingState.SKIPPED)
        return True

    async def manual_join(self, meeting_url: str, bot_name: str = "ProxyBot") -> str:
        """Join a meeting by URL (not from calendar). Returns a tracking ID."""
        import uuid

        event_id = f"manual-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()
        await self._state_manager.upsert_meeting(
            calendar_event_id=event_id,
            meet_url=meeting_url,
            title=f"Manual: {meeting_url}",
            start_time=now.isoformat(),
            end_time=(now + timedelta(hours=2)).isoformat(),
            state=MeetingState.PENDING,
            meeting_type="manual",
            persona=settings.scheduler.default_persona,
        )
        await self._join_meeting(event_id, {"meet_url": meeting_url, "summary": "Manual join"})
        return event_id
