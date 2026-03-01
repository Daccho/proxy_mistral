import logging
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import Depends, FastAPI, HTTPException, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config.settings import settings
from src.agent.context_manager import DocumentContextManager
from src.agent.summarizer import MeetingSummarizer
from src.api.models import (
    DocumentUploadRequest,
    DocumentSearchRequest,
    MeetingSummaryRequest,
    ExportSummaryRequest,
    MeetingHistoryRequest,
    ManualJoinRequest,
)
from src.security.auth import verify_api_key
from src.security.rate_limiter import rate_limit_dependency
from src.security.audit import log_api_access

logger = logging.getLogger(__name__)

# --- Scheduler singleton (accessible from endpoints) ---
_scheduler = None


def get_scheduler():
    return _scheduler


# --- Lifespan: start/stop scheduler alongside API ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    if settings.scheduler.enabled:
        from src.scheduler.scheduler import MeetingScheduler

        _scheduler = MeetingScheduler()
        await _scheduler.start()
        logger.info("Scheduler started alongside API server")
    yield
    if _scheduler:
        await _scheduler.stop()
        _scheduler = None
        logger.info("Scheduler stopped")


# --- App creation (A05: disable docs in production) ---
_is_production = settings.app.environment == "production"

app = FastAPI(
    title="Proxy Mistral API",
    description="REST API for Meeting Proxy Agent",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/api/docs",
    redoc_url=None if _is_production else "/api/redoc",
    openapi_url=None if _is_production else "/api/openapi.json",
)

# --- CORS (A05: restrict origins) ---
_allowed_origins = (
    [o.strip() for o in settings.security.allowed_origins.split(",") if o.strip()]
    if settings.security.allowed_origins
    else ["http://localhost:3000"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# --- Audit middleware (A09: security logging) ---
from starlette.middleware.base import BaseHTTPMiddleware


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        log_api_access(
            endpoint=str(request.url.path),
            client_ip=request.client.host if request.client else "unknown",
            api_key_prefix=request.headers.get("X-API-Key", ""),
            status=response.status_code,
        )
        return response


app.add_middleware(AuditMiddleware)


# --- Global exception handler (A02/LLM02: don't leak internals) ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = uuid.uuid4().hex[:8]
    logger.error(f"[{error_id}] Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal error. Reference: {error_id}"},
    )


# --- Router with rate limiting (A04/LLM10) ---
api_router = APIRouter(prefix="/api", dependencies=[Depends(rate_limit_dependency)])

# Initialize components
context_manager = DocumentContextManager()
summarizer = MeetingSummarizer(
    api_key=settings.mistral.api_key,
    context_manager=context_manager,
)


def _error_response(context: str, exc: Exception) -> HTTPException:
    """Create a safe error response that does not leak internals."""
    error_id = uuid.uuid4().hex[:8]
    logger.error(f"[{error_id}] {context}: {exc}", exc_info=True)
    return HTTPException(status_code=500, detail=f"Internal error. Reference: {error_id}")


# --- Health check (no auth — used by K8s probes) ---
@api_router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    sched = get_scheduler()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "service": "proxy-mistral-api",
        "scheduler_enabled": settings.scheduler.enabled,
        "scheduler_running": sched.is_running if sched else False,
        "active_meetings": sched.active_meeting_count if sched else 0,
    }


# --- Document endpoints (A01: require API key) ---
@api_router.post("/documents/upload")
async def upload_document(
    request: DocumentUploadRequest,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Upload a document to the context manager."""
    try:
        await context_manager.add_document(
            request.document_id, request.title, request.content, request.metadata
        )
        return {
            "success": True,
            "document_id": request.document_id,
            "message": "Document uploaded successfully",
        }
    except Exception as e:
        raise _error_response("Failed to upload document", e)


@api_router.get("/documents/search")
async def search_documents(
    params: DocumentSearchRequest = Depends(),
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Search documents using RAG."""
    try:
        results = await context_manager.search_documents(params.query, params.limit)
        context = await context_manager.get_relevant_context(params.query, params.meeting_type)
        return {
            "success": True,
            "results": results,
            "context": context,
            "count": len(results),
        }
    except Exception as e:
        raise _error_response("Failed to search documents", e)


@api_router.get("/documents")
async def list_documents(
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """List all uploaded documents."""
    try:
        return {"success": True, "documents": [], "count": 0}
    except Exception as e:
        raise _error_response("Failed to list documents", e)


# --- Meeting endpoints (A01: require API key) ---
@api_router.post("/meetings/{meeting_id}/summary")
async def generate_summary(
    meeting_id: str,
    request: MeetingSummaryRequest,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Generate meeting summary."""
    try:
        summary = await summarizer.generate_summary(
            meeting_id=meeting_id,
            title=request.title,
            transcript=request.transcript,
            participants=request.participants,
            meeting_type=request.meeting_type,
        )
        return {"success": True, "summary": summary}
    except Exception as e:
        raise _error_response("Failed to generate summary", e)


@api_router.get("/meetings/history")
async def get_meeting_history(
    params: MeetingHistoryRequest = Depends(),
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Get recent meeting history."""
    try:
        history = await summarizer.get_meeting_history(params.limit)
        return {"success": True, "history": history, "count": len(history)}
    except Exception as e:
        raise _error_response("Failed to get meeting history", e)


@api_router.get("/meetings/{meeting_id}/summary")
async def get_meeting_summary(
    meeting_id: str,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Get a specific meeting summary."""
    try:
        return {
            "success": True,
            "summary": {
                "meeting_id": meeting_id,
                "title": "Example Meeting",
                "executive_summary": "This is a sample summary.",
                "action_items": [],
                "decisions": [],
                "deferred_items": [],
                "questions_unanswered": [],
            },
        }
    except Exception as e:
        raise _error_response("Failed to get meeting summary", e)


@api_router.post("/meetings/{meeting_id}/summary/export")
async def export_summary(
    meeting_id: str,
    request: ExportSummaryRequest,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Export meeting summary in specified format."""
    try:
        summary = {
            "meeting_id": meeting_id,
            "title": "Example Meeting",
            "executive_summary": "This is a sample summary.",
        }
        exported = await summarizer.export_summary(summary, request.format)
        return {"success": True, "format": request.format, "content": exported}
    except Exception as e:
        raise _error_response("Failed to export summary", e)


# --- Calendar / Scheduler endpoints (A01: require API key) ---

@api_router.get("/calendar/upcoming")
async def get_upcoming_meetings(
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Get upcoming Google Calendar meetings with auto-join decisions."""
    sched = get_scheduler()
    if not sched or not sched._calendar:
        raise HTTPException(status_code=503, detail="Calendar not available")
    try:
        meetings = await sched._calendar.get_upcoming_meetings()
        persona = settings.scheduler.default_persona
        enriched = []
        for m in meetings:
            meeting_type = sched._calendar._determine_meeting_type(m)
            auto_join = await sched._calendar._should_auto_join(m, persona)
            enriched.append({
                "id": m["id"],
                "summary": m["summary"],
                "start": m["start"],
                "end": m["end"],
                "meet_url": m["meet_url"],
                "organizer": m.get("organizer", ""),
                "meeting_type": meeting_type,
                "auto_join": auto_join,
            })
        return {"success": True, "meetings": enriched, "count": len(enriched)}
    except Exception as e:
        raise _error_response("Failed to get upcoming meetings", e)


@api_router.get("/calendar/scheduled")
async def get_scheduled_meetings(
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Get all tracked meetings and their states."""
    sched = get_scheduler()
    if not sched:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        from src.scheduler.meeting_state import MeetingStateManager
        state_mgr = MeetingStateManager()
        meetings = await state_mgr.get_all_tracked()
        return {"success": True, "meetings": meetings, "count": len(meetings)}
    except Exception as e:
        raise _error_response("Failed to get scheduled meetings", e)


@api_router.post("/calendar/meetings/{event_id}/join")
async def force_join_meeting(
    event_id: str,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Force-join a specific calendar meeting."""
    sched = get_scheduler()
    if not sched:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        success = await sched.force_join(event_id)
        if not success:
            raise HTTPException(status_code=404, detail="Meeting not found in tracker")
        return {"success": True, "message": f"Joining meeting {event_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise _error_response("Failed to force join meeting", e)


@api_router.post("/calendar/meetings/{event_id}/skip")
async def skip_meeting(
    event_id: str,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Mark a meeting as skipped."""
    sched = get_scheduler()
    if not sched:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        success = await sched.force_skip(event_id)
        if not success:
            raise HTTPException(status_code=404, detail="Meeting not found in tracker")
        return {"success": True, "message": f"Skipped meeting {event_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise _error_response("Failed to skip meeting", e)


@api_router.post("/meetings/join")
async def manual_join(
    request: ManualJoinRequest,
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Join a meeting by URL (not from calendar)."""
    sched = get_scheduler()
    if not sched:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        tracking_id = await sched.manual_join(request.meeting_url, request.bot_name)
        return {"success": True, "tracking_id": tracking_id, "message": "Joining meeting"}
    except Exception as e:
        raise _error_response("Failed to join meeting", e)


@api_router.get("/scheduler/status")
async def scheduler_status(
    _api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Get scheduler status."""
    sched = get_scheduler()
    if not sched:
        return {
            "success": True,
            "enabled": settings.scheduler.enabled,
            "running": False,
            "calendar_connected": False,
            "active_meetings": 0,
            "config": {
                "poll_interval_minutes": settings.google_calendar.poll_interval_minutes,
                "lookahead_minutes": settings.google_calendar.lookahead_minutes,
                "max_concurrent_meetings": settings.scheduler.max_concurrent_meetings,
                "join_before_start_minutes": settings.scheduler.join_before_start_minutes,
                "auto_leave_after_end_minutes": settings.scheduler.auto_leave_after_end_minutes,
            },
        }
    return {
        "success": True,
        "enabled": True,
        "running": sched.is_running,
        "calendar_connected": sched._calendar is not None,
        "active_meetings": sched.active_meeting_count,
        "config": {
            "poll_interval_minutes": settings.google_calendar.poll_interval_minutes,
            "lookahead_minutes": settings.google_calendar.lookahead_minutes,
            "max_concurrent_meetings": settings.scheduler.max_concurrent_meetings,
            "join_before_start_minutes": settings.scheduler.join_before_start_minutes,
            "auto_leave_after_end_minutes": settings.scheduler.auto_leave_after_end_minutes,
        },
    }


# Include the router
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.app.log_level.lower(),
        reload=True,
    )
