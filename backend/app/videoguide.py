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
from pathlib import Path

from sqlalchemy import select

from . import ai
from .db import SessionLocal
from . import models as M
from .tutorial import BASE, _ffmpeg

VIDEO_MAX_SEC = int(os.getenv("VIDEO_GUIDE_MAX_SEC", "180"))
VIDEO_QUOTA_PER_DAY = int(os.getenv("MAX_VIDEO_OPS_PER_DAY", "10"))
VIDEO_FPS = 30
VIDEO_W, VIDEO_H = 1280, 720


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
    d = BASE / "data" / "tutorials" / job_id / "video"
    d.mkdir(parents=True, exist_ok=True)
    return {"dir": d, "voiceover": d / "voiceover.wav", "props": d / "props.json",
            "progress": d / "render-progress.json", "output": d / "guide-video-render.mp4"}


def cut_voiceover(job: M.TutorialJob, scenes: list[dict]) -> tuple[Path | None, float]:
    """Cut per-scene narration from the USER's own recording; concat to one track.

    Returns (voiceover_wav_path_or_None, total_seconds). Slices come from
    timed transcript ranges overlapping each step — the voiceover is a cut of
    the original audio, never synthesized. A 0.4s silence tail pads each
    scene so captions don't clip.
    """
    source = BASE / job.video_storage_key
    if not source.is_file():
        return None, 0.0
    total = sum(max(0.0, float(s.get("audio_end", 0)) - float(s.get("audio_start", 0))) for s in scenes)
    if total <= 0:
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
            return None, 0.0
        lst = vdir / "concat.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        out = _video_paths(job.id)["voiceover"]
        r = _sp.run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                     "-c:a", "pcm_s16le", str(out)], capture_output=True, timeout=180)
        if r.returncode != 0 or not out.exists():
            return None, 0.0
        _ = job_dir  # voiceover lives under the video/ subdir by design
        return out, total + 0.4 * len(scenes)
    except Exception:
        return None, 0.0


def build_video_props(job: M.TutorialJob, scenes: list[dict], voiceover: Path | None,
                      voiceover_sec: float) -> dict:
    """Props for the Remotion ProcedureVideo composition (Zod-validated at render).

    Images resolve to absolute local files (server render) — no URLs, no
    network at render time. Missing visuals stay null and the composition
    renders a title-only scene instead of inventing imagery.
    """
    job_dir = BASE / "data" / "tutorials" / job.id
    fps = VIDEO_FPS
    frame = int(1.5 * fps)  # title card
    out_scenes = []
    for s in scenes:
        dur = max(1.0, float(s.get("audio_end", 0)) - float(s.get("audio_start", 0)) + 0.4)
        img = None
        vis = s.get("visual") or {}
        if vis.get("name"):
            p = job_dir / Path(str(vis["name"])).name
            if p.is_file():
                img = str(p)
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


def start_video_guide(job_id: str, actor: str = "", force: bool = False) -> tuple[M.VideoGuide, bool]:
    """Queue (or reuse) a video-guide render. Returns (row, duplicate).

    In-flight renders are reused; a finished render is reused when the
    canonical procedure hasn't changed since (compare canonical hash).
    Pass force=True (the UI Regenerate button) to render afresh.
    """
    from . import processing as proc
    db = SessionLocal()
    try:
        job = db.get(M.TutorialJob, job_id)
        if job is None:
            raise ValueError("Tutorial not found")
        if job.status != "done":
            raise ValueError("The tutorial has not finished processing yet")
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
            from .tutorial import _canonical_hash
            canon = _canonical_hash(job.steps or [])
            for r in rows:
                if r.status == "ready" and (r.provenance or {}).get("canonical_hash") == canon:
                    return r, True
        else:
            from .tutorial import _canonical_hash
            canon = _canonical_hash(job.steps or [])
        total = sum(max(0.0, float(s.get("end", 0)) - float(s.get("start", 0))) for s in (job.steps or []))
        if total > VIDEO_MAX_SEC:
            raise ValueError(f"This tutorial is {total:.0f}s — video guides are capped at {VIDEO_MAX_SEC}s. Record a shorter tutorial for video output.")
        vg = M.VideoGuide(tutorial_id=job_id, status="queued", progress=2, created_by=actor or job.actor,
                          provenance={"trigger": "user_request", "canonical_hash": canon, "forced": bool(force)})
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
        with proc.timed() as t:
            plan = ai.plan_video_scenes(job.title, job.steps or [], job.objects or [],
                                        job.timed_segments or [])
        scenes = plan.get("scenes", [])
        if not scenes:
            raise RuntimeError("Could not plan video scenes from this tutorial.")
        vg.progress = 25
        db.commit()
        voiceover, voice_sec = cut_voiceover(job, scenes)
        vg.progress = 40
        db.commit()
        props = build_video_props(job, scenes, voiceover, voice_sec)
        paths = _video_paths(job.id)
        import json as _json
        paths["props"].write_text(_json.dumps(props), encoding="utf-8")
        out = _render_video(paths["props"], paths)
        if out is None or not out.exists():
            raise RuntimeError("Video render produced no file.")
        import datetime as _dt
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        final = paths["dir"] / f"guide-video-{stamp}.mp4"
        out.replace(final)
        storage_key = f"data/tutorials/{job.id}/video/guide-video-{stamp}.mp4"
        a = M.VisualAsset(tutorial_id=job.id, parent_id="", kind="video_guide", status="review",
                          storage_key=storage_key, mime_type="video/mp4",
                          width=VIDEO_W, height=VIDEO_H,
                          instruction=f"Video guide for “{job.title}” ({len(scenes)} scenes, original-voice cut).",
                          model=plan.get("model", ""), simulated=bool(plan.get("simulated", True)),
                          provenance={"scenes": len(scenes), "voiceover": "original-recording-cut",
                                      "voiceover_sec": round(voice_sec, 1),
                                      "model": plan.get("model", ""), "note": plan.get("note", ""),
                                      "warning": "AI-planned edit of the user's own recording. Verify narration matches the approved procedure before sharing."},
                          created_by=actor)
        db.add(a)
        db.flush()
        vg.status, vg.progress, vg.asset_id = "ready", 100, a.id
        vg.storage_key = storage_key
        vg.scenes = [{"step": s["step"], "title": s["title"], "caption": s["caption"]} for s in props["scenes"]]
        vg.simulated = bool(plan.get("simulated", True))
        vg.provenance = {"model": plan.get("model", ""), "note": plan.get("note", ""),
                         "voiceover_sec": round(voice_sec, 1),
                     "canonical_hash": (vg.provenance or {}).get("canonical_hash", "")}
        db.commit()
        db.refresh(vg)
        proc.safe_record(db, "tutorial", job.id, "video_guide", "succeeded", operation="render_video_guide",
                         provider="meta", model=plan.get("model", ""), duration_ms=t.ms, actor=actor,
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
