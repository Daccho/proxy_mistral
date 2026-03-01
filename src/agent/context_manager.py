import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config.settings import settings

logger = logging.getLogger(__name__)


class DocumentContextManager:
    """Manages document context and provides FTS5-based search capabilities."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = Path(db_path) if db_path else Path(settings.app.data_dir) / "context.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _initialize_database(self) -> None:
        """Initialize SQLite database with FTS5 for full-text search."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            # Main documents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # FTS5 virtual table for full-text search on documents
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                    title, content, content=documents, content_rowid=rowid
                )
            """)

            # Triggers to keep FTS in sync
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                    INSERT INTO documents_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                    INSERT INTO documents_fts(documents_fts, rowid, title, content) VALUES('delete', old.rowid, old.title, old.content);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                    INSERT INTO documents_fts(documents_fts, rowid, title, content) VALUES('delete', old.rowid, old.title, old.content);
                    INSERT INTO documents_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
                END
            """)

            # Meetings table for cross-meeting context
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meetings (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    summary TEXT,
                    action_items TEXT DEFAULT '[]',
                    decisions TEXT DEFAULT '[]',
                    participants TEXT DEFAULT '[]',
                    meeting_type TEXT DEFAULT 'default',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Transcripts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id TEXT NOT NULL,
                    speaker TEXT,
                    text TEXT NOT NULL,
                    timestamp REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                )
            """)

            conn.commit()
            logger.info("Initialized context database at %s", self._db_path)

    async def add_document(self, document_id: str, title: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a document to the context manager.

        LLM04: Validates content before storage to prevent data poisoning.
        """
        import re as _re
        if len(content) > 100_000:
            raise ValueError("Document content exceeds 100KB limit")
        # Strip script tags to prevent stored XSS if content is ever rendered
        content = _re.sub(r"<script[^>]*>.*?</script>", "", content, flags=_re.DOTALL | _re.IGNORECASE)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, title, content, metadata) VALUES (?, ?, ?, ?)",
                (document_id, title, content, json.dumps(metadata or {})),
            )
            conn.commit()
        logger.info("Added document: %s", title)

    async def search_documents(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search documents using FTS5 full-text search.

        LLM08: Validates query, caps limit, and truncates returned content.
        """
        if not query or len(query.strip()) < 2:
            return []
        limit = min(limit, 20)  # LLM08: cap results

        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                # FTS5 search with BM25 ranking
                cursor.execute("""
                    SELECT d.id, d.title, d.content, d.metadata, rank
                    FROM documents_fts
                    JOIN documents d ON documents_fts.rowid = d.rowid
                    WHERE documents_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": row[0],
                        "title": row[1],
                        "content": row[2][:500] if row[2] else "",  # LLM08: truncate
                        "metadata": json.loads(row[3] or "{}"),
                        "rank": row[4],
                    })
                return results
        except Exception as e:
            logger.error("FTS5 search failed, falling back to LIKE: %s", e)
            return await self._search_documents_fallback(query, limit)

    async def _search_documents_fallback(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Fallback to LIKE search if FTS5 fails.

        LLM08: Escapes SQL wildcards in the query itself.
        """
        # Escape user-supplied wildcards so they are treated as literals
        sanitized = query.replace("%", "\\%").replace("_", "\\_")
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, content, metadata FROM documents "
                "WHERE content LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{sanitized}%", f"%{sanitized}%", limit),
            )
            return [
                {"id": r[0], "title": r[1], "content": (r[2] or "")[:500], "metadata": json.loads(r[3] or "{}")}
                for r in cursor.fetchall()
            ]

    async def get_relevant_context(self, query: str, meeting_type: str = "default") -> str:
        """Get relevant context for the current meeting."""
        documents = await self.search_documents(query)
        past_meetings = await self._get_past_meetings_context(meeting_type)

        context = ""
        if documents:
            context += "Relevant Documents:\n"
            for doc in documents:
                context += f"- {doc['title']}: {doc['content'][:200]}...\n"
            context += "\n"

        if past_meetings:
            context += "Past Meeting Context:\n"
            for meeting in past_meetings:
                summary = meeting.get("summary", "")
                context += f"- {meeting['title']}: {summary[:100]}...\n"
            context += "\n"

        return context if context else "No relevant context found."

    async def _get_past_meetings_context(self, meeting_type: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Get context from past meetings."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT title, summary, action_items, decisions FROM meetings ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [
                {
                    "title": r[0],
                    "summary": r[1] or "",
                    "action_items": json.loads(r[2] or "[]"),
                    "decisions": json.loads(r[3] or "[]"),
                }
                for r in cursor.fetchall()
            ]

    async def save_meeting_summary(
        self,
        meeting_id: str,
        title: str,
        summary: str,
        action_items: List[Dict[str, Any]],
        decisions: List[Dict[str, Any]],
        participants: List[str],
        meeting_type: str = "default",
    ) -> None:
        """Save meeting summary for future context."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO meetings
                   (id, title, summary, action_items, decisions, participants, meeting_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (meeting_id, title, summary, json.dumps(action_items), json.dumps(decisions), json.dumps(participants), meeting_type),
            )
            conn.commit()
        logger.info("Saved meeting summary: %s", title)

    async def save_transcript(self, meeting_id: str, transcript: List[Dict[str, Any]]) -> None:
        """Save meeting transcript to database."""
        with sqlite3.connect(self._db_path) as conn:
            for entry in transcript:
                conn.execute(
                    "INSERT INTO transcripts (meeting_id, speaker, text, timestamp) VALUES (?, ?, ?, ?)",
                    (meeting_id, entry.get("speaker", "unknown"), entry.get("text", ""), entry.get("timestamp")),
                )
            conn.commit()
        logger.info("Saved transcript for meeting %s (%d entries)", meeting_id, len(transcript))

    async def get_meeting_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent meeting history."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, summary, created_at FROM meetings ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [
                {"id": r[0], "title": r[1], "summary": r[2] or "", "created_at": r[3]}
                for r in cursor.fetchall()
            ]

    def cleanup(self) -> None:
        """Optimize and vacuum the database."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("PRAGMA optimize")
            logger.info("Database optimized")
        except Exception as e:
            logger.error("Cleanup error: %s", e)
