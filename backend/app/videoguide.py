"""Video guide generation: original-voice cut + Remotion render.

A video guide is a versioned MP4 cut from ONE tutorial: per-scene narration
slices are cut from the user's own recorded audio with ffmpeg (never
synthesized, never invented), step cards and captions are rendered from the
canonical procedure, and visuals reuse real object illustrations.

Follows docs/remotion (remotion-saas skill): plain Node.js SSR via
@remotion/renderer on our long-running server — no Lambda, no extra cloud.
"""
import os
import threading
import uuid
from pathlib import Path

from sqlalchemy import select

from . import ai
from .db import SessionLocal
from . import models as M
from .tutorial import BASE, _ffmpeg

VIDEO_QUOTA_PER_DAY = int(os.getenv("MAX_VIDEO_OPS_PER_DAY", "10"))
VIDEO_FPS = 30
VIDEO_W, VIDEO_H = 1280, 720
TITLE_LEAD_SEC = 1.5
# Longest source tutorial a video guide may be built from. Renders are
# real-time-ish SSR; beyond this the job is rejected up front (422, before
# any VideoGuide row exists) instead of dying mid-render. The 600s default
# aligns with the transcription window so any fully-processed tutorial
# can get a video.
MAX_VIDEO_GUIDE_SEC = int(os.getenv("MAX_VIDEO_GUIDE_SEC", "600"))


def _check_video_quota(db, actor: str) -> None:
    import datetime as _dt
    if VIDEO_QUOTA_PER_DAY <= 0:
        return
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    n = 0
    for a in db.scalars(select(M.VideoGuide).where(M.VideoGuide.created_by == actor)).all():
        if (a.created_at.isoformat() if hasattr(a.created_at, "isoformat") else "")[:10] >= today:
            n += 1
    if n >= VIDEO_QUOTA_PER_DAY:
        raise ValueError(f"Daily video-guide limit reached ({VIDEO_QUOTA_PER_DAY}). Try again tomorrow.")


def _video_paths(job_id: str) -> dict:
    from . import storage as _storage
    d = _storage.media_root() / "tutorials" / job_id / "video"
    d.mkdir(parents=True, exist_ok=True)
    return {"dir": d, "voiceover": d / "voiceover.wav", "props": d / "props.json",
            "progress": d / "render-progress.json", "output": d / "guide-video-render.mp4"}


def _wav_seconds(path: Path) -> float:
    """Measured duration of a WAV file from its own header.

    Never estimated from requested slice ranges — the render timeline and
    the reported voiceover length must reflect actual bytes on disk.
    """
    import wave as _wave
    try:
        with _wave.open(str(path), "rb") as w:
            rate = w.getframerate() or 0
            if rate <= 0:
                return 0.0
            return w.getnframes() / float(rate)
    except Exception:
        return 0.0


def _record_voiceover(db, job_id: str, actor: str, status: str, summary: dict) -> None:
    """Best-effort processing-event record for the voiceover step."""
    try:
        from . import processing as _proc
        _proc.safe_record(db, "tutorial", job_id, "video_guide", status,
                          operation="extract_voiceover", actor=actor,
                          summary=summary)
    except Exception:
        pass


def cut_voiceover(job: M.TutorialJob, scenes: list[dict], db=None, actor: str = "") -> tuple[Path | None, float]:
    """Cut per-scene narration from the USER's own recording; concat to one track.

    Returns (voiceover_wav_path_or_None, measured_seconds). Slices come from
    timed transcript ranges overlapping each step — the voiceover is a cut of
    the original audio, never synthesized. A 0.4s silence tail pads each
    scene so captions don't clip.

    No audio track (or an unreadable source) is an expected *silent* outcome:
    returns (None, 0.0) with a "skipped" event. Genuine ffmpeg failures are
    recorded as "failed" with diagnostics — and still return (None, 0.0) so
    a valid silent video can render instead of killing the whole job.
    """
    from . import storage as _storage
    try:
        source = _storage.media_path(job.video_storage_key)
    except ValueError:
        _record_voiceover(db, job.id, actor, "skipped",
                          {"reason": "invalid source storage key"})
        return None, 0.0
    if not source.is_file():
        _record_voiceover(db, job.id, actor, "skipped",
                          {"reason": "source video file missing"})
        return None, 0.0
    total = sum(max(0.0, float(s.get("audio_end", 0)) - float(s.get("audio_start", 0))) for s in scenes)
    if total <= 0:
        _record_voiceover(db, job.id, actor, "skipped",
                          {"reason": "scene plan holds no audio ranges — silent video"})
        return None, 0.0
    parts: list[Path] = []
    try:
        vdir = _video_paths(job.id)["dir"]
        import subprocess as _sp
        for i, s in enumerate(scenes):
            ss = max(0.0, float(s.get("audio_start", 0)))
            dur = max(0.0, float(s.get("audio_end", 0)) - ss)
            if dur <= 0:
                continue
            part = vdir / f"slice-{i:02d}.wav"
            r = _sp.run([_ffmpeg(), "-y", "-ss", f"{ss:.2f}", "-i", str(source),
                         "-t", f"{dur:.2f}", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
                         str(part)], capture_output=True, timeout=120)
            if r.returncode != 0 or not part.exists():
                continue
            tail = vdir / f"slice-{i:02d}-tail.wav"
            r2 = _sp.run([_ffmpeg(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.4",
                          "-c:a", "pcm_s16le", str(tail)], capture_output=True, timeout=60)
            parts.extend([part] + ([tail] if r2.returncode == 0 and tail.exists() else []))
        if not parts:
            _record_voiceover(db, job.id, actor, "failed",
                              {"reason": "no audio slices could be extracted",
                               "scenes": len(scenes)})
            return None, 0.0
        lst = vdir / "concat.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        out = _video_paths(job.id)["voiceover"]
        r = _sp.run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                     "-c:a", "pcm_s16le", str(out)], capture_output=True, timeout=180)
        if r.returncode != 0 or not out.exists():
            tail = (r.stderr or b"").decode("utf-8", "replace")[-300:]
            _record_voiceover(db, job.id, actor, "failed",
                              {"reason": "voiceover concat failed", "ffmpeg": tail})
            return None, 0.0
        measured = _wav_seconds(out)
        if measured <= 0:
            _record_voiceover(db, job.id, actor, "failed",
                              {"reason": "rendered voiceover is empty or unreadable"})
            return None, 0.0
        _record_voiceover(db, job.id, actor, "succeeded",
                          {"voiceover_sec": round(measured, 2), "scenes": len(scenes),
                           "silent_tail_per_scene": 0.4})
        return out, measured
    except Exception as e:
        _record_voiceover(db, job.id, actor, "failed",
                          {"reason": f"{type(e).__name__}: {str(e)[:200]}"})
        return None, 0.0


def _resolve_visual_file(job_dir: Path, vis: dict) -> tuple[str | None, str]:
    """Resolve a scene visual to an absolute render-ready path.

    Searches every real storage location (visuals/, video/frames/, job
    dir) under the configured MEDIA_ROOT and verifies the file belongs to
    this tutorial's media directory. Returns (path_or_None, diagnostic).
    """
    name = str((vis or {}).get("name", "") or "")
    if not name:
        return None, "empty visual name"
    safe = Path(name).name
    if safe != name or not safe:
        return None, f"unsafe visual name {name!r}"
    preferred = []
    if str((vis or {}).get("dir", "") or ""):
        preferred.append(job_dir / str(vis["dir"]) / safe)
    preferred.extend([job_dir / "visuals" / safe,
                      job_dir / "video" / "frames" / safe,
                      job_dir / safe])
    try:
        root = job_dir.resolve()
    except OSError:
        return None, "tutorial media directory unreadable"
    for cand in preferred:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if root not in resolved.parents and resolved != root:
            continue
        if resolved.is_file():
            return str(resolved), ""
    return None, f"missing file for visual '{safe}' (checked visuals/, video/frames/, job dir)"


def _image_dimensions(path: str) -> tuple[int, int]:
    """Local image dimensions for 16:9 composition decisions. (0, 0) on failure."""
    try:
        from PIL import Image as _Image
        with _Image.open(path) as im:
            w, h = im.size
            return (int(w) or 0, int(h) or 0)
    except Exception:
        return (0, 0)


def _segments_for_range(segments: list[dict], start: float, end: float) -> list[dict]:
    out = []
    for x in segments or []:
        try:
            ss, se = float(x.get("start", 0) or 0), float(x.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        if se > start and ss < end:
            out.append(x)
    return out


def plan_visual_beats(scene: dict, segments: list[dict], duration_frames: int,
                      start_frame: int) -> list[dict]:
    """Split a scene into purposeful visual beats (deterministic frames).

    Short scenes (<8s) get establish + focus; longer scenes get introduce,
    focus, explain, and verify/recap beats so no still sits unchanged for
    20+ seconds. Each narrative beat's body is the transcript actually
    overlapping that beat's own time window — on-screen text follows the
    voiceover instead of repeating one static block. Consecutive beats
    never share identical bodies when any alternative exists. Frame ranges
    are contiguous integers summing exactly to duration_frames.
    """
    if duration_frames <= 0:
        return []
    try:
        start = float(scene.get("audio_start", 0) or 0)
        end = float(scene.get("audio_end", 0) or 0)
    except (TypeError, ValueError):
        start, end = 0.0, 0.0
    scene_dur = max(0.0, end - start)
    scene_sec = duration_frames / max(1, VIDEO_FPS)
    expected = str(scene.get("expected_result", "") or "")[:220]
    tools = [str(x) for x in (scene.get("required_tools") or [])][:4]
    tools_line = f"Tools: {', '.join(tools)}" if tools else ""
    caption = str(scene.get("caption", "") or "")[:220]
    title = str(scene.get("title", "") or "")
    step_no = int(scene.get("step", scene.get("step_number", 0)) or 0)
    recap = f"Step {step_no} of {title}" if title else caption
    if scene_sec < 8:
        kinds = ["hero", "detail"]
        ratios = [0.55, 0.45]
    else:
        kinds = ["hero", "detail", "caption", "verify"]
        ratios = [0.30, 0.30, 0.25, 0.15]
    # Frame ranges first (contiguous, exact sum).
    durs: list[int] = []
    offset = 0
    for i, ratio in enumerate(ratios):
        if i == len(ratios) - 1:
            dur = duration_frames - offset
        else:
            dur = max(1, int(round(duration_frames * ratio)))
            dur = min(dur, duration_frames - offset - (len(ratios) - i - 1))
        if dur <= 0:
            continue
        durs.append(dur)
        offset += dur
    kinds = kinds[:len(durs)]
    # Bodies by time overlap with each beat's own window.
    timed = []
    for x in segments or []:
        try:
            ss, se = float(x.get("start", 0) or 0), float(x.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        text = str(x.get("text", "") or "").strip()
        if text and se > start and ss < end:
            timed.append((ss, se, text))
    used: list[str] = []

    def pick_timed(ws: float, we: float) -> str:
        """The line actually spoken during [ws, we): max overlap wins.

        Repeating a still-spoken line across a beat boundary is honest;
        showing a line that is not being spoken is not.
        """
        best: tuple[float, str] | None = None
        best_ov = 0.0
        for ss, se, text in timed:
            ov = min(se, we) - max(ss, ws)
            if ov > 0 and (best is None or ov > best_ov or
                           (ov == best_ov and ss < best[0])):
                best, best_ov = (ss, text), ov
        return best[1] if best else ""

    def pick_fallback(options: list[str]) -> str:
        for fb in options:
            if fb and fb not in used:
                used.append(fb)
                return fb
        for fb in options:
            if fb:
                return fb
        return ""

    beats = []
    offset = 0
    for i, (kind, dur) in enumerate(zip(kinds, durs)):
        ws = start + (offset / max(1, duration_frames)) * scene_dur if scene_dur > 0 else start
        we = start + ((offset + dur) / max(1, duration_frames)) * scene_dur if scene_dur > 0 else start
        body = pick_timed(ws, we)
        if not body:
            if kind == "verify":
                body = pick_fallback([t for t in [expected, tools_line, recap, caption] if t])
            elif kind == "caption":
                body = pick_fallback([t for t in [recap, caption, expected, tools_line] if t])
            else:
                body = pick_fallback([t for t in [caption, recap, expected, tools_line] if t])
        if not body:
            body = recap or caption or expected or "Follow the narration."
        beats.append({"kind": kind, "headline": "", "body": body,
                      "startFrame": start_frame + offset, "durationFrames": dur})
        offset += dur
    return beats


def build_video_props(job: M.TutorialJob, scenes: list[dict], voiceover: Path | None,
                      voiceover_sec: float, diagnostics: list | None = None) -> dict:
    """Props for the Remotion ProcedureVideo composition (Zod-validated at render).

    Images resolve to absolute local files (server render) — no URLs, no
    network at render time. Every scene is guaranteed a visual by the
    resolver; anything unresolvable here is recorded in diagnostics (and
    the optional diagnostics list) instead of silently rendering empty.
    """
    from . import storage as _storage
    job_dir = _storage.media_root() / "tutorials" / job.id
    fps = VIDEO_FPS
    frame = int(1.5 * fps)  # title card
    out_scenes = []
    for s in scenes:
        dur = max(1.0, float(s.get("audio_end", 0)) - float(s.get("audio_start", 0)) + 0.4)
        img, diag = _resolve_visual_file(job_dir, s.get("visual") or {})
        if diag and diagnostics is not None:
            diagnostics.append({"step": int(s.get("step_number", len(out_scenes) + 1)),
                                "visual_kind": str((s.get("visual") or {}).get("kind", "")),
                                "diagnostic": diag})
        cap_text = str(s.get("caption") or s.get("narration") or "")
        dur_frames = int(round(dur * fps))
        scene_start = frame
        beats = plan_visual_beats(s, getattr(job, "timed_segments", None) or [], dur_frames, scene_start)
        for b in beats:
            b["image"] = img
        image_w, image_h = _image_dimensions(img) if img else (0, 0)
        out_scenes.append({
            "step": int(s.get("step_number", len(out_scenes) + 1)),
            "title": str(s.get("title", "")),
            "caption": cap_text,
            "image": img,
            "startFrame": scene_start,
            "durationFrames": dur_frames,
            "expected": str(s.get("expected_result", "") or "")[:300],
            "tools": [str(x) for x in (s.get("required_tools") or [])][:6],
            "imageW": image_w,
            "imageH": image_h,
            "beats": beats,
        })
        frame += dur_frames
    total_frames = frame + int(0.5 * fps)
    return {"title": job.title, "fps": fps, "width": VIDEO_W, "height": VIDEO_H,
            "format": str(getattr(job, "guide_format", "") or "work_instruction"),
            "voiceover": str(voiceover) if voiceover else None,
            "voiceoverFrames": int(round(voiceover_sec * fps)) if voiceover else 0,
            "scenes": out_scenes, "totalFrames": total_frames}


def validate_scene_plan(scenes: object, duration_sec: float) -> list[dict]:
    """Validate an edited scene plan. Raises ValueError on any problem.

    Rules: non-empty list; each scene needs a title; audio ranges must be
    finite, non-negative, end > start, and within the source duration;
    include defaults to True. Never fabricates timing — invalid ranges are
    rejected, not clamped into plausibility.
    """
    import math as _math
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Provide at least one scene")
    if len(scenes) > 60:
        raise ValueError("Too many scenes (max 60)")
    clean: list[dict] = []
    dur = float(duration_sec or 0)
    for i, s in enumerate(scenes):
        if not isinstance(s, dict):
            raise ValueError(f"Scene {i + 1} must be an object")
        title = str(s.get("title", "") or "").strip()[:200]
        if not title:
            raise ValueError(f"Scene {i + 1} needs a title")
        caption = str(s.get("caption", "") or s.get("narration", "") or "")[:2000]
        try:
            astart = float(s.get("audio_start", s.get("start", 0)))
            aend = float(s.get("audio_end", s.get("end", 0)))
        except (TypeError, ValueError):
            raise ValueError(f"Scene {i + 1}: audio_start/audio_end must be numbers")
        if not (_math.isfinite(astart) and _math.isfinite(aend)):
            raise ValueError(f"Scene {i + 1}: time range must be finite numbers")
        if astart < 0 or aend < 0:
            raise ValueError(f"Scene {i + 1}: time range cannot be negative")
        if not (aend > astart):
            raise ValueError(f"Scene {i + 1}: audio_end must be after audio_start")
        if dur > 0 and (astart > dur or aend > dur + 0.01):
            raise ValueError(f"Scene {i + 1}: range exceeds the {dur:.0f}s source recording")
        vis = s.get("visual") or {}
        vis_name = str(vis.get("name", "") or "")[:200] if isinstance(vis, dict) else ""
        clean.append({
            "step": int(s.get("step", s.get("step_number", i + 1)) or (i + 1)),
            "title": title,
            "caption": caption,
            "audio_start": round(astart, 2),
            "audio_end": round(aend, 2),
            "visual": {"name": vis_name} if vis_name else {},
            "include": bool(s.get("include", True)),
        })
    included = [c for c in clean if c["include"]]
    if not included:
        raise ValueError("At least one scene must be included")
    return clean


def suggest_scene_plan(job: M.TutorialJob, db=None) -> dict:
    """AI-planned initial scene plan from the processed tutorial content.

    Same guide-aware planner as the automatic render path (Muse Spark with
    a deterministic fallback, never inventing narration or visuals), mapped
    into the editable StudioScene shape and validated so the suggestion is
    guaranteed render-acceptable. Read-only: creates no versions, saves no
    drafts. Raises ValueError when there is nothing to plan from (no steps).
    """
    from . import ai as _ai

    steps = job.steps or []
    if not steps:
        raise ValueError("No guide steps yet — the tutorial has no processed content to plan scenes from")
    hints = accepted_visual_hints(db, job.id) if db is not None else []
    plan = _ai.plan_video_scenes(job.title, steps, job.objects or [],
                                 job.timed_segments or [],
                                 guide_markdown=job.guide_markdown or "",
                                 guide_format=job.guide_format or "",
                                 accepted_visuals=hints)
    raw = plan.get("scenes") or []
    if not raw:
        raise ValueError("Could not plan video scenes from this tutorial")
    scenes = []
    for i, sc in enumerate(raw):
        if not isinstance(sc, dict):
            continue
        vis = sc.get("visual") or {}
        vis_name = str(vis.get("name", "") or "") if isinstance(vis, dict) else ""
        scenes.append({
            "step": int(sc.get("step_number", sc.get("step", i + 1)) or (i + 1)),
            "title": str(sc.get("title", "") or f"Scene {i + 1}"),
            "caption": str(sc.get("caption", "") or ""),
            "audio_start": sc.get("audio_start", sc.get("start", 0)),
            "audio_end": sc.get("audio_end", sc.get("end", 0)),
            "visual": {"name": vis_name} if vis_name else {},
            "include": True,
        })
    clean = validate_scene_plan(scenes, job.duration_sec or 0)
    return {"scenes": clean, "simulated": bool(plan.get("simulated", True)),
            "model": str(plan.get("model", "") or ""),
            "note": str(plan.get("note", "") or "")}


def accepted_visual_hints(db, job_id: str) -> list[dict]:
    """Accepted visuals eligible for video composition.

    Accepted, human-reviewed assets only; illustrative alternatives are
    never eligible as factual evidence. Each hint carries the storage
    basename so the planner's choice resolves to a real file.
    """
    try:
        rows = db.scalars(select(M.VisualAsset).where(
            M.VisualAsset.tutorial_id == job_id,
            M.VisualAsset.status == "accepted")).all()
    except Exception:
        return []
    out = []
    for a in rows:
        if (a.kind or "") == "illustrative_alternative":
            continue
        name = Path(a.storage_key or "").name if a.storage_key else ""
        if not name:
            continue
        out.append({"label": a.instruction or a.kind or "visual", "name": name,
                    "asset_id": a.id, "kind": a.kind})
    return out


def _latest_guide_snapshot(db, job_id: str):
    try:
        return db.scalars(select(M.GuideSnapshot).where(
            M.GuideSnapshot.tutorial_id == job_id
        ).order_by(M.GuideSnapshot.created_at.desc())).first()
    except Exception:
        return None


def _latest_guide_snapshot(db, job_id: str):
    try:
        return db.scalars(select(M.GuideSnapshot).where(
            M.GuideSnapshot.tutorial_id == job_id
        ).order_by(M.GuideSnapshot.created_at.desc())).first()
    except Exception:
        return None


# ---------------------------------------------------------------- Automatic step visuals
# Priority: accepted visual -> source-derived (overlay/cutout/keyframe/frame)
# -> Muse Image auto-generation (cached, quota-bounded) -> deterministic
# guide graphic. Every scene ends with a real visual; empty panels are a
# defect, never a normal outcome.

MAX_AUTO_IMAGES_PER_VIDEO = int(os.getenv("MAX_AUTO_IMAGES_PER_VIDEO", "8"))
MAX_IMAGE_OPS_PER_DAY = int(os.getenv("MAX_IMAGE_OPS_PER_DAY", "50"))


def _auto_image_quota_ok(db, actor: str) -> bool:
    """Daily cap for automatically generated video illustrations."""
    if MAX_IMAGE_OPS_PER_DAY <= 0:
        return True
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    n = 0
    try:
        rows = db.scalars(select(M.VisualAsset).where(
            M.VisualAsset.kind == "illustrative_alternative")).all()
    except Exception:
        return True
    for a in rows:
        try:
            if not (a.provenance or {}).get("auto"):
                continue
        except Exception:
            continue
        if ((a.created_at.isoformat() if hasattr(a.created_at, "isoformat") else "")[:10] >= today
                and (not actor or (a.created_by or "") in ("", actor))):
            n += 1
    return n < MAX_IMAGE_OPS_PER_DAY


def _visual_fingerprint(job: M.TutorialJob, snapshot_id: str | None,
                        scene: dict, candidate_names: list[str], prompt: str) -> str:
    """Stable cache key: same guide content -> same illustration, no credits."""
    import hashlib as _hl
    import json as _json
    payload = {
        "tutorial": job.id,
        "content_revision": int(getattr(job, "content_revision", 0) or 0),
        "snapshot": snapshot_id or "",
        "step": int(scene.get("step", scene.get("step_number", 0)) or 0),
        "title": str(scene.get("title", "")),
        "caption": str(scene.get("caption", "") or scene.get("narration", ""))[:500],
        "objects": sorted(str(x) for x in (scene.get("objects_used") or [])),
        "candidates": sorted(candidate_names),
        "prompt": prompt,
    }
    try:
        from . import ai as _ai
        payload["model"] = _ai.IMAGE_MODEL
    except Exception:
        payload["model"] = "muse-image-1.0"
    return "auto-video-visual:" + _hl.sha256(
        _json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:48]


def _store_auto_visual(db, job: M.TutorialJob, kind: str, raw: bytes, mime: str,
                       label: str, step_number: int, actor: str,
                       fingerprint: str, extra_provenance: dict | None = None) -> M.VisualAsset:
    """Persist a generated/graphic illustration under MEDIA_ROOT + record it.

    Validates real image bytes (PIL verify + dimensions); raises ValueError
    on invalid input so callers fall through to the next fallback.
    """
    from PIL import Image as _Image
    import io as _io
    from . import storage as _storage
    try:
        with _Image.open(_io.BytesIO(raw)) as im:
            im.verify()
        with _Image.open(_io.BytesIO(raw)) as im:
            w, h = im.size
    except Exception:
        raise ValueError("generated bytes are not a valid image")
    if w <= 0 or h <= 0:
        raise ValueError("generated image has no dimensions")
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".png")
    store_dir = _storage.media_root() / "tutorials" / job.id / "visuals"
    store_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (store_dir / name).write_bytes(raw)
    prov = {"auto": True, "fingerprint": fingerprint, "step_number": step_number,
            "content_revision": int(getattr(job, "content_revision", 0) or 0)}
    if extra_provenance:
        prov.update(extra_provenance)
    a = M.VisualAsset(tutorial_id=job.id, parent_id="", kind=kind, status="review",
                      storage_key=f"data/tutorials/{job.id}/visuals/{name}",
                      mime_type=mime, width=w, height=h,
                      instruction=label, model=prov.get("model", ""),
                      simulated=bool(prov.get("simulated", False)),
                      provenance=prov, created_by=actor or job.actor,
                      idempotency_key=fingerprint)
    db.add(a)
    db.flush()
    return a


def _scene_source_candidates(job: M.TutorialJob, scene: dict) -> list[dict]:
    """Real source-derived visuals for a scene, best first.

    Object overlays/cutouts used by the step, then keyframes overlapping
    the scene's time range (nearest in-range, else nearest overall — still
    real footage, recorded as such in diagnostics).
    """
    from . import storage as _storage
    job_dir = _storage.media_root() / "tutorials" / job.id
    out: list[dict] = []
    try:
        start = float(scene.get("audio_start", 0) or 0)
        end = float(scene.get("audio_end", 0) or 0)
    except (TypeError, ValueError):
        start, end = 0.0, 0.0
    by_obj = {}
    for o in (job.objects or []):
        try:
            by_obj[int(o.get("obj_id", -1))] = o
        except (TypeError, ValueError):
            continue
    for oid in (scene.get("objects_used") or []):
        try:
            o = by_obj.get(int(oid))
        except (TypeError, ValueError):
            o = None
        if not o:
            continue
        if o.get("overlay"):
            out.append({"name": Path(str(o["overlay"])).name, "kind": "overlay",
                        "label": str(o.get("label", "object"))})
        if o.get("illustration"):
            out.append({"name": Path(str(o["illustration"])).name, "kind": "cutout",
                        "label": str(o.get("label", "object"))})
    kfs = [k for k in (getattr(job, "keyframes", None) or [])
           if isinstance(k, dict) and k.get("name")]
    if kfs:
        def _t(k):
            try:
                return float(k.get("t", 0) or 0)
            except (TypeError, ValueError):
                return 0.0
        in_range = [k for k in kfs if start <= _t(k) <= end] if end > start else []
        pool = in_range or kfs
        best = min(pool, key=lambda k: abs(_t(k) - start))
        out.append({"name": Path(str(best["name"])).name, "kind": "keyframe",
                    "label": f"source frame at {int(_t(best))}s",
                    "in_range": bool(in_range)})
    # Keep only files that actually exist under MEDIA_ROOT.
    live = []
    for c in out:
        if not c.get("name"):
            continue
        if (job_dir / c["name"]).is_file() or (job_dir / "visuals" / c["name"]).is_file():
            live.append(c)
    return live


def _extract_step_frame(job: M.TutorialJob, t: float, step_number: int) -> dict | None:
    """Extract one real recorded frame at time t (cached on disk).

    Used when a scene has no overlay/cutout/keyframe — still genuine
    evidence from the user's own recording, never invented.
    """
    from . import storage as _storage
    if t < 0:
        return None
    try:
        source = _storage.media_path(job.video_storage_key or "")
    except ValueError:
        return None
    if not source.is_file():
        return None
    frames_dir = _storage.media_root() / "tutorials" / job.id / "video" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    name = f"step-{int(step_number or 0):02d}-frame.jpg"
    dest = frames_dir / name
    if not dest.is_file() or dest.stat().st_size == 0:
        import subprocess as _sp
        r = _sp.run([_ffmpeg(), "-y", "-ss", f"{max(0.0, float(t)):.2f}", "-i", str(source),
                     "-frames:v", "1", "-q:v", "3", str(dest)],
                    capture_output=True, timeout=120)
        if r.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
            try:
                if dest.is_file():
                    dest.unlink()
            except OSError:
                pass
            return None
    return {"name": name, "kind": "frame",
            "label": f"recorded frame at {int(max(0.0, float(t)))}s", "dir": "video/frames"}


def _image_prompt_for_step(job: M.TutorialJob, scene: dict, objects_by_label: dict) -> str:
    """Grounded Muse Image prompt: visualizes the described action only.

    Explicitly forbids invented equipment geometry, values, measurements,
    warnings, and electrical details, plus any rendered text (titles,
    labels, and callouts are Remotion overlays, not pixels).
    """
    title = str(scene.get("title", "") or "")
    action = str(scene.get("caption", "") or scene.get("narration", "") or "")[:600]
    obj_labels = []
    for oid in (scene.get("objects_used") or []):
        for label, o in objects_by_label.items():
            try:
                if int(o.get("obj_id", -999)) == int(oid):
                    obj_labels.append(label)
                    break
            except (TypeError, ValueError):
                continue
    tools = [str(x) for x in (scene.get("required_tools") or [])][:6]
    expected = str(scene.get("expected_result", "") or "")[:300]
    fmt = (job.guide_format or "").replace("_", " ")
    parts = [f"Instructional illustration for a maintenance guide step ({fmt or 'work instruction'}).",
             f"Step: {title}." if title else "",
             f"Action to show: {action}" if action else "",
             ("Objects involved: " + ", ".join(obj_labels) + ".") if obj_labels else "",
             ("Tools/materials present: " + ", ".join(tools) + ".") if tools else "",
             (f"Expected result being worked toward: {expected}") if expected else "",
             "Show a clear conceptual diagram of the described action using ONLY the elements above; "
             "a generic workshop setting is fine.",
             "Do NOT invent exact equipment models, component geometry, torque values, measurements, "
             "safety steps, or electrical connections not stated above.",
             "Do NOT render any text, labels, numbers, arrows, or callouts in the image — "
             "titles and annotations are added separately as overlays.",
             "Flat vector style, landscape 16:9 composition."]
    return " ".join(p for p in parts if p)


def _fallback_graphic(job: M.TutorialJob, scene: dict, step_number: int,
                      fingerprint: str, actor: str, db,
                      snapshot_id: str | None = None) -> dict | None:
    """Deterministic explanatory graphic from verified guide text.

    A branded step card (number, title, tools) rendered with PIL — clearly
    a designed graphic, never photographic evidence. Stored persistently
    under the same fingerprint so it is reused, not rebuilt.
    """
    from PIL import Image as _Img, ImageDraw as _Draw
    try:
        from PIL import ImageFont as _Font
        f_title = _Font.load_default(size=64)
        f_body = _Font.load_default(size=36)
        f_tag = _Font.load_default(size=28)
    except Exception:
        f_title = f_body = f_tag = None
    W, H = 1280, 720
    card = _Img.new("RGB", (W, H), (11, 31, 26))
    d = _Draw.Draw(card)
    d.rectangle([64, 64, W - 64, H - 64], outline=(255, 176, 32), width=4)
    title = str(scene.get("title", "") or f"Step {step_number}")[:80]
    d.text((110, 130), f"STEP {step_number}", fill=(255, 176, 32), font=f_tag)
    d.text((110, 190), title, fill=(242, 252, 242), font=f_title)
    tools = [str(x) for x in (scene.get("required_tools") or [])][:3]
    y = 330
    for t in tools:
        d.text((110, y), f"• {t[:60]}", fill=(159, 195, 181), font=f_body)
        y += 56
    caption = str(scene.get("caption", "") or "")[:140]
    if caption:
        d.text((110, H - 200), caption, fill=(242, 252, 242), font=f_body)
    d.text((110, H - 120), "GUIDE GRAPHIC — from the verified guide, not a photo",
           fill=(255, 176, 32), font=f_tag)
    import io as _io
    buf = _io.BytesIO()
    card.save(buf, format="PNG")
    raw = buf.getvalue()
    try:
        a = _store_auto_visual(db, job, "guide_visual", raw, "image/png",
                               f"Step {step_number} guide graphic: {title}",
                               step_number, actor, fingerprint,
                               {"deterministic": True, "illustrative": False,
                                "simulated": False, "model": "deterministic-graphic",
                                "guide_snapshot_id": snapshot_id,
                                "note": "Deterministic text graphic from the verified guide — not photographic evidence."})
        db.commit()
        return {"name": Path(a.storage_key).name, "kind": "guide_visual",
                "label": f"step {step_number} guide graphic", "asset_id": a.id}
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _match_accepted_hint(hints: list[dict], scene: dict,
                         objects_by_label: dict) -> dict | None:
    """Match an accepted visual to a step by label overlap.

    Conservative: requires the hint label to overlap the step title,
    caption, or one of the step's object labels — never assigns an
    unrelated image merely because one is available.
    """
    text = " ".join([str(scene.get("title", "")), str(scene.get("caption", "")),
                     str(scene.get("narration", ""))]).lower()
    step_labels = set()
    for oid in (scene.get("objects_used") or []):
        for label in objects_by_label:
            try:
                if int(objects_by_label[label].get("obj_id", -999)) == int(oid):
                    step_labels.add(str(label).lower())
            except (TypeError, ValueError):
                continue
    for h in hints:
        hl = str(h.get("label", "") or "").lower()
        if not hl or not h.get("name"):
            continue
        if hl in text or any(hl in sl or sl in hl for sl in step_labels if sl):
            return {"name": Path(str(h["name"])).name, "kind": "accepted",
                    "label": str(h.get("label", "accepted visual")),
                    "asset_id": h.get("asset_id")}
    return None


def resolve_scene_visuals(db, job: M.TutorialJob, scenes: list[dict],
                          actor: str = "") -> tuple[list[dict], dict]:
    """Guarantee every scene a real visual.

    Priority: accepted visual -> source-derived (overlay/cutout/keyframe/
    extracted frame) -> Muse Image auto-generation (cached by fingerprint,
    quota-bounded) -> deterministic guide graphic. Returns (scenes, report).
    Normal success never yields an empty visual.
    """
    from . import ai as _ai
    report: dict = {"accepted": 0, "cached": 0, "source": 0, "generated": 0,
                    "graphic": 0, "empty": 0, "failures": []}
    try:
        snap = _latest_guide_snapshot(db, job.id)
        snapshot_id = snap.id if snap is not None else None
    except Exception:
        snapshot_id = None
    try:
        hints = accepted_visual_hints(db, job.id)
    except Exception:
        hints = []
    objects_by_label = {str(o.get("label", "")): o for o in (job.objects or []) if o.get("label")}
    try:
        quota_ok = _auto_image_quota_ok(db, actor or job.actor)
    except Exception:
        quota_ok = True
    generated_this_run = 0
    out = []
    for i, s in enumerate(scenes):
        step_number = int(s.get("step", s.get("step_number", i + 1)) or (i + 1))
        visual = _match_accepted_hint(hints, s, objects_by_label)
        if visual:
            report["accepted"] += 1
            out.append({**s, "visual": visual})
            continue
        candidates = _scene_source_candidates(job, s)
        if not candidates:
            # No overlay/cutout/keyframe file: pull one real recorded frame
            # at the scene midpoint — genuine evidence beats generation.
            try:
                mid = (float(s.get("audio_start", 0) or 0) + float(s.get("audio_end", 0) or 0)) / 2
            except (TypeError, ValueError):
                mid = 0.0
            frame = _extract_step_frame(job, mid, step_number)
            if frame:
                candidates = [frame]
        prompt = _image_prompt_for_step(job, s, objects_by_label)
        fp = _visual_fingerprint(job, snapshot_id, {**s, "step": step_number},
                                 [c["name"] for c in candidates], prompt)
        cached = None
        try:
            row = db.scalars(select(M.VisualAsset).where(
                M.VisualAsset.tutorial_id == job.id,
                M.VisualAsset.idempotency_key == fp)).first()
            if row is not None and row.storage_key:
                from . import storage as _storage
                try:
                    p = _storage.media_path(row.storage_key)
                    if p.is_file():
                        cached = {"name": Path(row.storage_key).name, "kind": row.kind or "illustrative_alternative",
                                  "label": row.instruction or "video illustration", "asset_id": row.id}
                except ValueError:
                    cached = None
        except Exception:
            cached = None
        if cached:
            report["cached"] += 1
            out.append({**s, "visual": cached})
            continue
        if candidates:
            report["source"] += 1
            out.append({**s, "visual": {**candidates[0], "asset_id": None}})
            continue
        gen_visual = None
        if quota_ok and generated_this_run < MAX_AUTO_IMAGES_PER_VIDEO:
            refs: list[tuple[bytes, str]] = []
            try:
                gen_visual = None
                res = _ai.image_generate(prompt, reference_bytes=None)
                if res.get("ok"):
                    raw = __import__("base64").b64decode(res.get("image_b64") or "")
                    mime = _ai.valid_image_bytes(raw)
                    if mime is None:
                        raise ValueError("generated bytes failed signature validation")
                    a = _store_auto_visual(
                        db, job, "illustrative_alternative", raw, mime, prompt[:200],
                        step_number, actor, fp,
                        {"model": res.get("model", ""), "simulated": False,
                         "illustrative": True, "not_evidence": True,
                         "source_reference": f"tutorial:{job.id}",
                         "guide_snapshot_id": snapshot_id,
                         "prompt_hash": fp.split(":")[-1][:16],
                         "usage": res.get("usage", {}),
                         "warning": "AI-generated illustration for this video step. Conceptual reference only — verify against the actual equipment. Never photographic evidence."})
                    db.commit()
                    gen_visual = {"name": Path(a.storage_key).name,
                                  "kind": "illustrative_alternative",
                                  "label": f"step {step_number} illustration",
                                  "asset_id": a.id}
                    report["generated"] += 1
                    generated_this_run += 1
                else:
                    report["failures"].append(
                        {"step": step_number, "stage": "generate",
                         "status": res.get("status", "error"),
                         "note": str(res.get("note", ""))[:200]})
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                report["failures"].append(
                    {"step": step_number, "stage": "generate",
                     "status": f"{type(e).__name__}: {str(e)[:120]}"})
                gen_visual = None
        if gen_visual:
            out.append({**s, "visual": gen_visual})
            continue
        if not quota_ok or generated_this_run >= MAX_AUTO_IMAGES_PER_VIDEO:
            report["failures"].append(
                {"step": step_number, "stage": "quota",
                 "status": "auto-generation budget exhausted" if quota_ok else "daily image quota reached"})
        graphic = _fallback_graphic(job, s, step_number, fp, actor, db,
                                    snapshot_id=snapshot_id)
        if graphic:
            report["graphic"] += 1
            out.append({**s, "visual": graphic})
        else:
            report["empty"] += 1
            report["failures"].append({"step": step_number, "stage": "graphic",
                                       "status": "graphic store failed"})
            out.append({**s, "visual": {}})
    try:
        from . import processing as _proc
        _proc.safe_record(db, "tutorial", job.id, "video_guide",
                          "succeeded" if not report["empty"] else "failed",
                          operation="resolve_scene_visuals", actor=actor or job.actor,
                          summary={k: v for k, v in report.items() if k != "failures"})
    except Exception:
        pass
    return out, report


def _video_fingerprint(db, job: M.TutorialJob) -> dict:
    """Content fingerprint for idempotent reuse: steps hash + guide state.

    A finished render is only reused as duplicate when the canonical steps,
    the latest guide snapshot, the content revision, and the guide format
    all match. Legacy rows without the new keys compare equal on None —
    backward compatible.
    """
    from .tutorial import _canonical_hash
    snap = _latest_guide_snapshot(db, job.id)
    return {"canonical_hash": _canonical_hash(job.steps or []),
            "guide_snapshot_id": snap.id if snap is not None else None,
            "content_revision": int(getattr(job, "content_revision", 0) or 0),
            "guide_format": job.guide_format or ""}


def describe_staleness(db, job: M.TutorialJob, vg: M.VideoGuide) -> dict:
    """Whether the guide/content moved on since this video version rendered."""
    fp = _video_fingerprint(db, job)
    prov = vg.provenance or {}
    changed = sorted(k for k in fp if prov.get(k) != fp[k])
    return {"stale": bool(changed), "changed": changed,
            "video_guide_id": vg.id, "version_number": vg.version_number or 0}


def start_video_guide(job_id: str, actor: str = "", force: bool = False, scenes: list[dict] | None = None) -> tuple[M.VideoGuide, bool]:
    """Queue (or reuse) a video-guide render. Returns (row, duplicate).

    In-flight renders are reused; a finished render is reused when the
    canonical procedure hasn't changed since (compare canonical hash).
    Pass force=True (the UI Regenerate button) to render afresh.
    Pass scenes=[...] (an edited scene plan from Tutorial Studio) to render
    exactly that plan as a NEW version — never overwriting a prior MP4.
    """
    from . import processing as proc
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, job_id)
        if job is None:
            raise ValueError("Tutorial not found")
        if job.status != "done":
            raise ValueError("The tutorial has not finished processing yet")
        if (job.duration_sec or 0) > MAX_VIDEO_GUIDE_SEC:
            mins = int(MAX_VIDEO_GUIDE_SEC // 60)
            raise ValueError(
                f"This recording is {round((job.duration_sec or 0) / 60)} min; video guides support up to "
                f"{mins} min per render. Split the tutorial or trim the source, then generate again.")
        try:
            _check_video_quota(db, actor or job.actor)
        except ValueError as e:
            raise ValueError(str(e))
        rows = list(db.scalars(select(M.VideoGuide).where(
            M.VideoGuide.tutorial_id == job_id).order_by(M.VideoGuide.created_at.desc())).all())
        import datetime as _dt
        for r in rows:
            if r.status in ("queued", "rendering"):
                try:
                    age = (_dt.datetime.now(_dt.timezone.utc) - r.created_at.replace(tzinfo=_dt.timezone.utc)).total_seconds()
                except Exception:
                    age = 10 ** 9
                if age < 1800:
                    return r, True
        if not force:
            fp = _video_fingerprint(db, job)
            for r in rows:
                if r.status == "ready" and all((r.provenance or {}).get(k) == v for k, v in fp.items()):
                    return r, True
        else:
            fp = _video_fingerprint(db, job)
        if scenes is not None:
            clean = validate_scene_plan(scenes, job.duration_sec or 0)
            fp = _video_fingerprint(db, job)
        max_ver = 0
        for r in rows:
            try:
                max_ver = max(max_ver, int(r.version_number or 0))
            except (TypeError, ValueError):
                pass
        vg = M.VideoGuide(tutorial_id=job_id, status="queued", progress=2, created_by=actor or job.actor,
                          version_number=max_ver + 1,
                          provenance={"trigger": "studio_scene_plan" if scenes is not None else "auto_guide_composition",
                                      **fp, "forced": bool(force)})
        if scenes is not None:
            vg.scenes = [{"step": c["step"], "title": c["title"], "caption": c["caption"],
                          "audio_start": c["audio_start"], "audio_end": c["audio_end"],
                          "visual": c.get("visual") or {}, "include": c.get("include", True)}
                         for c in clean]
        db.add(vg)
        db.commit()
        db.refresh(vg)
        proc.safe_record(db, "tutorial", job_id, "video_guide", "queued", operation="queue_video_guide",
                         actor=actor or job.actor, summary={"video_guide_id": vg.id})
        vid = vg.id
    finally:
        db.close()
    threading.Thread(target=run_video_guide_job, args=(vid,), daemon=True).start()
    db2 = SessionLocal()
    try:
        return db2.get(M.VideoGuide, vid), False
    finally:
        db2.close()


def _inspect_mp4(path: Path) -> dict:
    """Stream inventory for a rendered file via `ffmpeg -i` output.

    Uses the bundled ffmpeg binary (no ffprobe ships with it) with the
    same parsing style as tutorial.probe_video. Returns
    {video, audio, duration_sec, codec}.
    """
    import re as _re
    import subprocess as _sp
    out = {"video": False, "audio": False, "duration_sec": 0.0, "codec": ""}
    try:
        r = _sp.run([_ffmpeg(), "-i", str(path)], capture_output=True, timeout=60)
    except Exception:
        return out
    err = (r.stderr or b"").decode("utf-8", "replace")
    m = _re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        out["duration_sec"] = round(
            int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 2)
    vm = _re.search(r"Stream #\d+:\d+.*Video:\s*([a-z0-9_]+)", err)
    if vm:
        out["video"] = True
        out["codec"] = vm.group(1)
    if _re.search(r"Stream #\d+:\d+.*Audio:", err, _re.S):
        out["audio"] = True
    return out


def _validate_mp4(path: Path) -> dict:
    """Validate a rendered MP4 before it is marked ready. Raises RuntimeError.

    Checks: file exists and is non-empty; at least one video stream;
    a positive duration. Never lets a corrupt render become a 'ready'
    version. Audio presence is reported (not required — silent tutorials
    render valid silent videos).
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("Video render produced no file.")
    info = _inspect_mp4(path)
    if not info["video"]:
        raise RuntimeError("Rendered file has no video stream.")
    if info["duration_sec"] <= 0:
        raise RuntimeError("Rendered file has no measurable duration.")
    return {"duration_sec": info["duration_sec"],
            "streams": (["video"] + (["audio"] if info["audio"] else [])),
            "codec": info["codec"], "bytes": path.stat().st_size}


def _next_video_filename(video_dir: Path, job_id: str) -> tuple[Path, str]:
    """Unique per-version MP4 path. Timestamped for humans, with a random
    suffix so two renders in the same second never share a filename — each
    version keeps its own immutable MP4."""
    import datetime as _dt
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    unique = f"{stamp}-{_dt.datetime.now(_dt.timezone.utc).strftime('%f')}-{uuid.uuid4().hex[:8]}"
    return video_dir / f"guide-video-{unique}.mp4", f"data/tutorials/{job_id}/video/guide-video-{unique}.mp4"


def run_video_guide_job(vg_id: str) -> dict:
    """Background worker: plan scenes -> cut voiceover -> Remotion render -> asset."""
    from . import processing as proc
    proc.new_correlation()
    db = SessionLocal()
    try:
        vg = db.get(M.VideoGuide, vg_id)
        if vg is None:
            return {"ok": False}
        job = db.get(M.TutorialJob, vg.tutorial_id)
        if job is None:
            vg.status, vg.error = "error", "Tutorial not found"
            db.commit()
            return {"ok": False}
        actor = vg.created_by or job.actor
        vg.status, vg.progress = "rendering", 5
        db.commit()
        # Studio-edited scene plan (stored on the row by the scenes endpoint)
        # wins over AI planning: the render reproduces exactly the saved plan.
        stored = [s for s in (vg.scenes or []) if isinstance(s, dict) and s.get("title")]
        stored = [s for s in stored if s.get("include", True)]
        if stored:
            scenes = [{"step": int(s.get("step", i + 1)), "title": str(s.get("title", "")),
                       "caption": str(s.get("caption", "") or ""),
                       "audio_start": float(s.get("audio_start", s.get("start", 0)) or 0),
                       "audio_end": float(s.get("audio_end", s.get("end", 0)) or 0),
                       "visual": s.get("visual") or {}} for i, s in enumerate(stored)]
            plan = {"scenes": scenes, "model": "studio-scene-plan", "simulated": False,
                    "note": "Edited scene plan from Tutorial Studio; voiceover cut from the original recording."}
        else:
            with proc.timed() as t:
                plan = ai.plan_video_scenes(job.title, job.steps or [], job.objects or [],
                                            job.timed_segments or [],
                                            guide_markdown=job.guide_markdown or "",
                                            guide_format=job.guide_format or "",
                                            accepted_visuals=accepted_visual_hints(db, job.id))
            plan_ms = t.ms
            scenes = plan.get("scenes", [])
            if not scenes:
                raise RuntimeError("Could not plan video scenes from this tutorial.")
        if stored:
            plan_ms = 0
        # Every scene gets a real visual: accepted -> source-derived ->
        # Muse Image auto-generation (cached) -> deterministic graphic.
        # Empty panels are a defect, never a normal outcome.
        try:
            scenes, visual_report = resolve_scene_visuals(db, job, scenes, actor=actor)
        except Exception as e:
            visual_report = {"accepted": 0, "cached": 0, "source": 0,
                             "generated": 0, "graphic": 0, "empty": len(scenes),
                             "failures": [{"step": 0, "stage": "resolve",
                                           "status": f"{type(e).__name__}: {str(e)[:120]}"}]}
        vg.progress = 25
        db.commit()
        voiceover, voice_sec = cut_voiceover(job, scenes, db=db, actor=actor)
        vg.progress = 40
        db.commit()
        # Canonical step detail (expected result, tools) rides into the
        # composition so verify beats show verified procedure content.
        step_by_number = {}
        for st in (job.steps or []):
            try:
                step_by_number[int(st.get("step_number", 0))] = st
            except (TypeError, ValueError):
                continue
        for i, s in enumerate(scenes):
            base = step_by_number.get(int(s.get("step", s.get("step_number", i + 1)) or (i + 1)), {})
            for k in ("expected_result", "verification_notes", "required_tools"):
                if base.get(k) and not s.get(k):
                    s[k] = base[k]
        prop_diagnostics: list = []
        props = build_video_props(job, scenes, voiceover, voice_sec,
                                  diagnostics=prop_diagnostics)
        if prop_diagnostics:
            visual_report = {**visual_report,
                             "unresolved": prop_diagnostics,
                             "empty": len(prop_diagnostics)}
        paths = _video_paths(job.id)
        import json as _json
        paths["props"].write_text(_json.dumps(props), encoding="utf-8")
        out = _render_video(paths["props"], paths)
        vg.status, vg.progress = "validating", 85
        db.commit()
        checked = _validate_mp4(out) if out is not None and out.exists() else None
        if checked is None:
            raise RuntimeError("Video render produced no file.")
        final, storage_key = _next_video_filename(paths["dir"], job.id)
        out.replace(final)
        a = M.VisualAsset(tutorial_id=job.id, parent_id="", kind="video_guide", status="review",
                          storage_key=storage_key, mime_type="video/mp4",
                          width=VIDEO_W, height=VIDEO_H,
                          instruction=(f"Video guide for “{job.title}” ({len(scenes)} scenes, "
                                       f"{'original-voice cut' if voiceover else 'silent captions, no narration track'})."),
                          model=plan.get("model", ""), simulated=bool(plan.get("simulated", True)),
                          provenance={"scenes": len(scenes),
                                      "voiceover": ("original-recording-cut" if voiceover else
                                                    "silent-captions-only"),
                                      "voiceover_sec": round(voice_sec, 1),
                                      "model": plan.get("model", ""), "note": plan.get("note", ""),
                                      "warning": "AI-planned edit of the user's own recording. Verify narration matches the approved procedure before sharing."},
                          created_by=actor)
        db.add(a)
        db.flush()
        vg.status, vg.progress, vg.asset_id = "ready", 100, a.id
        vg.storage_key = storage_key
        vg.scenes = [{"step": int(s.get("step", s.get("step_number", i + 1)) or (i + 1)),
                      "title": str(s.get("title", "")),
                      "caption": str(s.get("caption", "") or ""),
                      "audio_start": float(s.get("audio_start", 0) or 0),
                      "audio_end": float(s.get("audio_end", 0) or 0),
                      "visual": s.get("visual") or {}, "include": True} for i, s in enumerate(scenes)]
        vg.simulated = bool(plan.get("simulated", True))
        vg.provenance = {**_video_fingerprint(db, job),
                         "model": plan.get("model", ""), "note": plan.get("note", ""),
                         "voiceover_sec": round(voice_sec, 1),
                         "voiceover": ("original-recording-cut" if voiceover else
                                       "silent-captions-only"),
                         "visuals": {k: v for k, v in visual_report.items() if k != "failures"},
                         "render": checked}
        db.commit()
        db.refresh(vg)
        proc.safe_record(db, "tutorial", job.id, "video_guide", "succeeded", operation="render_video_guide",
                         provider="meta", model=plan.get("model", ""), duration_ms=plan_ms, actor=actor,
                         summary={"video_guide_id": vg.id, "asset_id": a.id, "scenes": len(scenes),
                                  "simulated": bool(plan.get("simulated", True)),
                                  "visuals": {k: v for k, v in visual_report.items() if k != "failures"}})
        return {"ok": True, "video_guide_id": vg.id, "asset_id": a.id}
    except Exception as e:
        try:
            vg = db.get(M.VideoGuide, vg_id)
            if vg is not None:
                vg.status, vg.error = "error", f"{type(e).__name__}: {str(e)[:300]}"
                db.commit()
            proc.safe_record(db, "tutorial", getattr(vg, "tutorial_id", "-") if vg else "-",
                             "video_guide", "failed", operation="render_video_guide",
                             summary={"error_type": type(e).__name__, "error": str(e)[:300]})
        except Exception:
            pass
        return {"ok": False}
    finally:
        db.close()


def _video_project_dir() -> Path:
    repo_video = BASE.parent.parent / "video"
    if repo_video.is_dir():
        return repo_video
    return Path(__file__).resolve().parent.parent.parent / "video"


def _render_video(props_path: Path, paths: dict) -> Path | None:
    """Render via the vendored Remotion project (Node.js SSR, per remotion-saas skill).

    Uses a prebuilt bundle when VIDEO_BUNDLE_DIR (or repo video/bundle) exists;
    otherwise bundles on demand (slower first run, then cached). Raises on failure.
    """
    import shutil as _shutil
    import subprocess as _sp
    repo_video = _video_project_dir()
    bundle_dir = Path(os.getenv("VIDEO_BUNDLE_DIR", "") or str(repo_video / "bundle"))
    node = _shutil.which("node") or _shutil.which("node.exe")
    if not node:
        raise RuntimeError("Node.js is required to render video guides but was not found on PATH.")
    render_js = repo_video / "render.mjs"
    if not render_js.is_file():
        raise RuntimeError("Video renderer (video/render.mjs) is missing from this deployment.")
    out = paths["dir"] / "guide-video-render.mp4"
    progress = paths["progress"]
    try:
        if progress.exists():
            progress.unlink()
    except OSError:
        pass
    cmd = [node, str(render_js), "--bundle", str(bundle_dir), "--project", str(repo_video),
           "--props", str(props_path), "--out", str(out), "--progress", str(progress)]
    proc = _sp.run(cmd, capture_output=True, timeout=int(os.getenv("VIDEO_RENDER_TIMEOUT", "600")))
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stderr.decode("utf-8", "replace") or proc.stdout.decode("utf-8", "replace"))[-800:]
        raise RuntimeError(f"Video render failed. {tail}")
    return out
