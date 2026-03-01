import enum
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.config.settings import settings

logger = logging.getLogger(__name__)


class MeetingState(str, enum.Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    JOINING = "joining"
    ACTIVE = "active"
    LEAVING = "leaving"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class MeetingStateManager:
    """SQLite-backed meeting lifecycle tracker.

    Uses the same context.db as DocumentContextManager to keep
    all application state in one place.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(Path(settings.app.data_dir) / "context.db")
        self._initialize_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_tables(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_meetings (
                    calendar_event_id TEXT PRIMARY KEY,
                    meet_url TEXT NOT NULL,
                    title TEXT,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    bot_id TEXT,
                    persona TEXT,
                    meeting_type TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
            logger.info("MeetingStateManager initialized")
        finally:
            conn.close()

    async def upsert_meeting(
        self,
        calendar_event_id: str,
        meet_url: str,
        title: str,
        start_time: str,
        end_time: str,
        state: MeetingState,
        meeting_type: str = "default",
        persona: str = "default",
    ) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO scheduled_meetings
                    (calendar_event_id, meet_url, title, start_time, end_time, state, meeting_type, persona, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(calendar_event_id) DO UPDATE SET
                    meet_url = excluded.meet_url,
                    title = excluded.title,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    state = CASE
                        WHEN scheduled_meetings.state IN ('completed', 'active', 'joining', 'leaving')
                        THEN scheduled_meetings.state
                        ELSE excluded.state
                    END,
                    meeting_type = excluded.meeting_type,
                    persona = excluded.persona,
                    updated_at = datetime('now')
                """,
                (calendar_event_id, meet_url, title, start_time, end_time, state.value, meeting_type, persona),
            )
            conn.commit()
        finally:
            conn.close()

    async def update_state(
        self,
        calendar_event_id: str,
        new_state: MeetingState,
        bot_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        conn = self._get_conn()
        try:
            if bot_id:
                conn.execute(
                    "UPDATE scheduled_meetings SET state=?, bot_id=?, updated_at=datetime('now') WHERE calendar_event_id=?",
                    (new_state.value, bot_id, calendar_event_id),
                )
            elif error:
                conn.execute(
                    "UPDATE scheduled_meetings SET state=?, error_message=?, updated_at=datetime('now') WHERE calendar_event_id=?",
                    (new_state.value, error, calendar_event_id),
                )
            else:
                conn.execute(
                    "UPDATE scheduled_meetings SET state=?, updated_at=datetime('now') WHERE calendar_event_id=?",
                    (new_state.value, calendar_event_id),
                )
            conn.commit()
        finally:
            conn.close()

    async def get_meetings_by_state(self, state: MeetingState) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM scheduled_meetings WHERE state=? ORDER BY start_time",
                (state.value,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def get_active_meeting_count(self) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM scheduled_meetings WHERE state IN ('joining', 'active')"
            ).fetchone()
            return row["cnt"]
        finally:
            conn.close()

    async def get_meeting(self, calendar_event_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM scheduled_meetings WHERE calendar_event_id=?",
                (calendar_event_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    async def get_all_tracked(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM scheduled_meetings ORDER BY start_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    async def cleanup_stale(self, max_age_hours: int = 48) -> int:
        conn = self._get_conn()
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
            cursor = conn.execute(
                "DELETE FROM scheduled_meetings WHERE state IN ('completed', 'failed', 'skipped', 'cancelled') AND updated_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
