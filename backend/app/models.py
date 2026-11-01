import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, JSON, UniqueConstraint, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    asset_type: Mapped[str] = mapped_column(String, default="training-assembly")
    manufacturer: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    serial_or_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Manual(Base):
    __tablename__ = "manuals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    document_version: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    storage_key: Mapped[str] = mapped_column(String, default="")
    mime_type: Mapped[str] = mapped_column(String, default="application/pdf")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String, default="")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String, default="demo-expert")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ManualChunk(Base):
    __tablename__ = "manual_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    manual_id: Mapped[str] = mapped_column(ForeignKey("manuals.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    extraction_status: Mapped[str] = mapped_column(String, default="ok")


class CaptureSession(Base):
    __tablename__ = "capture_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    task_description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String, default="assembly")
    status: Mapped[str] = mapped_column(String, default="draft")
    transcript_original: Mapped[str] = mapped_column(Text, default="")
    transcript_corrected: Mapped[str] = mapped_column(Text, default="")
    manual_id: Mapped[str | None] = mapped_column(ForeignKey("manuals.id"), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String, default="demo-expert")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Procedure(Base):
    __tablename__ = "procedures"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    asset_type: Mapped[str] = mapped_column(String, default="training-assembly")
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="demo-expert")
    favorite: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    versions = relationship("ProcedureVersion", back_populates="procedure", cascade="all, delete-orphan")


class ProcedureVersion(Base):
    __tablename__ = "procedure_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    procedure_id: Mapped[str] = mapped_column(ForeignKey("procedures.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft|pending_review|approved|rejected|superseded
    summary: Mapped[str] = mapped_column(Text, default="")
    prerequisites: Mapped[str] = mapped_column(Text, default="")
    source_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_model: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_simulated: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String, default="demo-expert")
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    procedure = relationship("Procedure", back_populates="versions")
    steps = relationship("ProcedureStep", back_populates="version", cascade="all, delete-orphan", order_by="ProcedureStep.step_order")


class ProcedureStep(Base):
    __tablename__ = "procedure_steps"
    __table_args__ = (UniqueConstraint("procedure_version_id", "step_order"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    procedure_version_id: Mapped[str] = mapped_column(ForeignKey("procedure_versions.id"), nullable=False, index=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_tools: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    visual_refs: Mapped[list] = mapped_column(JSON, default=list)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    version = relationship("ProcedureVersion", back_populates="steps")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    capture_session_id: Mapped[str | None] = mapped_column(ForeignKey("capture_sessions.id"), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String, default="image")  # image|transcript|note
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_by: Mapped[str] = mapped_column(String, default="demo-tech")
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


class SegmentationResult(Base):
    __tablename__ = "segmentation_results"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False, index=True)
    provider_model: Mapped[str] = mapped_column(String, default="sam-3.1")
    prompt_text: Mapped[str] = mapped_column(String, default="")
    normalized_geometry: Mapped[dict] = mapped_column(JSON, default=dict)
    result_status: Mapped[str] = mapped_column(String, default="ok")
    simulated: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    confirmed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobSession(Base):
    __tablename__ = "job_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    procedure_id: Mapped[str] = mapped_column(ForeignKey("procedures.id"), nullable=False)
    procedure_version_id: Mapped[str] = mapped_column(ForeignKey("procedure_versions.id"), nullable=False)
    technician_id: Mapped[str] = mapped_column(String, default="demo-tech")
    status: Mapped[str] = mapped_column(String, default="active")  # active|finished
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("job_sessions.id"), nullable=False, index=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_by: Mapped[str] = mapped_column(String, default="demo-tech")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String, default="system")
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, default="")
    entity_id: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProcessingEvent(Base):
    """Append-only observability timeline for AI/model pipeline stages.

    Summaries and diagnostics only: prompts tried, confidences, counts,
    hashes, durations, error types. Never secrets, auth headers, full raw
    provider payloads, or duplicated video/transcript bytes (those live in
    their own records, linked from here by entity_type/entity_id).
    """
    __tablename__ = "processing_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    correlation_id: Mapped[str] = mapped_column(String, default="", index=True)
    entity_type: Mapped[str] = mapped_column(String, default="", index=True)
    entity_id: Mapped[str] = mapped_column(String, default="", index=True)
    actor: Mapped[str] = mapped_column(String, default="")
    stage: Mapped[str] = mapped_column(String, default="", index=True)
    operation: Mapped[str] = mapped_column(String, default="")
    provider: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="", index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class GuideSnapshot(Base):
    """Immutable per-generation record of a tutorial guide.

    The live guide_markdown on TutorialJob keeps moving (refreshes, tap
    corrections); snapshots preserve what each generation produced, with
    what models, from which objects, and why.
    """
    __tablename__ = "guide_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tutorial_id: Mapped[str] = mapped_column(ForeignKey("tutorial_jobs.id"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String, default="")  # initial|refresh|tap|retry|format
    model: Mapped[str] = mapped_column(String, default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    guide_markdown: Mapped[str] = mapped_column(Text, default="")
    guide_hash: Mapped[str] = mapped_column(String, default="", index=True)
    materials: Mapped[list] = mapped_column(JSON, default=list)
    object_statuses: Mapped[list] = mapped_column(JSON, default=list)
    guide_format: Mapped[str] = mapped_column(String, default="")  # work_instruction|reference_manual|interactive
    format_source: Mapped[str] = mapped_column(String, default="")  # user|recommended
    format_rationale: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class VisualAsset(Base):
    """Every visual has an identity: source pixels, deterministic overlays,
    and AI-generated derivatives are distinct rows linked by parentage.

    kind: source_frame | photo | segmentation | enhanced | annotation |
          illustrative_alternative | user_reference | guide_visual
    status: ready | review | accepted | rejected
    An accepted asset never replaces its source; acceptance only links it.
    """
    __tablename__ = "visual_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tutorial_id: Mapped[str] = mapped_column(String, default="", index=True)
    parent_id: Mapped[str] = mapped_column(String, default="", index=True)
    kind: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="review")
    step_id: Mapped[str] = mapped_column(String, default="")
    version_id: Mapped[str] = mapped_column(String, default="")
    storage_key: Mapped[str] = mapped_column(String, default="")
    mime_type: Mapped[str] = mapped_column(String, default="image/png")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    instruction: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String, default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, default="demo-tech")
    idempotency_key: Mapped[str] = mapped_column(String, default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LiveRecording(Base):
    __tablename__ = "live_recordings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    access_token: Mapped[str] = mapped_column(String, default="")
    actor: Mapped[str] = mapped_column(String, default="demo-tech")
    capture_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active|finished
    transcript: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LiveChunk(Base):
    __tablename__ = "live_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    recording_id: Mapped[str] = mapped_column(ForeignKey("live_recordings.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String, default="")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=6.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    prompt_text: Mapped[str] = mapped_column(String, default="")
    prompt_kind: Mapped[str] = mapped_column(String, default="")
    result_status: Mapped[str] = mapped_column(String, default="ok")
    simulated: Mapped[int] = mapped_column(Integer, default=0)
    segmentation: Mapped[dict] = mapped_column(JSON, default=dict)
    corrected_segmentation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    corrected_prompt: Mapped[str] = mapped_column(String, default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    start_ms: Mapped[int] = mapped_column(Integer, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_source: Mapped[str] = mapped_column(String, default="")
    speech_phrase: Mapped[str] = mapped_column(String, default="")
    review_status: Mapped[str] = mapped_column(String, default="pending")  # pending|verified|needs_correction|incorrect|corrected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class TutorialJob(Base):
    __tablename__ = "tutorial_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    access_token: Mapped[str] = mapped_column(String, default="")
    actor: Mapped[str] = mapped_column(String, default="demo-tech")
    title: Mapped[str] = mapped_column(String, default="Untitled tutorial")
    status: Mapped[str] = mapped_column(String, default="uploaded")  # uploaded|transcribing|understanding|segmenting|illustrating|generating|done|error
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    video_storage_key: Mapped[str] = mapped_column(String, default="")
    video_hash: Mapped[str] = mapped_column(String, default="", index=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    track_width: Mapped[int] = mapped_column(Integer, default=0)
    track_height: Mapped[int] = mapped_column(Integer, default=0)
    full_transcript: Mapped[str] = mapped_column(Text, default="")
    timed_segments: Mapped[list] = mapped_column(JSON, default=list)
    objects: Mapped[list] = mapped_column(JSON, default=list)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    materials: Mapped[list] = mapped_column(JSON, default=list)
    guide_markdown: Mapped[str] = mapped_column(Text, default="")
    guide_format: Mapped[str] = mapped_column(String, default="")
    format_source: Mapped[str] = mapped_column(String, default="")
    format_rationale: Mapped[str] = mapped_column(String, default="")
    draft_procedure_id: Mapped[str] = mapped_column(String, default="")
    draft_version_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class VideoGuide(Base):
    """A rendered MP4 video guide cut from one tutorial.

    Versioned per tutorial like guide snapshots: a new generation never
    overwrites a previous file (storage_key is unique per row). The voiceover
    is the user's own recorded narration, cut per scene with ffmpeg — never
    synthesized, never invented. status: queued|rendering|ready|error.
    """
    __tablename__ = "video_guides"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    tutorial_id: Mapped[str] = mapped_column(String, default="", index=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    asset_id: Mapped[str] = mapped_column(String, default="")
    storage_key: Mapped[str] = mapped_column(String, default="")
    scenes: Mapped[list] = mapped_column(JSON, default=list)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String, default="demo-tech")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
