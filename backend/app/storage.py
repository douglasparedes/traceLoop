"""Server-side persistent media storage.

Single source of truth for where bytes live: MEDIA_ROOT (env override,
default <backend>/data for backward compatibility with existing records).
Storage keys stored in the DB are always relative ("data/..."); this module
resolves them and guards against path traversal. The PWA cache is only an
offline playback optimization — never the authoritative copy.
"""
import os
import shutil
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def media_root() -> Path:
    """Absolute media root. Defaults to the historic backend/data directory
    so existing storage keys keep resolving without a migration."""
    env = os.getenv("MEDIA_ROOT", "")
    root = Path(env) if env else (BACKEND_DIR / "data")
    return root.resolve()


def media_path(storage_key: str) -> Path:
    """Resolve a DB storage key to an absolute path inside MEDIA_ROOT.

    Raises ValueError on absolute keys or ".." escapes so a hostile or
    corrupt key can never escape the media volume.
    """
    raw = (storage_key or "").replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        raise ValueError(f"Invalid storage key: {storage_key!r}")
    key = raw.lstrip("/")
    base = media_root()
    # Keys are stored with the legacy "data/..." prefix; the volume root
    # already *is* that data directory.
    rel = key[5:] if key == "data" or key.startswith("data/") else key
    return (base / rel).resolve()


def ensure_media_subdirs() -> list[str]:
    """Create the required media subdirectories. Returns the ones created."""
    created = []
    for sub in ("tutorials", "evidence", "live"):
        d = media_root() / sub
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            created.append(sub)
    tmp = media_root() / ".tmp"
    if not tmp.is_dir():
        tmp.mkdir(parents=True, exist_ok=True)
    return created


def sweep_stale_tmp(max_age_sec: int = 24 * 3600) -> int:
    """Delete abandoned chunked-upload temp files. Returns count removed."""
    tmp = media_root() / ".tmp"
    if not tmp.is_dir():
        return 0
    now = time.time()
    removed = 0
    for p in tmp.glob("*.part"):
        try:
            if now - p.stat().st_mtime > max_age_sec:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def _missing(model, key_attr: str, db, limit: int = 500) -> list[str]:
    """Ids whose storage_key points at no file. Capped scan, ids only —
    never filesystem paths (no sensitive info leaves the server)."""
    from sqlalchemy import select
    missing: list[str] = []
    try:
        rows = db.scalars(select(model).limit(limit)).all()
    except Exception:
        return missing
    for r in rows:
        key = getattr(r, key_attr, "") or ""
        if not key:
            continue
        try:
            if not media_path(key).is_file():
                missing.append(r.id)
        except ValueError:
            missing.append(r.id)
        if len(missing) >= 20:
            break
    return missing


def storage_health(db) -> dict:
    """Report media volume + database health for the admin endpoint."""
    from . import models as M
    root = media_root()
    out: dict = {"media_root_ok": root.is_dir(), "writable": False,
                 "disk": {}, "database_ok": False, "missing": {}}
    try:
        ensure_media_subdirs()
        probe = root / ".tmp" / ".writetest"
        probe.write_bytes(b"ok")
        probe.unlink()
        out["writable"] = True
    except OSError:
        out["writable"] = False
    try:
        du = shutil.disk_usage(str(root))
        out["disk"] = {"total": du.total, "used": du.used, "free": du.free}
    except OSError:
        out["disk"] = {"error": "unavailable"}
    try:
        from sqlalchemy import select as _select
        db.scalar(_select(1))
        out["database_ok"] = True
    except Exception:
        out["database_ok"] = False
    try:
        out["missing"] = {
            "tutorial_sources": _missing(M.TutorialJob, "video_storage_key", db),
            "video_guides": _missing(M.VideoGuide, "storage_key", db),
            "visual_assets": _missing(M.VisualAsset, "storage_key", db),
            "evidence": _missing(M.Evidence, "storage_key", db),
        }
    except Exception:
        out["missing"] = {"error": "scan failed"}
    return out
