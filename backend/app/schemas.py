from pydantic import BaseModel, Field
from typing import Any


class CaptureCreate(BaseModel):
    asset_id: str | None = None
    asset_name: str | None = None
    title: str = Field(min_length=1, max_length=200)
    task_description: str = ""
    category: str = "assembly"
    manual_id: str | None = None
    tags: list[str] = []
    notes: str = ""


class TranscriptSave(BaseModel):
    transcript_original: str = ""
    transcript_corrected: str = ""


class EvidenceCreate(BaseModel):
    evidence_type: str = "note"
    text_content: str | None = None
    description: str = ""
    source_reference: str = "manual-entry"


class DraftRequest(BaseModel):
    capture_session_id: str
    manual_excerpt: str = ""


class StepIn(BaseModel):
    title: str
    instruction: str
    expected_result: str | None = None
    required_tools: list[str] = []
    evidence_refs: list[str] = []
    visual_refs: list[str] = []
    verification_notes: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None


class VersionEdit(BaseModel):
    summary: str | None = None
    prerequisites: str | None = None
    steps: list[StepIn] | None = None


class ReviewAction(BaseModel):
    comment: str = ""


class JobCreate(BaseModel):
    procedure_id: str
    procedure_version_id: str
    asset_id: str | None = None
    # Optional stable client-generated id for offline-created jobs. When
    # supplied, job creation is idempotent on this id so queued events
    # referencing it can sync after reconnect.
    id: str | None = None
    # Optional offline execution grant (see POST
    # /api/procedure-versions/{vid}/offline-grant). Allows an offline job
    # started against an approved revision to register after that revision
    # was superseded. Ignored when the version is still approved.
    offline_grant: str | None = None


class JobEventIn(BaseModel):
    event_id: str
    session_id: str
    step_id: str | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str | None = None


class SyncRequest(BaseModel):
    events: list[JobEventIn] = []


class FinishJob(BaseModel):
    outcome: str = "completed"
    reason: str = ""
    summary: str = ""


class FinishExceptional(BaseModel):
    reason: str = ""


class FinalizeJob(BaseModel):
    """One-shot final step completion + job finalization.

    step_id must belong to the job's pinned procedure revision. event_id
    makes retries idempotent: re-sending the same finalization never
    duplicates the step event or the finish. The server computes the
    outcome (completed vs completed-with-exceptions) and ignores any
    client-supplied outcome.
    """
    step_id: str
    event_id: str
    occurred_at: str | None = None
    reason: str = ""


class SegmentRequest(BaseModel):
    prompt_text: str = Field(default="", max_length=200)
    prompt_nx: float | None = Field(default=None, ge=0.0, le=1.0)
    prompt_ny: float | None = Field(default=None, ge=0.0, le=1.0)


class AskRequest(BaseModel):
    question: str
    procedure_version_id: str | None = None
    manual_id: str | None = None
