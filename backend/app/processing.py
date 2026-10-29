"""Processing observability: persisted per-stage AI/model events plus structured
stdout logs (for Coolify) sharing one correlation id.

What is recorded: stage summaries and diagnostics (prompts tried, confidences,
counts, hashes, durations, errors). What is NEVER recorded: API keys, auth
headers, full raw provider payloads, or duplicated video bytes. Transcripts and
videos stay in their own records; events link to them.

Event recording must never break the pipeline it observes: callers wrap
record() in try/except and continue on failure.
"""
import contextvars
import json
import logging
import os
import time
import uuid

_correlation: contextvars.ContextVar[str] = contextvars.ContextVar("fg_correlation", default="")


def new_correlation() -> str:
    tok = uuid.uuid4().hex[:12]
    _correlation.set(tok)
    return tok


def get_correlation() -> str:
    return _correlation.get()


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("fieldguard.processing")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False
    return logger


_logger = _build_logger()


def record(db, entity_type: str, entity_id: str, stage: str, status: str,
           operation: str = "", provider: str = "", model: str = "",
           duration_ms: int | None = None, summary: dict | None = None,
           actor: str = ""):
    """Persist a ProcessingEvent and mirror it to stdout as one JSON line."""
    from . import models as M
    summary = summary or {}
    corr = get_correlation()
    ev = M.ProcessingEvent(
        correlation_id=corr, entity_type=entity_type, entity_id=entity_id,
        actor=actor, stage=stage, operation=operation, provider=provider,
        model=model, status=status, duration_ms=duration_ms, summary=summary)
    db.add(ev)
    db.flush()
    try:
        _logger.info(json.dumps({
            "logger": "fieldguard.processing", "correlation_id": corr,
            "entity_type": entity_type, "entity_id": entity_id, "stage": stage,
            "operation": operation, "provider": provider, "model": model,
            "status": status, "duration_ms": duration_ms, "summary": summary,
        }, default=str))
    except Exception:
        pass
    return ev


def safe_record(db, *args, **kwargs):
    """record() that never raises; returns the event or None."""
    try:
        return record(db, *args, **kwargs)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


class timed:
    """Usage: with timed() as t: ...; t.ms -> elapsed milliseconds."""

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self._t0) * 1000)
        return False
