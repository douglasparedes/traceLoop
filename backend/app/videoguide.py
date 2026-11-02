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


def build_video_props(job: M.TutorialJob, scenes: list[dict], voiceover: Path | None,
                      voiceover_sec: float) -> dict:
    """Props for the Remotion ProcedureVideo composition (Zod-validated at render).

    Images resolve to absolute local files (server render) — no URLs, no
    network at render time. Missing visuals stay null and the composition
    renders a title-only scene instead of inventing imagery.
    """
    from . import storage as _storage
    job_dir = _storage.media_root() / "tutorials" / job.id
    fps = VIDEO_FPS
    frame = int(1.5 * fps)  # title card
    out_scenes = []
    for s in scenes:
        dur = max(1.0, float(s.get("audio_end", 0)) - float(s.get("audio_start", 0)) + 0.4)
        img = None
        vis = s.get("visual") or {}
        if vis.get("name"):
            # Illustrations live directly under the job dir; accepted visual
            # assets live under visuals/. Both are real files — check each.
            for cand in (job_dir / Path(str(vis["name"])).name,
                         job_dir / "visuals" / Path(str(vis["name"])).name):
                if cand.is_file():
                    img = str(cand)
                    break
        cap_text = str(s.get("caption") or s.get("narration") or "")
        out_scenes.append({
            "step": int(s.get("step_number", len(out_scenes) + 1)),
            "title": str(s.get("title", "")),
            "caption": cap_text,
            "image": img,
            "startFrame": frame,
            "durationFrames": int(round(dur * fps)),
        })
        frame += int(round(dur * fps))
    total_frames = frame + int(0.5 * fps)
    return {"title": job.title, "fps": fps, "width": VIDEO_W, "height": VIDEO_H,
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
        vg.progress = 25
        db.commit()
        voiceover, voice_sec = cut_voiceover(job, scenes, db=db, actor=actor)
        vg.progress = 40
        db.commit()
        props = build_video_props(job, scenes, voiceover, voice_sec)
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
                         "render": checked}
        db.commit()
        db.refresh(vg)
        proc.safe_record(db, "tutorial", job.id, "video_guide", "succeeded", operation="render_video_guide",
                         provider="meta", model=plan.get("model", ""), duration_ms=plan_ms, actor=actor,
                         summary={"video_guide_id": vg.id, "asset_id": a.id, "scenes": len(scenes),
                                  "simulated": bool(plan.get("simulated", True))})
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
