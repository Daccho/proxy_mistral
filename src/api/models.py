"""Pydantic request validation models for API endpoints.

Addresses: OWASP A03 (Injection), A04 (Insecure Design)
"""

from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field, field_validator


class DocumentUploadRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=100_000)
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("content")
    @classmethod
    def validate_content_byte_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 100_000:
            raise ValueError("Content exceeds 100KB limit")
        return v


class DocumentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)
    meeting_type: str = Field(default="default", max_length=50)


class MeetingSummaryRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    transcript: List[Dict[str, Any]] = Field(...)
    participants: List[str] = Field(...)
    meeting_type: str = Field(default="default", max_length=50)

    @field_validator("transcript")
    @classmethod
    def validate_transcript_length(cls, v: List) -> List:
        if len(v) > 10_000:
            raise ValueError("Transcript exceeds 10,000 entries")
        return v

    @field_validator("participants")
    @classmethod
    def validate_participants_length(cls, v: List) -> List:
        if len(v) > 100:
            raise ValueError("Participants list exceeds 100 entries")
        return v


class ExportSummaryRequest(BaseModel):
    format: str = Field(default="json", pattern=r"^(json|markdown)$")


class MeetingHistoryRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)


# --- Calendar / Scheduler models ---

class ManualJoinRequest(BaseModel):
    meeting_url: str = Field(..., min_length=10, max_length=500)
    bot_name: str = Field(default="ProxyBot", max_length=50)
