import asyncio
import hashlib
import json as _json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from .db import Base, engine, get_db
from . import models as M, schemas as S
from . import ai
from . import live as live_mod
from . import tutorial as tut

Base.metadata.create_all(bind=engine)

# Lightweight additive migrations for the local SQLite prototype (no Alembic).
with engine.begin() as _conn:
    from sqlalchemy import inspect as _inspect, text as _text
    _insp = _inspect(_conn)
    for _table, _col, _type in (("live_chunks", "transcript", "TEXT DEFAULT ''"), ("live_recordings", "transcript", "TEXT DEFAULT ''"),
                                ("live_chunks", "start_ms", "INTEGER DEFAULT 0"), ("live_chunks", "end_ms", "INTEGER DEFAULT 0"),
                                ("live_chunks", "prompt_source", "TEXT DEFAULT ''"), ("live_chunks", "speech_phrase", "TEXT DEFAULT ''"),
                                ("tutorial_jobs", "draft_procedure_id", "VARCHAR DEFAULT ''"),
                                ("tutorial_jobs", "draft_version_id", "VARCHAR DEFAULT ''"),
                                ("tutorial_jobs", "guide_format", "VARCHAR DEFAULT ''"),
                                ("tutorial_jobs", "format_source", "VARCHAR DEFAULT ''"),
                                ("tutorial_jobs", "format_rationale", "TEXT DEFAULT ''"),
                                ("guide_snapshots", "guide_format", "VARCHAR DEFAULT ''"),
                                ("guide_snapshots", "format_source", "VARCHAR DEFAULT ''"),
                                ("guide_snapshots", "format_rationale", "TEXT DEFAULT ''"),
                                ("guide_snapshots", "content_revision", "INTEGER DEFAULT 0"),
                                ("visual_assets", "idempotency_key", "VARCHAR DEFAULT ''"),
                                ("procedure_steps", "start_sec", "FLOAT"),
                                ("procedure_steps", "end_sec", "FLOAT"),
                                ("tutorial_jobs", "equipment_name", "VARCHAR DEFAULT ''"),
                                ("tutorial_jobs", "task_description", "TEXT DEFAULT ''"),
                                ("tutorial_jobs", "context_notes", "TEXT DEFAULT ''"),
                                ("tutorial_jobs", "content_revision", "INTEGER DEFAULT 1"),
                                ("tutorial_jobs", "transcript_original", "TEXT DEFAULT ''"),
                                ("tutorial_jobs", "transcript_corrected", "TEXT DEFAULT ''"),
                                ("video_guides", "version_number", "INTEGER DEFAULT 1")):
        if _insp.has_table(_table) and _col not in {c["name"] for c in _insp.get_columns(_table)}:
            _conn.execute(_text(f"ALTER TABLE {_table} ADD COLUMN {_col} {_type}"))

app = FastAPI(title="TraceLoop FieldGuard API", version="0.1.0")

import os as _os

# Same-origin in production (frontend served by this app); CORS only matters
# for local dev servers. Override with CORS_ORIGINS (comma-separated).
_cors_origins = [o.strip() for o in _os.getenv(
    "CORS_ORIGINS",
    "https://knowloop.online,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"])

MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_IMG_BYTES = 8 * 1024 * 1024
ROLES = {"technician", "expert", "reviewer", "admin"}


def actor(x_user: str = Header(default="demo-tech"), x_role: str = Header(default="technician")):
    role = x_role if x_role in ROLES else "technician"
    return {"id": x_user, "role": role}


def audit(db: Session, who: str, action: str, etype: str, eid: str, detail=None):
    db.add(M.AuditLog(actor=who, action=action, entity_type=etype, entity_id=eid, detail=detail or {}))


def ver_out(v: M.ProcedureVersion) -> dict:
    return {
        "id": v.id, "procedure_id": v.procedure_id, "version_number": v.version_number,
        "status": v.status, "summary": v.summary, "prerequisites": v.prerequisites,
        "source_evidence": v.source_evidence, "ai_model": v.ai_model, "ai_simulated": bool(v.ai_simulated),
        "created_by": v.created_by, "reviewed_by": v.reviewed_by,
        "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
        "review_comment": v.review_comment, "created_at": v.created_at.isoformat(),
        "steps": [{"id": s.id, "step_order": s.step_order, "title": s.title, "instruction": s.instruction,
                   "expected_result": s.expected_result, "required_tools": s.required_tools or [],
                   "evidence_refs": s.evidence_refs or [], "visual_refs": s.visual_refs or [],
                   "verification_notes": s.verification_notes,
                   "start_sec": s.start_sec, "end_sec": s.end_sec} for s in v.steps],
    }


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.scalar(select(1)); db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "ai_live": ai.live_enabled(), "models": {"spark": ai.SPARK_MODEL, "segment": ai.SAM_MODEL, "voice": ai.VOICE_MODEL}}


@app.get("/api/auth/status")
def auth_status():
    from . import auth as _auth
    return {"auth_enabled": _auth.enabled()}


@app.post("/api/auth/login")
async def auth_login(request: Request):
    from . import auth as _auth
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not _auth.enabled():
        return {"ok": True, "token": "", "demo_open": True}
    if _auth.check_password(str(body.get("password", ""))):
        return {"ok": True, "token": _auth.create_token()}
    raise HTTPException(401, "Wrong team passphrase")


@app.get("/api/auth/me")
def auth_me(request: Request):
    from . import auth as _auth
    if not _auth.enabled():
        return {"ok": True, "demo_open": True}
    if _auth.verify_token(request.headers.get("X-Auth-Token", "")):
        return {"ok": True}
    raise HTTPException(401, "Not signed in")


import re as _re_gate

# Headerless media: <video>/<img>/<a download> tags cannot send X-Auth-Token,
# so these GETs carry a ?token= bearer instead, verified endpoint-side (403 on
# mismatch). The evidence image URL is an unguessable UUID, as it was before
# the team gate existed.
MEDIA_GATE_EXEMPT_RE = _re_gate.compile(
    r"^/api/(tutorial/[^/]+/(video|video-guide/file|bundle\.zip|illustrations/[^/]+|diagnostics/frame/[^/]+)"
    r"|visuals/[^/]+/file"
    r"|live-recordings/[^/]+/chunks/[^/]+/video"
    r"|evidence/[^/]+/image)$")


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    from . import auth as _auth
    # Headerless media: <video>/<img>/<a download> tags cannot send
    # X-Auth-Token, so these GETs carry a ?token= bearer instead, verified
    # endpoint-side (403 on mismatch). The evidence image URL is an
    # unguessable UUID, as it was before the team gate existed.
    _MEDIA_RE = MEDIA_GATE_EXEMPT_RE
    if _auth.enabled() and request.url.path.startswith("/api/") and request.url.path not in (
            "/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/me"):
        # /api/auth/me answers 401 itself when the token is missing/invalid.
        if not (request.method in ("GET", "HEAD") and _MEDIA_RE.match(request.url.path)):
            if not _auth.verify_token(request.headers.get("X-Auth-Token", "")):
                return JSONResponse({"detail": "Not signed in — enter the team passphrase."}, status_code=401)
    return await call_next(request)


@app.get("/api/assets")
def list_assets(db: Session = Depends(get_db)):
    return [{"id": a.id, "name": a.name, "asset_type": a.asset_type, "model": a.model, "description": a.description}
            for a in db.scalars(select(M.Asset)).all()]


@app.post("/api/assets")
def create_asset(body: dict, db: Session = Depends(get_db), who=Depends(actor)):
    a = M.Asset(name=body.get("name", "Untitled asset"), asset_type=body.get("asset_type", "training-assembly"),
                manufacturer=body.get("manufacturer"), model=body.get("model"), description=body.get("description"))
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id, "name": a.name}


@app.post("/api/capture-sessions")
def create_capture(body: S.CaptureCreate, db: Session = Depends(get_db), who=Depends(actor)):
    asset_id = body.asset_id
    if asset_id and not db.get(M.Asset, asset_id): raise HTTPException(404, "Asset not found")
    if body.manual_id and not db.get(M.Manual, body.manual_id): raise HTTPException(404, "Manual not found")
    if not asset_id and body.asset_name:
        a = M.Asset(name=body.asset_name); db.add(a); db.flush(); asset_id = a.id
    c = M.CaptureSession(asset_id=asset_id, title=body.title, task_description=body.task_description,
                         category=body.category, manual_id=body.manual_id, tags=body.tags, notes=body.notes, created_by=who["id"])
    db.add(c); db.flush(); audit(db, who["id"], "capture.create", "capture_session", c.id)
    db.commit(); db.refresh(c)
    return {"id": c.id, "title": c.title, "status": c.status}


@app.get("/api/capture-sessions")
def list_captures(db: Session = Depends(get_db)):
    return [{"id": c.id, "title": c.title, "status": c.status, "task_description": c.task_description,
             "transcript_corrected": c.transcript_corrected, "created_at": c.created_at.isoformat()}
            for c in db.scalars(select(M.CaptureSession).order_by(M.CaptureSession.created_at.desc())).all()]


@app.get("/api/capture-sessions/{cid}")
def get_capture(cid: str, db: Session = Depends(get_db)):
    c = db.get(M.CaptureSession, cid)
    if not c: raise HTTPException(404, "Capture session not found")
    ev = db.scalars(select(M.Evidence).where(M.Evidence.capture_session_id == cid)).all()
    return {"id": c.id, "title": c.title, "task_description": c.task_description, "status": c.status,
            "transcript_original": c.transcript_original, "transcript_corrected": c.transcript_corrected,
            "evidence": [{"id": e.id, "evidence_type": e.evidence_type, "description": e.description,
                          "text_content": e.text_content, "source_reference": e.source_reference} for e in ev]}


@app.put("/api/capture-sessions/{cid}/transcript")
def save_transcript(cid: str, body: S.TranscriptSave, db: Session = Depends(get_db), who=Depends(actor)):
    c = db.get(M.CaptureSession, cid)
    if not c: raise HTTPException(404, "Capture session not found")
    if body.transcript_original: c.transcript_original = body.transcript_original
    c.transcript_corrected = body.transcript_corrected
    db.commit()
    return {"ok": True}


@app.websocket("/api/voice/realtime")
async def voice_realtime(ws: WebSocket):
    """Proxy browser PCM <-> Muse Voice realtime. Key never leaves the server.

    Client protocol: binary frames of mono 16-bit PCM @24kHz; text
    {"type":"endStream"} to finish. Server forwards Muse transcript /
    speechComplete events verbatim.
    """
    await ws.accept()
    from . import auth as _auth
    if _auth.enabled() and not _auth.verify_token(dict(ws.query_params).get("token", "")):
        await ws.send_json({"type": "error", "simulated": True,
                            "message": "Not signed in — enter the team passphrase and try again."})
        await ws.close()
        return
    if not ai.live_enabled():
        await ws.send_json({"type": "error", "simulated": True,
                            "message": "No META_API_KEY configured; live transcription unavailable. Use Stop-and-transcribe or type the transcript."})
        await ws.close()
        return
    import websockets

    session_id = str(uuid.uuid4())
    uri = f"wss://api.meta.ai/v1/asr/realtime?sessionId={session_id}"
    try:
        async with websockets.connect(uri, open_timeout=20, max_size=8 * 1024 * 1024) as meta:
            await meta.send(_json.dumps({
                "authorization": {"accessToken": f"Bearer {ai.META_API_KEY}"},
                "audioEncoding": "PCM_24KHZ", "model": ai.VOICE_MODEL,
                "mode": "PUSH_TO_TALK", "partialMode": "CUMULATIVE", "emitAudioProgress": False,
            }))
            ack = _json.loads(await asyncio.wait_for(meta.recv(), timeout=20))
            if "sessionId" not in ack:
                await ws.send_json({"type": "error", "message": f"Voice handshake failed: {ack}"})
                await ws.close()
                return
            await ws.send_json({"type": "ready", "sessionId": ack["sessionId"], "model": ai.VOICE_MODEL})

            async def client_to_meta():
                # Pace forwarding to realtime: never run more than ~1s ahead
                # of wall clock, or Meta closes with 1008 "backlog too large".
                _loop = asyncio.get_running_loop()
                _pace_start = _loop.time()
                _bytes_sent = 0
                try:
                    while True:
                        msg = await ws.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("bytes") is not None:
                            _bytes_sent += len(msg["bytes"])
                            _ahead = (_bytes_sent / 48000.0) - (_loop.time() - _pace_start) - 1.0
                            if _ahead > 0:
                                await asyncio.sleep(_ahead)
                            try:
                                await meta.send(msg["bytes"])
                            except Exception:
                                break  # Meta closed: stop forwarding quietly
                        elif msg.get("text"):
                            try:
                                ctl = _json.loads(msg["text"])
                            except ValueError:
                                continue
                            if ctl.get("type") == "endStream":
                                try: await meta.send(_json.dumps({"type": "endStream"}))
                                except Exception: break
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass
                finally:
                    try:
                        if meta.state.name == "OPEN":
                            await meta.send(_json.dumps({"type": "endStream"}))
                    except Exception: pass

            async def meta_to_client():
                try:
                    async for raw in meta:
                        if isinstance(raw, bytes):
                            continue
                        await ws.send_text(raw)
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_meta()), asyncio.create_task(meta_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in done:
                try: t.exception()
                except Exception: pass
    except Exception as e:
        import logging
        logging.getLogger("fieldguard.voice").warning("voice realtime session %s failed: %s: %s", session_id, type(e).__name__, str(e)[:200])
        try:
            await ws.send_json({"type": "error", "message": f"Live transcription failed ({type(e).__name__}). Use Stop-and-transcribe or type the transcript."})
            await ws.close()
        except Exception:
            pass


@app.post("/api/capture-sessions/{cid}/transcribe")
async def transcribe(cid: str, file: UploadFile = File(...), db: Session = Depends(get_db), who=Depends(actor)):
    c = db.get(M.CaptureSession, cid)
    if not c: raise HTTPException(404, "Capture session not found")
    data = await file.read()
    if len(data) > 25 * 1024 * 1024: raise HTTPException(413, "Audio file too large (max 25 MB)")
    result = await run_in_threadpool(ai.transcribe_audio, file.filename or "audio.webm", data)
    if result.get("error"): raise HTTPException(502, result["error"])
    if result.get("simulated"):
        # Never wipe an existing transcript with a simulated placeholder.
        return {"text": c.transcript_corrected or c.transcript_original or "", "simulated": True, "note": result.get("note", "")}
    c.transcript_original = result["text"]
    if not c.transcript_corrected: c.transcript_corrected = result["text"]
    ev = M.Evidence(capture_session_id=cid, evidence_type="audio", text_content=result["text"],
                    source_reference=file.filename or "recording", description="Voice recording", created_by=who["id"])
    db.add(ev); db.commit()
    return {"text": result["text"], "simulated": result.get("simulated", False), "note": result.get("note", "")}


@app.post("/api/capture-sessions/{cid}/evidence")
def add_evidence(cid: str, body: S.EvidenceCreate, db: Session = Depends(get_db), who=Depends(actor)):
    c = db.get(M.CaptureSession, cid)
    if not c: raise HTTPException(404, "Capture session not found")
    e = M.Evidence(capture_session_id=cid, evidence_type=body.evidence_type, text_content=body.text_content,
                   description=body.description, source_reference=body.source_reference, created_by=who["id"])
    db.add(e); db.commit(); db.refresh(e)
    return {"id": e.id}


@app.post("/api/capture-sessions/{cid}/image")
async def add_image(cid: str, file: UploadFile = File(...), description: str = Form(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    c = db.get(M.CaptureSession, cid)
    if not c: raise HTTPException(404, "Capture session not found")
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "Only JPEG, PNG or WebP images are supported")
    data = await file.read()
    if len(data) > MAX_IMG_BYTES: raise HTTPException(413, "Image too large (max 8 MB)")
    digest = hashlib.sha256(data).hexdigest()[:16]
    e = M.Evidence(capture_session_id=cid, evidence_type="image", description=description,
                   source_reference=file.filename or "photo", created_by=who["id"], extra={"sha256_16": digest, "size": len(data)})
    db.add(e); db.flush()
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(file.content_type or "", ".jpg")
    store_dir = Path(__file__).resolve().parent.parent / "data" / "evidence"
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / f"{e.id}{suffix}").write_bytes(data)
    e.storage_key = f"data/evidence/{e.id}{suffix}"
    db.commit(); db.refresh(e)
    return {"id": e.id, "size": len(data)}


@app.get("/api/manuals")
def list_manuals(db: Session = Depends(get_db)):
    out = []
    for m in db.scalars(select(M.Manual).order_by(M.Manual.created_at.desc())).all():
        chunks = db.scalar(select(func.count()).select_from(M.ManualChunk).where(M.ManualChunk.manual_id == m.id)) or 0
        out.append({"id": m.id, "title": m.title, "model": m.model, "document_version": m.document_version,
                    "file_size": m.file_size, "chunks": chunks, "created_at": m.created_at.isoformat()})
    return out


@app.post("/api/manuals")
async def upload_manual(file: UploadFile = File(...), title: str = Form(default=""), model: str = Form(default=""),
                        db: Session = Depends(get_db), who=Depends(actor)):
    if file.content_type != "application/pdf": raise HTTPException(415, "Only PDF manuals are supported")
    data = await file.read()
    if len(data) > MAX_PDF_BYTES: raise HTTPException(413, "PDF too large (max 15 MB)")
    text = ""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        text = ""
    m = M.Manual(title=title or (file.filename or "Manual"), model=model or None,
                 storage_key=file.filename or "manual.pdf", mime_type="application/pdf",
                 file_size=len(data), checksum=hashlib.sha256(data).hexdigest(), extracted_text=text, created_by=who["id"])
    db.add(m); db.flush()
    words = text.split()
    size = 220
    for i in range(0, max(len(words), 1), size):
        chunk = " ".join(words[i:i + size])
        if chunk: db.add(M.ManualChunk(manual_id=m.id, chunk_index=i // size, text=chunk,
                                       extraction_status="ok" if text else "no-text"))
    audit(db, who["id"], "manual.upload", "manual", m.id, {"size": len(data)})
    db.commit()
    return {"id": m.id, "title": m.title, "extracted_chars": len(text), "searchable": bool(text.strip())}


@app.get("/api/manuals/search")
def search_manuals(q: str = "", db: Session = Depends(get_db)):
    if not q.strip(): return []
    terms = [t.lower() for t in q.split() if len(t) > 1]
    results = []
    for ch in db.scalars(select(M.ManualChunk)).all():
        low = ch.text.lower()
        score = sum(low.count(t) for t in terms)
        if score:
            man = db.get(M.Manual, ch.manual_id)
            idx = min((low.find(t) for t in terms if t in low), default=0)
            results.append({"manual_id": ch.manual_id, "manual_title": man.title if man else "",
                            "page_number": ch.page_number, "chunk_index": ch.chunk_index,
                            "snippet": ch.text[max(0, idx - 80):idx + 220], "score": score})
    return sorted(results, key=lambda r: -r["score"])[:20]


@app.post("/api/procedures/draft")
def make_draft(body: S.DraftRequest, db: Session = Depends(get_db), who=Depends(actor)):
    c = db.get(M.CaptureSession, body.capture_session_id)
    if not c: raise HTTPException(404, "Capture session not found")
    ev_ids = [e.id for e in db.scalars(select(M.Evidence).where(M.Evidence.capture_session_id == c.id)).all()]
    result = ai.generate_draft(c.title, c.task_description, c.transcript_corrected or c.transcript_original,
                               body.manual_excerpt, ev_ids)
    d = result["draft"]
    proc = M.Procedure(title=d["title"], asset_id=c.asset_id, created_by=who["id"])
    db.add(proc); db.flush()
    ver = M.ProcedureVersion(procedure_id=proc.id, version_number=1, status="draft", summary=d["summary"],
                             prerequisites=d["prerequisites"], ai_model=result["model"],
                             ai_simulated=1 if result["simulated"] else 0, created_by=who["id"],
                             source_evidence={"capture_session_id": c.id, "evidence_ids": ev_ids,
                                              "uncertainties": d["uncertainties"], "missing_information": d["missing_information"],
                                              "safety_notes": d["safety_notes"], "ai_note": result.get("note", "")})
    db.add(ver); db.flush()
    for i, s in enumerate(d["steps"], start=1):
        db.add(M.ProcedureStep(procedure_version_id=ver.id, step_order=i, title=s["title"], instruction=s["instruction"],
                               expected_result=s.get("expected_result"), required_tools=s.get("required_tools", []),
                               evidence_refs=s.get("evidence_refs", []), visual_refs=s.get("visual_refs", []),
                               verification_notes=s.get("verification_notes")))
    c.status = "draft-generated"
    audit(db, who["id"], "procedure.draft", "procedure_version", ver.id, {"simulated": result["simulated"]})
    db.commit(); db.refresh(ver)
    return ver_out(ver)


@app.get("/api/procedures")
def list_procedures(db: Session = Depends(get_db)):
    out = []
    for p in db.scalars(select(M.Procedure).order_by(M.Procedure.updated_at.desc())).all():
        vers = sorted(p.versions, key=lambda v: v.version_number)
        approved = [v for v in vers if v.status == "approved"]
        out.append({"id": p.id, "title": p.title, "favorite": bool(p.favorite),
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                    "asset_type": p.asset_type,
                    "versions": [{"id": v.id, "version_number": v.version_number, "status": v.status} for v in vers],
                    "approved_version_id": approved[-1].id if approved else None,
                    "has_pending_review": any(v.status == "pending_review" for v in vers)})
    return out


@app.get("/api/procedure-versions/{vid}/evidence")
def version_evidence(vid: str, db: Session = Depends(get_db)):
    """Source evidence linked to a version (via its capture session), with
    the latest SAM segmentation per image so guided jobs and reviewers can
    show the correct highlight for the correct image."""
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    cap_id = (v.source_evidence or {}).get("capture_session_id")
    tut_id = (v.source_evidence or {}).get("tutorial_id")
    items = []
    seen: set[str] = set()

    def add_item(e):
        if e.id in seen:
            return
        seen.add(e.id)
        seg_out = None
        seg = db.scalar(select(M.SegmentationResult).where(M.SegmentationResult.evidence_id == e.id).order_by(M.SegmentationResult.created_at.desc()))
        if seg is not None:
            seg_out = {"id": seg.id, "geometry": seg.normalized_geometry, "simulated": bool(seg.simulated),
                       "status": seg.result_status, "prompt": seg.prompt_text, "model": seg.provider_model}
        has_file = bool(e.storage_key) and (Path(__file__).resolve().parent.parent / e.storage_key).is_file()
        items.append({"id": e.id, "evidence_type": e.evidence_type, "description": e.description,
                      "text_content": e.text_content, "source_reference": e.source_reference,
                      "image_url": f"/api/evidence/{e.id}/image" if e.evidence_type == "image" and has_file else None,
                      "segmentation": seg_out})

    if cap_id:
        for e in db.scalars(select(M.Evidence).where(M.Evidence.capture_session_id == cap_id)).all():
            add_item(e)
    if tut_id:
        for e in db.scalars(select(M.Evidence).where(M.Evidence.source_reference == f"tutorial:{tut_id}")).all():
            add_item(e)
    return {"version_id": vid, "capture_session_id": cap_id, "tutorial_id": tut_id, "evidence": items}


@app.get("/api/evidence/{eid}/image")
def evidence_image(eid: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    e = db.get(M.Evidence, eid)
    if not e or e.evidence_type != "image" or not e.storage_key: raise HTTPException(404, "Evidence image not found")
    path = Path(__file__).resolve().parent.parent / e.storage_key
    if not path.is_file(): raise HTTPException(404, "Evidence image file missing")
    media = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/procedure-versions/{vid}")
def get_version(vid: str, db: Session = Depends(get_db)):
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    return ver_out(v)


@app.put("/api/procedure-versions/{vid}")
def edit_version(vid: str, body: S.VersionEdit, db: Session = Depends(get_db), who=Depends(actor)):
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    if v.status == "approved": raise HTTPException(409, "Approved versions are immutable. Create a new draft revision instead.")
    if v.status not in ("draft", "rejected"): raise HTTPException(409, f"Cannot edit a version in status '{v.status}'")
    if body.summary is not None: v.summary = body.summary
    if body.prerequisites is not None: v.prerequisites = body.prerequisites
    if body.steps is not None:
        for s in list(v.steps): db.delete(s)
        db.flush()
        for i, s in enumerate(body.steps, start=1):
            db.add(M.ProcedureStep(procedure_version_id=v.id, step_order=i, title=s.title, instruction=s.instruction,
                                   expected_result=s.expected_result, required_tools=s.required_tools,
                                   evidence_refs=s.evidence_refs, visual_refs=s.visual_refs,
                                   verification_notes=s.verification_notes,
                                   start_sec=s.start_sec, end_sec=s.end_sec))
    db.commit(); db.refresh(v)
    return ver_out(v)


@app.post("/api/procedure-versions/{vid}/new-revision")
def new_revision(vid: str, db: Session = Depends(get_db), who=Depends(actor)):
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    if v.status in ("pending_review", "superseded"): raise HTTPException(409, f"Cannot create a revision from a version in status '{v.status}'")
    nxt = (db.scalar(select(func.max(M.ProcedureVersion.version_number)).where(M.ProcedureVersion.procedure_id == v.procedure_id)) or 0) + 1
    nv = M.ProcedureVersion(procedure_id=v.procedure_id, version_number=nxt, status="draft", summary=v.summary,
                            prerequisites=v.prerequisites, source_evidence=v.source_evidence, created_by=who["id"])
    db.add(nv); db.flush()
    for s in v.steps:
        db.add(M.ProcedureStep(procedure_version_id=nv.id, step_order=s.step_order, title=s.title, instruction=s.instruction,
                               expected_result=s.expected_result, required_tools=s.required_tools or [],
                               evidence_refs=s.evidence_refs or [], visual_refs=s.visual_refs or [],
                               verification_notes=s.verification_notes, start_sec=s.start_sec, end_sec=s.end_sec))
    db.commit(); db.refresh(nv)
    return ver_out(nv)


@app.post("/api/procedure-versions/{vid}/resolve-conflict")
def resolve_conflict(vid: str, body: dict, db: Session = Depends(get_db), who=Depends(actor)):
    """Apply canonical text to chosen conflicted steps (expert keeps the rest).

    Only editable versions. Each listed step takes the title/instruction from
    the stored canonical snapshot; unresolved steps stay exactly as the
    expert left them. When nothing remains flagged, the sync action flips
    to "resolved".
    """
    v = db.get(M.ProcedureVersion, vid)
    if not v:
        raise HTTPException(404, "Version not found")
    if v.status not in ("draft", "rejected"):
        raise HTTPException(409, "Only editable drafts can resolve conflicts. Create a new revision instead.")
    try:
        orders = [int(x) for x in ((body or {}).get("step_orders") or [])]
    except (TypeError, ValueError):
        raise HTTPException(422, "step_orders must be a list of step numbers")
    canon = {int(c.get("n", 0)): c for c in (v.source_evidence or {}).get("canonical_steps", []) if isinstance(c, dict)}
    applied: list[int] = []
    for s in v.steps:
        if s.step_order in orders and s.step_order in canon:
            s.title = str(canon[s.step_order].get("t", "") or s.title)
            s.instruction = str(canon[s.step_order].get("i", "") or "")
            applied.append(s.step_order)
    se = dict(v.source_evidence or {})
    sync = dict(se.get("sync") or {})
    remaining = [o for o in (sync.get("conflicting_steps") or []) if o not in applied]
    sync.update({"conflicting_steps": remaining})
    if not remaining and sync.get("action") == "conflict":
        sync["action"] = "resolved"
    se["sync"] = sync
    v.source_evidence = se
    from sqlalchemy.orm.attributes import flag_modified as _flag_modified
    _flag_modified(v, "source_evidence")
    db.commit()
    db.refresh(v)
    audit(db, who["id"], "procedure.conflict_resolve", "procedure_version", v.id,
          {"applied": applied, "remaining": remaining})
    return {"ok": True, "applied": applied, "remaining": remaining, "action": sync.get("action")}


@app.post("/api/procedure-versions/{vid}/submit-review")
def submit_review(vid: str, db: Session = Depends(get_db), who=Depends(actor)):
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    if v.status not in ("draft", "rejected"): raise HTTPException(409, "Only drafts or rejected versions can be submitted for review")
    v.status = "pending_review"; db.commit()
    return {"ok": True, "status": v.status}


@app.post("/api/procedure-versions/{vid}/approve")
def approve(vid: str, body: S.ReviewAction, db: Session = Depends(get_db), who=Depends(actor)):
    if who["role"] not in ("reviewer", "admin", "expert"): raise HTTPException(403, "Reviewer role required to approve")
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    if v.status != "pending_review": raise HTTPException(409, "Only versions pending review can be approved")
    for other in db.scalars(select(M.ProcedureVersion).where(M.ProcedureVersion.procedure_id == v.procedure_id, M.ProcedureVersion.status == "approved")).all():
        other.status = "superseded"
    v.status = "approved"; v.reviewed_by = who["id"]; v.reviewed_at = datetime.now(timezone.utc); v.review_comment = body.comment
    audit(db, who["id"], "procedure.approve", "procedure_version", v.id, {"comment": body.comment})
    db.commit()
    return {"ok": True, "status": "approved"}


@app.post("/api/procedure-versions/{vid}/reject")
def reject(vid: str, body: S.ReviewAction, db: Session = Depends(get_db), who=Depends(actor)):
    if who["role"] not in ("reviewer", "admin", "expert"): raise HTTPException(403, "Reviewer role required to reject")
    v = db.get(M.ProcedureVersion, vid)
    if not v: raise HTTPException(404, "Version not found")
    if v.status != "pending_review": raise HTTPException(409, "Only versions pending review can be rejected")
    if not (body.comment or "").strip(): raise HTTPException(422, "A reason is required when rejecting a version")
    v.status = "rejected"; v.reviewed_by = who["id"]; v.reviewed_at = datetime.now(timezone.utc); v.review_comment = body.comment
    audit(db, who["id"], "procedure.reject", "procedure_version", v.id, {"comment": body.comment})
    db.commit()
    return {"ok": True, "status": "rejected"}


def _evidence_image(e: M.Evidence) -> tuple[bytes | None, str]:
    if e.storage_key:
        path = Path(__file__).resolve().parent.parent / e.storage_key
        if path.is_file():
            ct = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
            return path.read_bytes(), ct
    return None, "image/jpeg"


@app.post("/api/evidence/{eid}/segment")
def segment(eid: str, body: S.SegmentRequest, db: Session = Depends(get_db), who=Depends(actor)):
    e = db.get(M.Evidence, eid)
    if not e: raise HTTPException(404, "Evidence not found")
    if e.evidence_type != "image": raise HTTPException(400, "Segmentation requires image evidence. Attach or capture a photo first.")
    if not body.prompt_text.strip() and body.prompt_nx is None:
        raise HTTPException(422, "Provide a prompt_text or a tap point (prompt_nx/prompt_ny)")
    image_bytes, content_type = _evidence_image(e)
    point = (body.prompt_nx, body.prompt_ny) if body.prompt_nx is not None and body.prompt_ny is not None else None
    r = ai.segment_image(body.prompt_text, image_bytes=image_bytes, filename=e.source_reference or "photo.jpg",
                         content_type=content_type, prompt_point_norm=point)
    seg = M.SegmentationResult(evidence_id=eid, prompt_text=body.prompt_text or "tapped object", normalized_geometry=r["geometry"],
                               provider_model=r["model"], simulated=1 if r["simulated"] else 0,
                               result_status=r.get("status", "ok"))
    db.add(seg); db.commit(); db.refresh(seg)
    return {"id": seg.id, "geometry": seg.normalized_geometry, "simulated": bool(seg.simulated), "model": seg.provider_model, "note": r.get("note", ""), "status": r.get("status", "ok")}


@app.post("/api/evidence/{eid}/suggest-prompts")
def suggest_prompts(eid: str, db: Session = Depends(get_db), who=Depends(actor)):
    e = db.get(M.Evidence, eid)
    if not e: raise HTTPException(404, "Evidence not found")
    if e.evidence_type != "image": raise HTTPException(400, "Suggestions require image evidence")
    image_bytes, content_type = _evidence_image(e)
    return ai.suggest_segment_prompts(image_bytes, content_type=content_type)


@app.post("/api/segmentation/{sid}/confirm")
def confirm_seg(sid: str, body: dict, db: Session = Depends(get_db), who=Depends(actor)):
    s = db.get(M.SegmentationResult, sid)
    if not s: raise HTTPException(404, "Segmentation not found")
    if s.result_status == "no_match": raise HTTPException(409, "There is no segmentation match to confirm or reject")
    s.confirmed_by = who["id"] if body.get("confirmed") else None
    s.confirmed_at = datetime.now(timezone.utc) if body.get("confirmed") else None
    s.result_status = "confirmed" if body.get("confirmed") else "rejected"
    db.commit()
    return {"ok": True, "status": s.result_status}


@app.post("/api/live-session/start")
def live_start(db: Session = Depends(get_db), who=Depends(actor)):
    recording_id = str(uuid.uuid4())
    s = live_mod.create_session(who["id"], recording_id=recording_id)
    rec = M.LiveRecording(id=recording_id, session_id=s["session_id"], access_token=s["token"], actor=who["id"])
    db.add(rec); db.commit()
    return s


def _get_recording(db: Session, rid: str, token: str) -> M.LiveRecording:
    import secrets as _secrets
    rec = db.get(M.LiveRecording, rid)
    if not rec or not token or not _secrets.compare_digest(rec.access_token, token):
        raise HTTPException(403, "Invalid recording token")
    return rec


def _chunk_out(ch: M.LiveChunk) -> dict:
    return {"id": ch.id, "chunk_index": ch.chunk_index, "frame_count": ch.frame_count, "fps": ch.fps,
            "width": ch.width, "height": ch.height, "prompt_text": ch.prompt_text, "prompt_kind": ch.prompt_kind,
            "result_status": ch.result_status, "simulated": bool(ch.simulated),
            "segmentation": ch.segmentation or {"frames": []},
            "corrected_segmentation": ch.corrected_segmentation,
            "corrected_prompt": ch.corrected_prompt, "review_status": ch.review_status, "transcript": ch.transcript or "",
            "start_ms": ch.start_ms or 0, "end_ms": ch.end_ms or 0, "prompt_source": ch.prompt_source or "", "speech_phrase": ch.speech_phrase or "",
            "video_url": f"/api/live-recordings/{ch.recording_id}/chunks/{ch.chunk_index}/video",
            "created_at": ch.created_at.isoformat()}


# ---------------------------------------------------------------- Tutorials

def _get_tutorial(db: Session, jid: str, token: str) -> M.TutorialJob:
    import secrets as _secrets
    job = db.get(M.TutorialJob, jid)
    if not job or not token or not _secrets.compare_digest(job.access_token, token):
        raise HTTPException(403, "Invalid tutorial token")
    return job


def _tutorial_out(job: M.TutorialJob) -> dict:
    return {"id": job.id, "title": job.title, "status": job.status, "progress": job.progress,
            "error": job.error, "duration_sec": job.duration_sec, "width": job.width, "height": job.height,
            "access_token": job.access_token,
            "video_url": f"/api/tutorial/{job.id}/video",
            "full_transcript": job.full_transcript, "timed_segments": job.timed_segments or [],
            "transcript_original": getattr(job, "transcript_original", "") or "",
            "transcript_corrected": getattr(job, "transcript_corrected", "") or "",
            "equipment_name": getattr(job, "equipment_name", "") or "",
            "task_description": getattr(job, "task_description", "") or "",
            "context_notes": getattr(job, "context_notes", "") or "",
            "content_revision": getattr(job, "content_revision", 1) or 1,
            "objects": job.objects or [], "steps": job.steps or [], "materials": job.materials or [],
            "guide_markdown": job.guide_markdown, "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat() if getattr(job, "updated_at", None) else job.created_at.isoformat(),
            "guide_format": job.guide_format or "", "format_source": job.format_source or "",
            "format_rationale": job.format_rationale or "",
            "draft_procedure_id": job.draft_procedure_id or None,
            "draft_version_id": job.draft_version_id or None}


@app.post("/api/tutorial/start")
async def tutorial_start(file: UploadFile = File(...), title: str = Form(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    # Browsers send codec-qualified types (e.g. "video/webm;codecs=vp8,opus"):
    # compare the base media type only, with a filename-extension fallback.
    base_type = (file.content_type or "").split(";")[0].strip().lower()
    suffix_by_type = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov", "video/x-matroska": ".mkv"}
    suffix = suffix_by_type.get(base_type)
    if suffix is None:
        ext = Path(file.filename or "").suffix.lower()
        if ext in (".mp4", ".webm", ".mov", ".mkv"):
            suffix = ext
    if suffix is None:
        raise HTTPException(415, "Only MP4, WebM or MOV tutorial videos are supported")
    data = await file.read()
    if len(data) > 300 * 1024 * 1024: raise HTTPException(413, "Tutorial video too large (max 300 MB)")
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(M.TutorialJob).where(M.TutorialJob.video_hash == digest, M.TutorialJob.actor == who["id"], M.TutorialJob.status == "done"))
    if existing is not None:
        out = _tutorial_out(existing); out["cached"] = True
        return out
    job = M.TutorialJob(title=title.strip() or (file.filename or "Untitled tutorial"), actor=who["id"],
                        access_token=str(uuid.uuid4()), video_hash=digest, status="uploaded", progress=2)
    db.add(job); db.flush()
    store_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / job.id
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / f"source{suffix}").write_bytes(data)
    job.video_storage_key = f"data/tutorials/{job.id}/source{suffix}"
    db.commit(); db.refresh(job)
    tut.start_job(job.id)
    return _tutorial_out(job)


@app.get("/api/tutorial")
def list_tutorials(q: str = "", status: str = "", limit: int = 50, offset: int = 0,
                   include_archived: bool = False, db: Session = Depends(get_db)):
    """Tutorial library: visible to all demo users (demo identity is not a
    security boundary), newest first, with search + status filter +
    pagination so older, failed and unapproved tutorials stay findable."""
    stmt = select(M.TutorialJob).order_by(M.TutorialJob.created_at.desc())
    if not include_archived:
        stmt = stmt.where(M.TutorialJob.status != "archived")
    if status:
        stmt = stmt.where(M.TutorialJob.status == status)
    rows = list(db.scalars(stmt).all())
    if q:
        needle = q.strip().lower()
        rows = [j for j in rows if needle in (j.title or "").lower()]
    total = len(rows)
    page = rows[offset:offset + max(1, min(limit, 200))]
    return {"total": total, "offset": offset,
            "items": [{"id": j.id, "title": j.title, "status": j.status, "progress": j.progress,
                       "access_token": j.access_token, "duration_sec": j.duration_sec,
                       "created_at": j.created_at.isoformat(), "actor": j.actor,
                       "draft_version_id": j.draft_version_id or None,
                       "objects_total": len(j.objects or []),
                       "objects_unresolved": sum(1 for o in (j.objects or []) if o.get("status") in ("needs_tap", "error")),
                       "has_guide": bool(j.guide_markdown)} for j in page]}


@app.get("/api/tutorial/formats")
def tutorial_formats():
    """The three selectable guide presentations (shared canonical content)."""
    from . import tutorial as tut
    return {"formats": [{"id": fid, **meta} for fid, meta in tut.GUIDE_FORMATS.items()]}


@app.get("/api/tutorial/{jid}")
def get_tutorial(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    return _tutorial_out(_get_tutorial(db, jid, x_tutorial_token))


@app.get("/api/tutorial/{jid}/video")
def tutorial_video(jid: str, token: str = "", db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    job = _get_tutorial(db, jid, token)
    path = Path(__file__).resolve().parent.parent / job.video_storage_key
    if not path.is_file(): raise HTTPException(404, "Tutorial video missing")
    media = {".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "video/mp4")
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/tutorial/{jid}/illustrations/{name}")
def tutorial_illustration(jid: str, name: str, token: str = "", db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    job = _get_tutorial(db, jid, token)
    safe = Path(name).name
    if safe != name or not safe.endswith(".png"): raise HTTPException(404, "Illustration not found")
    path = Path(__file__).resolve().parent.parent / "data" / "tutorials" / jid / safe
    if not path.is_file(): raise HTTPException(404, "Illustration not found")
    return FileResponse(path, media_type="image/png", filename=safe)


@app.get("/api/tutorial/{jid}/recommendation")
def tutorial_recommendation(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    from . import tutorial as tut
    job = _get_tutorial(db, jid, x_tutorial_token)
    rec = tut.recommend_format(job)
    if job.guide_format in tut.GUIDE_FORMATS:
        return {"format": job.guide_format, "source": job.format_source or "user",
                "rationale": job.format_rationale or "Selected explicitly; kept as-is.",
                "scores": rec["scores"],
                "recommendation": {"format": rec["format"], "rationale": rec["rationale"]}}
    return {"format": rec["format"], "source": "recommended", "rationale": rec["rationale"], "scores": rec["scores"],
            "recommendation": {"format": rec["format"], "rationale": rec["rationale"]},
            "explicit": bool(job.guide_format in tut.GUIDE_FORMATS)}


@app.put("/api/tutorial/{jid}/format")
def tutorial_set_format(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Explicitly select a presentation format without generating yet.

    The choice is recorded with source=user; generation keeps it unless the
    user changes it again. Never touches prior versions.
    """
    from . import tutorial as tut
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    fmt = str((body or {}).get("format", "") or "").strip()
    if fmt not in tut.GUIDE_FORMATS:
        raise HTTPException(422, f"Unknown format '{fmt}'. Choose from: {', '.join(sorted(tut.GUIDE_FORMATS))}")
    job.guide_format = fmt
    job.format_source = "user"
    job.format_rationale = str((body or {}).get("rationale", "") or "") or "Selected explicitly by the user."
    db.commit(); db.refresh(job)
    proc.safe_record(db, "tutorial", job.id, "format", "user", operation="select_format", actor=who["id"],
                     summary={"format": fmt, "rationale": job.format_rationale})
    return {"ok": True, "format": fmt, "format_source": "user", "rationale": job.format_rationale}


@app.post("/api/tutorial/{jid}/guide")
def tutorial_generate_guide(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Generate a NEW persisted guide version in the requested (or recommended) format.

    Never mutates prior snapshots. When instructions/illustrations also change
    (always true for a fresh generation), the linked Review draft is synced:
    editable drafts are updated in place; locked versions get a new revision
    via the normal revision flow. Approved procedures are never touched.
    """
    from . import tutorial as tut
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status != "done":
        raise HTTPException(409, "The tutorial has not finished processing yet")
    fmt = str((body or {}).get("format", "") or "").strip()
    if not fmt and job.guide_format in tut.GUIDE_FORMATS:
        # Explicit user choice persists: generating without a format keeps it,
        # never silently switches to a new recommendation.
        fmt, source, rationale = job.guide_format, job.format_source or "user", job.format_rationale or "Selected explicitly by the user."
    elif not fmt:
        rec = tut.recommend_format(job)
        fmt, source, rationale = rec["format"], "recommended", rec["rationale"]
    elif fmt not in tut.GUIDE_FORMATS:
        raise HTTPException(422, f"Unknown format '{fmt}'. Choose from: {', '.join(sorted(tut.GUIDE_FORMATS))}")
    else:
        source, rationale = "user", "Selected explicitly by the user."
    same_as_current = bool(job.guide_format) and fmt == job.guide_format
    objects = job.objects or []
    # Idempotency: an identical format generation completed moments ago
    # (double-click / retry) returns the existing snapshot, no new version.
    # The dedup is deliberately narrow: it is skipped when canonical content
    # changed since that snapshot (job.updated_at is bumped by every Studio
    # save) or when the linked draft is locked (regen must fork a new
    # revision via the normal review flow, never silently reuse).
    try:
        latest = db.scalars(select(M.GuideSnapshot).where(M.GuideSnapshot.tutorial_id == job.id).order_by(M.GuideSnapshot.created_at.desc())).first()
    except Exception:
        latest = None
    draft_locked = False
    if job.draft_version_id:
        _dv = db.get(M.ProcedureVersion, job.draft_version_id)
        draft_locked = _dv is not None and _dv.status not in ("draft", "rejected")
    content_changed = bool((getattr(latest, "content_revision", 0) or 0) != (int(getattr(job, "content_revision", 1) or 1)))
    if latest is not None and latest.trigger == "format" and (latest.guide_format or "") == fmt \
            and not draft_locked and not content_changed:
        try:
            import datetime as _dt
            age = (_dt.datetime.now(_dt.timezone.utc) - latest.created_at.replace(tzinfo=_dt.timezone.utc)).total_seconds()
        except Exception:
            age = 10 ** 9
        if age < 120 and (latest.object_statuses or []) == [{"obj_id": o.get("obj_id"), "label": o.get("label"), "status": o.get("status"), "confidence": o.get("confidence")} for o in objects]:
            return {"ok": True, "snapshot_id": latest.id, "format": fmt,
                    "format_source": latest.format_source or source,
                    "rationale": latest.format_rationale or rationale,
                    "draft_version_id": job.draft_version_id or None,
                    "draft_status": "unchanged", "markdown_chars": len(job.guide_markdown or ""),
                    "duplicate": True}
    # Canonical path: regenerate from current job content, snapshot the new
    # version, then sync (or fork) the linked Review draft. Approved
    # procedures are never touched; prior snapshots are never mutated.
    out = tut.regenerate_guide_for_job(db, job, "format", fmt=fmt, actor=who["id"])
    return {"ok": True, "snapshot_id": out["snapshot_id"], "format": out["format"],
            "format_source": out["format_source"], "rationale": out["rationale"],
            "draft_version_id": out["draft_version_id"], "draft_status": out["draft_status"],
            "markdown_chars": out["markdown_chars"],
            "draft_action": out["draft_action"], "detail": out["detail"]}


@app.post("/api/tutorial/{jid}/objects/{obj_id}/tap")
def tutorial_tap(jid: str, obj_id: int, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    _get_tutorial(db, jid, x_tutorial_token)
    try:
        nx, ny = float(body.get("nx")), float(body.get("ny"))
    except Exception:
        raise HTTPException(422, "nx and ny are required")
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0): raise HTTPException(422, "Tap coordinates must be within 0..1")
    tut.start_tap_correction(jid, obj_id, nx, ny)
    return {"ok": True, "status": "processing"}


@app.post("/api/tutorial/{jid}/retry")
def tutorial_retry(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status in ("done",):
        return {"ok": True, "status": job.status}
    job.status = "uploaded"; job.progress = 2; job.error = ""; db.commit()
    tut.start_job(jid)
    return {"ok": True, "status": "uploaded"}


@app.delete("/api/tutorial/{jid}")
def tutorial_delete(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    import shutil as _shutil
    job = _get_tutorial(db, jid, x_tutorial_token)
    store_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / jid
    if store_dir.is_dir(): _shutil.rmtree(store_dir, ignore_errors=True)
    db.delete(job); db.commit()
    return {"ok": True}


@app.post("/api/tutorial/{jid}/refresh-guide")
def refresh_guide(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Regenerate the guide from current canonical content and sync the draft.

    Used after tap corrections (and from the UI refresh action): the guide,
    snapshot history, and Review draft all reflect the latest objects,
    labels, and illustrations. Never mutates locked versions.
    """
    from . import tutorial as tut
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status != "done":
        raise HTTPException(409, "The guide is not finished yet")
    out = tut.regenerate_guide_for_job(db, job, "refresh", actor=who["id"])
    return {"ok": True, "guide_markdown": job.guide_markdown, "snapshot_id": out["snapshot_id"],
            "draft_version_id": out["draft_version_id"], "draft_action": out["draft_action"]}


@app.get("/api/tutorial/{jid}/snapshots")
def tutorial_snapshots(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Immutable history of every generated guide for this tutorial."""
    job = _get_tutorial(db, jid, x_tutorial_token)
    snaps = db.scalars(select(M.GuideSnapshot).where(M.GuideSnapshot.tutorial_id == job.id).order_by(M.GuideSnapshot.created_at)).all()
    return {"tutorial_id": job.id,
            "snapshots": [{"id": s.id, "trigger": s.trigger, "model": s.model, "simulated": bool(s.simulated),
                           "guide_hash": s.guide_hash, "materials": s.materials or [],
                           "object_statuses": s.object_statuses or [], "created_at": s.created_at.isoformat(),
                           "markdown_chars": len(s.guide_markdown or "")} for s in snaps]}


@app.get("/api/tutorial/{jid}/snapshots/{sid}")
def tutorial_snapshot(jid: str, sid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    job = _get_tutorial(db, jid, x_tutorial_token)
    snap = db.get(M.GuideSnapshot, sid)
    if not snap or snap.tutorial_id != job.id: raise HTTPException(404, "Guide snapshot not found")
    return {"id": snap.id, "trigger": snap.trigger, "model": snap.model, "simulated": bool(snap.simulated),
            "guide_hash": snap.guide_hash, "materials": snap.materials or [],
            "object_statuses": snap.object_statuses or [], "created_at": snap.created_at.isoformat(),
            "guide_markdown": snap.guide_markdown}


@app.get("/api/tutorial/{jid}/diagnostics")
def tutorial_diagnostics(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Machine-readable debug bundle: transcript, object attempts, snapshots, events."""
    from . import processing as _proc  # noqa: F401 (ensures table mapping import order)
    job = _get_tutorial(db, jid, x_tutorial_token)
    snaps = db.scalars(select(M.GuideSnapshot).where(M.GuideSnapshot.tutorial_id == job.id).order_by(M.GuideSnapshot.created_at)).all()
    evs = db.scalars(select(M.ProcessingEvent).where(M.ProcessingEvent.entity_type == "tutorial",
                                                     M.ProcessingEvent.entity_id == job.id).order_by(M.ProcessingEvent.created_at)).all()
    return {"tutorial_id": job.id, "title": job.title, "status": job.status, "progress": job.progress,
            "error": job.error, "duration_sec": job.duration_sec,
            "draft_procedure_id": job.draft_procedure_id or None,
            "draft_version_id": job.draft_version_id or None,
            "full_transcript": job.full_transcript, "timed_segments": job.timed_segments or [],
            "objects": job.objects or [], "steps": job.steps or [],
            "snapshots": [{"id": s.id, "trigger": s.trigger, "model": s.model, "simulated": bool(s.simulated),
                           "guide_hash": s.guide_hash, "created_at": s.created_at.isoformat()} for s in snaps],
            "events": [{"id": e.id, "correlation_id": e.correlation_id, "stage": e.stage,
                        "operation": e.operation, "provider": e.provider, "model": e.model,
                        "status": e.status, "duration_ms": e.duration_ms, "summary": e.summary or {},
                        "created_at": e.created_at.isoformat()} for e in evs]}


@app.get("/api/tutorial/{jid}/diagnostics/frame/{obj_id}")
def tutorial_diagnostic_frame(jid: str, obj_id: int, token: str = "", db: Session = Depends(get_db)):
    """The frame SAM was asked about for an object it could not track."""
    from fastapi.responses import FileResponse
    job = _get_tutorial(db, jid, token)
    obj = next((o for o in (job.objects or []) if int(o.get("obj_id", 0)) == obj_id), None)
    if obj is None: raise HTTPException(404, "Object not found")
    names = [n for n in [obj.get("diagnostic_frame")] if n]
    for n in names:
        path = Path(__file__).resolve().parent.parent / "data" / "tutorials" / jid / Path(n).name
        if path.is_file():
            return FileResponse(path, media_type="image/jpeg", filename=path.name)
    raise HTTPException(404, "No diagnostic frame recorded for this object")


@app.post("/api/tutorial/{jid}/draft")
def tutorial_ensure_draft(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Create (or return) the persistent Review-queue draft for a finished tutorial.

    Idempotent: never duplicates. Also serves as retry/backfill for older tutorials.
    """
    from . import tutorial as tut
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status != "done":
        raise HTTPException(409, "The tutorial has not finished processing yet")
    if job.draft_version_id:
        existing = db.get(M.ProcedureVersion, job.draft_version_id)
        if existing is not None:
            return {"ok": True, "procedure_id": job.draft_procedure_id, "version_id": job.draft_version_id,
                    "created": False}
    try:
        ver = tut._ensure_review_draft(db, job, job.steps or [], job.objects or [],
                                       job.guide_markdown or "", job.materials or [],
                                       model="tutorial-pipeline", simulated=True, actor=who["id"])
    except Exception as e:
        proc.safe_record(db, "tutorial", job.id, "draft", "failed", operation="ensure_review_draft",
                         actor=who["id"], summary={"error_type": type(e).__name__, "error": str(e)[:300]})
        raise HTTPException(500, f"Draft creation failed: {type(e).__name__}: {str(e)[:200]}")
    return {"ok": True, "procedure_id": ver.procedure_id, "version_id": ver.id, "created": True}


# ------------------------------------------------ Tutorial Studio: editing

def _check_content_revision(job: M.TutorialJob, body: dict) -> None:
    """Optimistic concurrency: reject stale Studio saves instead of merging."""
    exp = (body or {}).get("expected_revision")
    if exp is None or exp == "":
        return
    try:
        exp_n = int(exp)
    except (TypeError, ValueError):
        raise HTTPException(422, "expected_revision must be a number")
    if int(getattr(job, "content_revision", 1) or 1) != exp_n:
        raise HTTPException(409, "This tutorial changed in another session. Reload to get the latest content, then save again.")


def _normalize_studio_steps(raw: object, duration_sec: float) -> list[dict]:
    """Validate + normalize the Studio step list into canonical step dicts.

    Accepts {title, summary|instruction, start|audio_start, end|audio_end,
    objects_used, expected_result, verification_notes, tools|required_tools}.
    Rejects empty titles, negative/inverted ranges, and ranges beyond the
    source recording. Never fabricates timing.
    """
    if not isinstance(raw, list) or not raw:
        raise HTTPException(422, "Provide at least one step")
    if len(raw) > 100:
        raise HTTPException(422, "Too many steps (max 100)")
    clean: list[dict] = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise HTTPException(422, f"Step {i + 1} must be an object")
        title = str(s.get("title", "") or "").strip()[:200]
        if not title:
            raise HTTPException(422, f"Step {i + 1} needs a title")
        summary = str(s.get("summary", s.get("instruction", "")) or "")[:8000]
        if not summary.strip():
            raise HTTPException(422, f"Step {i + 1} needs an instruction")
        try:
            start = float(s.get("start", s.get("audio_start", 0)) or 0)
            end = float(s.get("end", s.get("audio_end", 0)) or 0)
        except (TypeError, ValueError):
            raise HTTPException(422, f"Step {i + 1}: time range must be numbers")
        if start < 0 or end < 0:
            raise HTTPException(422, f"Step {i + 1}: time range cannot be negative")
        if end and end <= start:
            raise HTTPException(422, f"Step {i + 1}: end must be after start")
        if duration_sec > 0 and (start > duration_sec or (end and end > duration_sec + 0.01)):
            raise HTTPException(422, f"Step {i + 1}: range exceeds the {duration_sec:.0f}s source recording")
        used = s.get("objects_used", [])
        if not isinstance(used, list):
            raise HTTPException(422, f"Step {i + 1}: objects_used must be a list")
        obj_ids: list[int] = []
        for o in used:
            try:
                obj_ids.append(int(o))
            except (TypeError, ValueError):
                raise HTTPException(422, f"Step {i + 1}: object ids must be numbers")
        tools = s.get("required_tools", s.get("tools", []))
        if not isinstance(tools, list):
            raise HTTPException(422, f"Step {i + 1}: tools must be a list")
        clean.append({
            "step_number": i + 1,
            "title": title,
            "summary": summary,
            "start": round(start, 2),
            "end": round(end, 2),
            "objects_used": obj_ids,
            "expected_result": str(s.get("expected_result", "") or "")[:2000],
            "verification_notes": str(s.get("verification_notes", "") or "")[:2000],
            "required_tools": [str(t)[:120] for t in tools if str(t).strip()][:20],
        })
    return clean


def _normalize_segments(raw: object, duration_sec: float) -> list[dict]:
    if raw is None:
        raise HTTPException(422, "Timed segments must be a list to replace them")
    if not isinstance(raw, list):
        raise HTTPException(422, "Timed segments must be a list")
    if len(raw) > 2000:
        raise HTTPException(422, "Too many transcript segments (max 2000)")
    clean: list[dict] = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise HTTPException(422, f"Segment {i + 1} must be an object")
        try:
            start = float(s.get("start", 0) or 0)
            end = float(s.get("end", 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(422, f"Segment {i + 1}: time range must be numbers")
        if start < 0 or end < 0 or (end and end < start):
            raise HTTPException(422, f"Segment {i + 1}: invalid time range")
        clean.append({"text": str(s.get("text", "") or "")[:4000],
                      "start": round(start, 2), "end": round(end, 2)})
    return clean


@app.put("/api/tutorial/{jid}")
def tutorial_update_meta(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Edit Tutorial Studio overview metadata. The original video is untouched."""
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    _check_content_revision(job, body or {})
    title = str((body or {}).get("title", "") or "")
    if "title" in (body or {}):
        if not title.strip():
            raise HTTPException(422, "Title cannot be empty")
        if len(title) > 200:
            raise HTTPException(422, "Title too long (max 200 chars)")
        job.title = title.strip()
    if "equipment_name" in (body or {}):
        job.equipment_name = str((body or {}).get("equipment_name") or "")[:200]
    if "task_description" in (body or {}):
        job.task_description = str((body or {}).get("task_description") or "")[:4000]
    if "context_notes" in (body or {}):
        job.context_notes = str((body or {}).get("context_notes") or "")[:8000]
    db.commit()
    db.refresh(job)
    proc.safe_record(db, "tutorial", job.id, "studio", "succeeded", operation="update_metadata",
                     actor=who["id"], summary={"title_chars": len(job.title)})
    return _tutorial_out(job)


@app.get("/api/tutorial/{jid}/content")
def tutorial_get_content(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Current editable canonical content for Tutorial Studio."""
    job = _get_tutorial(db, jid, x_tutorial_token)
    return {"tutorial_id": job.id,
            "content_revision": int(getattr(job, "content_revision", 1) or 1),
            "transcript_original": getattr(job, "transcript_original", "") or job.full_transcript or "",
            "transcript_corrected": getattr(job, "transcript_corrected", "") or "",
            "timed_segments": job.timed_segments or [],
            "steps": job.steps or [],
            "materials": job.materials or [],
            "updated_at": job.updated_at.isoformat() if getattr(job, "updated_at", None) else job.created_at.isoformat()}


@app.put("/api/tutorial/{jid}/content")
def tutorial_save_content(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Save canonical Studio content as a new immutable revision.

    Preserves the original AI transcription separately, bumps
    content_revision (optimistic concurrency via expected_revision), and
    records a TutorialContentRevision row. Does NOT touch guides, drafts,
    or approved procedures — regenerate explicitly via /guide.
    """
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    _check_content_revision(job, body or {})
    if not isinstance(body, dict):
        raise HTTPException(422, "Request body must be an object")
    touched: list[str] = []
    if "transcript_corrected" in body:
        corrected = str(body.get("transcript_corrected") or "")[:60000]
        if not getattr(job, "transcript_original", ""):
            job.transcript_original = job.full_transcript or ""
        job.transcript_corrected = corrected
        touched.append("transcript")
    if "timed_segments" in body:
        job.timed_segments = _normalize_segments(body.get("timed_segments"), job.duration_sec or 0)
        touched.append("segments")
    if "steps" in body:
        job.steps = _normalize_studio_steps(body.get("steps"), job.duration_sec or 0)
        touched.append("steps")
    if "materials" in body:
        mats = body.get("materials")
        if not isinstance(mats, list):
            raise HTTPException(422, "Materials must be a list")
        job.materials = [str(m)[:300] for m in mats if str(m).strip()][:50]
        touched.append("materials")
    if not touched:
        raise HTTPException(422, "Nothing to save: provide transcript_corrected, timed_segments, steps, or materials")
    job.content_revision = int(getattr(job, "content_revision", 1) or 1) + 1
    from sqlalchemy import func as _func
    max_rev = db.scalar(select(_func.max(M.TutorialContentRevision.revision_number)).where(
        M.TutorialContentRevision.tutorial_id == job.id)) or 0
    rev = M.TutorialContentRevision(
        tutorial_id=job.id, revision_number=int(max_rev) + 1,
        transcript_corrected=getattr(job, "transcript_corrected", "") or "",
        timed_segments=list(job.timed_segments or []),
        steps=list(job.steps or []),
        materials=list(job.materials or []),
        actor=who["id"], note=str((body or {}).get("note", "") or "")[:500])
    db.add(rev)
    db.commit()
    db.refresh(job)
    db.refresh(rev)
    proc.safe_record(db, "tutorial", job.id, "studio", "succeeded", operation="save_content",
                     actor=who["id"], summary={"revision": rev.revision_number,
                                              "touched": touched,
                                              "steps": len(job.steps or [])})
    return {"ok": True, "tutorial_id": job.id, "content_revision": job.content_revision,
            "revision_id": rev.id, "revision_number": rev.revision_number, "touched": touched}


@app.get("/api/tutorial/{jid}/revisions")
def tutorial_list_revisions(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Saved content revisions, newest last. Originals live on the tutorial."""
    job = _get_tutorial(db, jid, x_tutorial_token)
    rows = db.scalars(select(M.TutorialContentRevision).where(
        M.TutorialContentRevision.tutorial_id == job.id).order_by(M.TutorialContentRevision.revision_number)).all()
    return {"tutorial_id": job.id, "current_revision": int(getattr(job, "content_revision", 1) or 1),
            "revisions": [{"id": r.id, "revision_number": r.revision_number,
                           "steps": len(r.steps or []),
                           "transcript_chars": len(r.transcript_corrected or ""),
                           "actor": r.actor, "note": r.note or "",
                           "created_at": r.created_at.isoformat()} for r in rows]}


@app.post("/api/tutorial/{jid}/revisions/{rid}/restore")
def tutorial_restore_revision(jid: str, rid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Restore a prior content revision as a NEW revision (history preserved)."""
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    _check_content_revision(job, body or {})
    rev = db.get(M.TutorialContentRevision, rid)
    if rev is None or rev.tutorial_id != job.id:
        raise HTTPException(404, "Content revision not found")
    job.transcript_corrected = rev.transcript_corrected or ""
    job.timed_segments = list(rev.timed_segments or [])
    job.steps = list(rev.steps or [])
    job.materials = list(rev.materials or [])
    job.content_revision = int(getattr(job, "content_revision", 1) or 1) + 1
    from sqlalchemy import func as _func
    max_rev = db.scalar(select(_func.max(M.TutorialContentRevision.revision_number)).where(
        M.TutorialContentRevision.tutorial_id == job.id)) or 0
    nxt = M.TutorialContentRevision(
        tutorial_id=job.id, revision_number=int(max_rev) + 1,
        transcript_corrected=job.transcript_corrected or "",
        timed_segments=list(job.timed_segments or []),
        steps=list(job.steps or []), materials=list(job.materials or []),
        actor=who["id"], note=f"Restored from revision {rev.revision_number}")
    db.add(nxt)
    db.commit()
    db.refresh(job)
    proc.safe_record(db, "tutorial", job.id, "studio", "succeeded", operation="restore_content",
                     actor=who["id"], summary={"from_revision": rev.revision_number,
                                              "to_revision": nxt.revision_number})
    return {"ok": True, "tutorial_id": job.id, "content_revision": job.content_revision,
            "revision_number": nxt.revision_number}


@app.get("/api/tutorial/{jid}/video-guides")
def tutorial_video_guide_history(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Every rendered video-guide version, oldest first. MP4s are never overwritten."""
    job = _get_tutorial(db, jid, x_tutorial_token)
    rows = db.scalars(select(M.VideoGuide).where(
        M.VideoGuide.tutorial_id == job.id).order_by(M.VideoGuide.created_at)).all()
    return {"tutorial_id": job.id,
            "versions": [_video_guide_out(vg) for vg in rows]}


@app.get("/api/tutorial/{jid}/video-guides/{vgid}/file")
def tutorial_video_guide_version_file(jid: str, vgid: str, token: str = "", db: Session = Depends(get_db)):
    """Serve one specific rendered MP4 version (token-gated, like other media)."""
    from fastapi.responses import FileResponse
    job = _get_tutorial(db, jid, token)
    vg = db.get(M.VideoGuide, vgid)
    if vg is None or vg.tutorial_id != job.id:
        raise HTTPException(404, "Video guide version not found")
    if vg.status != "ready" or not vg.storage_key:
        raise HTTPException(409, "That video version is not finished rendering yet")
    path = Path(__file__).resolve().parent.parent / vg.storage_key
    if not path.is_file():
        raise HTTPException(404, "Video guide file missing")
    return FileResponse(path, media_type="video/mp4",
                        filename=f"{(job.title or 'tutorial-guide').strip() or 'tutorial-guide'}-v{getattr(vg, 'version_number', 0) or 0}.mp4")


@app.put("/api/tutorial/{jid}/video-guide/scenes")
def tutorial_video_guide_save_scenes(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Save an edited scene plan as a draft (no render yet, no prior MP4 touched).

    Validates ranges against the source duration and rejects references to
    missing files by basename. Rendering happens explicitly via /render.
    """
    from . import videoguide as vgmod
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    scenes = (body or {}).get("scenes")
    try:
        clean = vgmod.validate_scene_plan(scenes, job.duration_sec or 0)
    except ValueError as e:
        raise HTTPException(422, str(e))
    for c in clean:
        name = (c.get("visual") or {}).get("name", "")
        if name:
            safe = Path(str(name)).name
            if safe != str(name) or Path(safe).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                raise HTTPException(422, f"Scene {c['step']}: invalid visual name")
    job_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / job.id
    missing: list[str] = []
    for c in clean:
        name = (c.get("visual") or {}).get("name", "")
        if name and not (job_dir / Path(str(name)).name).is_file():
            missing.append(f"scene {c['step']}: {name}")
    if missing:
        raise HTTPException(422, "Visual not found for " + "; ".join(missing[:5]))
    draft = db.scalar(select(M.VideoGuide).where(
        M.VideoGuide.tutorial_id == job.id, M.VideoGuide.status == "draft"
    ).order_by(M.VideoGuide.created_at.desc()))
    if draft is None:
        draft = M.VideoGuide(tutorial_id=job.id, status="draft", progress=0,
                             version_number=0, created_by=who["id"],
                             provenance={"trigger": "studio_scene_draft"})
        db.add(draft)
        db.flush()
    draft.scenes = clean
    from sqlalchemy.orm.attributes import flag_modified as _flag_modified
    _flag_modified(draft, "scenes")
    db.commit()
    db.refresh(draft)
    proc.safe_record(db, "tutorial", job.id, "video_guide", "succeeded", operation="save_scene_plan",
                     actor=who["id"], summary={"scenes": len(clean)})
    return {"ok": True, "tutorial_id": job.id, "video_guide_id": draft.id, "scenes": clean}


@app.post("/api/tutorial/{jid}/video-guide/render")
def tutorial_video_guide_render(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Render a NEW versioned MP4 from an edited scene plan (or the saved draft).

    Every render creates a separate persistent VideoGuide version — prior
    MP4s are never overwritten. The voiceover stays a cut of the user's own
    original recording; captions never imply changed narration.
    """
    from . import videoguide as vgmod
    job = _get_tutorial(db, jid, x_tutorial_token)
    scenes = (body or {}).get("scenes") if isinstance(body, dict) else None
    if scenes is None:
        draft = db.scalar(select(M.VideoGuide).where(
            M.VideoGuide.tutorial_id == job.id, M.VideoGuide.status == "draft"
        ).order_by(M.VideoGuide.created_at.desc()))
        if draft is not None and draft.scenes:
            scenes = draft.scenes
    if scenes is None:
        raise HTTPException(422, "No scene plan saved yet — edit scenes first, then render")
    try:
        vg, dup = vgmod.start_video_guide(job.id, actor=who["id"], force=True, scenes=scenes)
    except ValueError as e:
        msg = str(e)
        code = 429 if "limit" in msg else 409 if "finished processing" in msg else 422
        raise HTTPException(code, msg)
    return {"ok": True, "video_guide": _video_guide_out(vg), "duplicate": dup}


def _visual_out(a: M.VisualAsset) -> dict:
    return {"id": a.id, "tutorial_id": a.tutorial_id, "parent_id": a.parent_id, "kind": a.kind,
            "status": a.status, "step_id": a.step_id or None, "version_id": a.version_id or None,
            "image_url": f"/api/visuals/{a.id}/file" if a.storage_key else None,
            "mime_type": a.mime_type, "width": a.width, "height": a.height,
            "instruction": a.instruction, "model": a.model, "simulated": bool(a.simulated),
            "provenance": a.provenance or {}, "created_by": a.created_by,
            "created_at": a.created_at.isoformat()}


def _visual_source_bytes(db: Session, job: M.TutorialJob, spec: dict) -> tuple[bytes, str, str, str]:
    """Resolve {kind: evidence|asset|illustration|frame|diagnostic, id|name|obj_id}
    to (bytes, mime, parent_id, label). Validates ownership and type."""
    from PIL import Image as _Image
    kind = str(spec.get("kind", ""))
    job_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / job.id
    if kind == "evidence":
        e = db.get(M.Evidence, str(spec.get("id", "")))
        if not e or e.evidence_type != "image" or not e.storage_key:
            raise HTTPException(404, "Source image evidence not found")
        # Ownership: tutorial-linked evidence or same capture family is fine;
        # anything else is rejected.
        if e.source_reference != f"tutorial:{job.id}" and not str(e.source_reference or "").startswith("tutorial:"):
            raise HTTPException(403, "That evidence does not belong to this tutorial")
        path = Path(__file__).resolve().parent.parent / e.storage_key
        if not path.is_file():
            raise HTTPException(404, "Source image file missing")
        return path.read_bytes(), "image/" + path.suffix.lstrip(".").lower().replace("jpg", "jpeg"), f"evidence:{e.id}", e.description or "evidence"
    if kind == "asset":
        a = db.get(M.VisualAsset, str(spec.get("id", "")))
        if not a or a.tutorial_id != job.id or not a.storage_key:
            raise HTTPException(404, "Source visual asset not found")
        path = Path(__file__).resolve().parent.parent / a.storage_key
        if not path.is_file():
            raise HTTPException(404, "Source visual file missing")
        return path.read_bytes(), a.mime_type or "image/png", f"asset:{a.id}", a.instruction or a.kind
    if kind in ("illustration", "frame", "diagnostic"):
        name = str(spec.get("name", ""))
        if kind == "diagnostic":
            obj_id = int(spec.get("obj_id", -1))
            obj = next((o for o in (job.objects or []) if int(o.get("obj_id", -1)) == obj_id), None)
            if obj is None or not obj.get("diagnostic_frame"):
                raise HTTPException(404, "No diagnostic frame for that object")
            name = str(obj["diagnostic_frame"])
        safe = Path(name).name
        if not safe or safe != name or Path(safe).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(400, "Invalid source image name")
        if kind == "diagnostic":
            job_dir = job_dir
        path = job_dir / safe
        if not path.is_file():
            # Illustrations live at data/tutorials/{jid}/; evidence elsewhere is rejected.
            raise HTTPException(404, "Source image file missing")
        media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}[Path(safe).suffix.lower().lstrip(".")]
        return path.read_bytes(), media, f"file:{safe}", safe
    raise HTTPException(422, "source.kind must be evidence|asset|illustration|frame|diagnostic")


def _check_image_quota(db: Session, actor: str) -> None:
    import datetime as _dt
    try:
        limit = int(_os.getenv("MAX_IMAGE_OPS_PER_DAY", "50"))
    except ValueError:
        limit = 50
    if limit <= 0:
        return
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    n = 0
    for a in db.scalars(select(M.VisualAsset).where(
            M.VisualAsset.created_by == actor,
            M.VisualAsset.kind.in_(["enhanced", "illustrative_alternative"]))).all():
        if (a.created_at.isoformat() if hasattr(a.created_at, "isoformat") else "")[:10] >= today:
            n += 1
    if n >= limit:
        raise HTTPException(429, f"Daily image-generation limit reached ({limit}). Try again tomorrow.")


def _store_visual(db: Session, job: M.TutorialJob, kind: str, raw: bytes, mime: str,
                  instruction: str, model: str, parent_id: str, actor: str,
                  provenance: dict | None = None, status: str = "review",
                  idempotency_key: str = "") -> M.VisualAsset:
    from PIL import Image as _Image
    import io as _io
    try:
        with _Image.open(_io.BytesIO(raw)) as im:
            im.verify()
    except Exception:
        raise HTTPException(422, "Generated file is not a valid image")
    with _Image.open(_io.BytesIO(raw)) as im:
        w, h = im.size
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".png")
    store_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / job.id / "visuals"
    store_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (store_dir / name).write_bytes(raw)
    a = M.VisualAsset(tutorial_id=job.id, parent_id=parent_id, kind=kind, status=status,
                      storage_key=f"data/tutorials/{job.id}/visuals/{name}",
                      mime_type=mime, width=w, height=h, instruction=instruction or "",
                      model=model, simulated=False, provenance=provenance or {},
                      created_by=actor, idempotency_key=idempotency_key or "")
    db.add(a)
    db.flush()
    return a


@app.get("/api/tutorial/{jid}/visuals")
def tutorial_visuals(jid: str, kind: str = "", x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    job = _get_tutorial(db, jid, x_tutorial_token)
    stmt = select(M.VisualAsset).where(M.VisualAsset.tutorial_id == job.id).order_by(M.VisualAsset.created_at.desc())
    if kind:
        stmt = stmt.where(M.VisualAsset.kind == kind)
    return {"tutorial_id": job.id, "items": [_visual_out(a) for a in db.scalars(stmt).all()]}


@app.get("/api/visuals/{aid}/file")
def visual_file(aid: str, token: str = "", x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    tok = token or x_tutorial_token
    a = db.get(M.VisualAsset, aid)
    if not a or not a.storage_key:
        raise HTTPException(404, "Visual not found")
    job = db.get(M.TutorialJob, a.tutorial_id)
    if not job or not tok:
        raise HTTPException(403, "Invalid tutorial token")
    import secrets as _secrets
    if not _secrets.compare_digest(job.access_token, tok):
        raise HTTPException(403, "Invalid tutorial token")
    path = Path(__file__).resolve().parent.parent / a.storage_key
    if not path.is_file():
        raise HTTPException(404, "Visual file missing")
    media = {"image/png": "image/png", "image/jpeg": "image/jpeg", "image/svg+xml": "image/svg+xml",
             "image/webp": "image/webp"}.get(a.mime_type, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


def _video_guide_out(vg) -> dict:
    return {"id": vg.id, "tutorial_id": vg.tutorial_id, "status": vg.status,
            "version_number": getattr(vg, "version_number", 0) or 0,
            "progress": vg.progress, "error": vg.error or "",
            "asset_id": vg.asset_id or None,
            "video_url": f"/api/tutorial/{vg.tutorial_id}/video-guide/file" if vg.status == "ready" else None,
            "scenes": vg.scenes or [], "simulated": bool(vg.simulated),
            "provenance": vg.provenance or {}, "created_at": vg.created_at.isoformat()}


@app.post("/api/tutorial/{jid}/video-guide")
def tutorial_video_guide(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Generate an MP4 video guide cut from the user's own recorded narration.

    Optional, user-triggered, runs in the background: scenes are planned from
    the canonical procedure (Muse Spark, or deterministic fallback), the
    voiceover is cut from the original recording (never synthesized), and the
    video is rendered with the vendored Remotion project. Same versioning and
    honesty rules as image derivatives.
    """
    from . import videoguide as vgmod
    job = _get_tutorial(db, jid, x_tutorial_token)
    force = bool((body or {}).get("regenerate"))
    try:
        vg, dup = vgmod.start_video_guide(job.id, actor=who["id"], force=force)
    except ValueError as e:
        msg = str(e)
        code = 429 if "limit" in msg else 409 if "finished processing" in msg else 422
        raise HTTPException(code, msg)
    return {"ok": True, "video_guide": _video_guide_out(vg), "duplicate": dup}


@app.get("/api/tutorial/{jid}/video-guide")
def tutorial_video_guide_status(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    from . import videoguide as vgmod  # noqa: F401 (keeps video surface next to its endpoints)
    from . import models as _M
    job = _get_tutorial(db, jid, x_tutorial_token)
    vg = db.scalars(select(_M.VideoGuide).where(_M.VideoGuide.tutorial_id == job.id).order_by(_M.VideoGuide.created_at.desc())).first()
    if vg is None:
        return {"tutorial_id": job.id, "status": "none", "video_guide": None}
    return {"tutorial_id": job.id, "status": vg.status, "video_guide": _video_guide_out(vg)}


@app.get("/api/tutorial/{jid}/video-guide/file")
def tutorial_video_guide_file(jid: str, token: str = "", db: Session = Depends(get_db)):
    """Serve the rendered MP4 (token-gated like other tutorial media)."""
    from fastapi.responses import FileResponse
    job = _get_tutorial(db, jid, token)
    vg = db.scalars(select(M.VideoGuide).where(M.VideoGuide.tutorial_id == job.id,
                                               M.VideoGuide.status == "ready").order_by(M.VideoGuide.created_at.desc())).first()
    if not vg or not vg.storage_key:
        raise HTTPException(404, "No finished video guide for this tutorial yet")
    path = Path(__file__).resolve().parent.parent / vg.storage_key
    if not path.is_file():
        raise HTTPException(404, "Video guide file missing")
    return FileResponse(path, media_type="video/mp4", filename=f"{(job.title or 'tutorial-guide').strip() or 'tutorial-guide'}-guide.mp4")


_VISUAL_INTENT_PREFIX = {
    # Intent categories shape the actual model instruction (not just metadata).
    "improve": "Improve the clarity, framing, and visibility of this technical reference photo while preserving the exact same component, geometry, and viewpoint. Do not move, add, or remove parts: ",
    "highlight": "Emphasize the described region or component with a clear outline and label while preserving the exact geometry of everything else. Do not move, add, or remove parts: ",
    "replace": "Show the same kind of component with the requested replacement applied, keeping viewpoint and context comparable. This is an illustrative variant, never technical evidence: ",
    "adapt": "Adapt this reference to the requested variant while keeping viewpoint and context comparable. Illustrative only, never technical evidence: ",
    "compare": "Render a clear comparison emphasizing the requested difference while keeping each depiction faithful to its input. Illustrative only, never technical evidence: ",
    "similar": "Create a similar illustrative object guided by the references, keeping viewpoint and context comparable. Illustrative only: ",
    "newer": "Create an illustrative depiction of the described newer model guided by the references, keeping viewpoint and context comparable. Illustrative only: ",
    "reference": "Create an illustrative composition guided by the supplied reference images and the description. Illustrative only: ",
}


def _shape_instruction(intent: str, prompt: str, fallback_label: str = "") -> str:
    """Turn (intent, user text) into the model instruction.

    The user's words always drive the request; the intent prefix constrains
    HOW the model may change the image (preserve vs. illustrate). Unknown
    intents pass the prompt through unchanged — never dropped.
    """
    prefix = _VISUAL_INTENT_PREFIX.get((intent or "").strip().lower(), "")
    body = prompt.strip() or fallback_label
    return (prefix + body).strip()


@app.post("/api/tutorial/{jid}/visuals/improve")
def visual_improve(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Muse Image edit of a source visual (crop/clarity/detail).

    Source pixels are NEVER overwritten: output is a new VisualAsset
    (kind=enhanced) that must be accepted before use. Deterministic ops
    (plain crop/resize) should use the annotate/crop path instead.
    """
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    source = (body or {}).get("source") or {}
    prompt = str((body or {}).get("prompt") or "").strip()
    if_kind = str((body or {}).get("intent") or "improve")
    idem = str((body or {}).get("idempotency_key") or "")
    if idem:
        dup = db.scalar(select(M.VisualAsset).where(M.VisualAsset.tutorial_id == job.id,
                                                   M.VisualAsset.idempotency_key == idem))
        if dup is not None:
            return {"ok": True, "asset": _visual_out(dup), "duplicate": True}
    _check_image_quota(db, who["id"])
    raw, mime, parent_id, label = _visual_source_bytes(db, job, source)
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "Source image too large (max 15 MB)")
    instruction = _shape_instruction(if_kind, prompt,
        f"Improve this reference photo for a technical guide: keep the same component and viewpoint, make the subject clearer and better framed ({label}).")
    try:
        linked_obj = int((body or {}).get("obj_id", 0) or 0)
    except (TypeError, ValueError):
        linked_obj = 0
    with proc.timed() as t:
        res = ai.image_edit(raw, instruction, mime=mime if mime in ("image/png", "image/jpeg", "image/webp") else "image/png")
    proc.safe_record(db, "tutorial", job.id, "image_edit", "succeeded" if res.get("ok") else str(res.get("status", "error")),
                     operation="muse_image_edit", provider="meta", model=res.get("model", ""), duration_ms=t.ms, actor=who["id"],
                     summary={"parent": parent_id, "prompt_chars": len(instruction),
                              "usage": res.get("usage", {}), "note": res.get("note", "")})
    if not res.get("ok"):
        raise HTTPException(502 if res.get("status") == "retryable" else 500,
                            res.get("note") or "Image improvement failed")
    import base64 as _b64
    out = _b64.b64decode(res["image_b64"])
    a = _store_visual(db, job, "enhanced", out, "image/" + (res.get("output_format") or "png"),
                      instruction, res.get("model", ""), parent_id, who["id"],
                      {"intent": if_kind, "source_label": label, "obj_id": linked_obj, "usage": res.get("usage", {}),
                       "attempts": res.get("attempts", 1),
                       "warning": "AI reconstruction may not reflect true detail — verify against the source before approving."},
                      status="review", idempotency_key=idem)
    db.commit(); db.refresh(a)
    return {"ok": True, "asset": _visual_out(a), "duplicate": False}


@app.post("/api/tutorial/{jid}/visuals/alternative")
def visual_alternative(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Generate an AI ILLUSTRATIVE alternative (never evidence).

    The result is always labelled illustrative, linked to (not replacing) the
    source, and requires human review before any guide use.
    """
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    prompt = str((body or {}).get("prompt") or "").strip()
    intent = str((body or {}).get("intent") or "similar")
    idem = str((body or {}).get("idempotency_key") or "")
    try:
        linked_obj = int((body or {}).get("obj_id", 0) or 0)
    except (TypeError, ValueError):
        linked_obj = 0
    refs = []
    ref_ids = []
    for r in ((body or {}).get("references") or [])[:3]:
        try:
            raw, mime, pid, label = _visual_source_bytes(db, job, r if isinstance(r, dict) else {})
        except HTTPException as e:
            raise e
        if len(raw) > 15 * 1024 * 1024:
            raise HTTPException(413, "Reference image too large (max 15 MB)")
        refs.append((raw, mime if mime in ("image/png", "image/jpeg", "image/webp") else "image/png"))
        ref_ids.append(pid)
    _check_image_quota(db, who["id"])
    if idem:
        dup = db.scalar(select(M.VisualAsset).where(M.VisualAsset.tutorial_id == job.id,
                                                   M.VisualAsset.idempotency_key == idem))
        if dup is not None:
            return {"ok": True, "asset": _visual_out(dup), "duplicate": True}
    full_prompt = (_shape_instruction(intent, prompt, "Illustrative alternative.") +
                   " (AI-generated illustrative alternative for documentation; "
                   "conceptual reference only, not a verified photograph of the actual object.)").strip()
    if not prompt:
        raise HTTPException(422, "A description is required")
    with proc.timed() as t:
        res = ai.image_generate(full_prompt, refs or None)
    proc.safe_record(db, "tutorial", job.id, "image_generate", "succeeded" if res.get("ok") else str(res.get("status", "error")),
                     operation="muse_image_generate", provider="meta", model=res.get("model", ""),
                     duration_ms=t.ms, actor=who["id"],
                     summary={"intent": intent, "references": ref_ids, "prompt_chars": len(full_prompt),
                              "usage": res.get("usage", {}), "note": res.get("note", "")})
    if not res.get("ok"):
        raise HTTPException(502 if res.get("status") == "retryable" else 500,
                            res.get("note") or "Illustrative generation failed")
    import base64 as _b64
    out = _b64.b64decode(res["image_b64"])
    a = _store_visual(db, job, "illustrative_alternative", out, "image/" + (res.get("output_format") or "png"),
                      prompt, res.get("model", ""), ref_ids[0] if ref_ids else f"tutorial:{job.id}",
                      who["id"],
                      {"intent": intent, "references": ref_ids, "obj_id": linked_obj, "usage": res.get("usage", {}),
                       "attempts": res.get("attempts", 1),
                       "illustrative": True, "not_evidence": True,
                       "comparison": {"requested": prompt, "references": ref_ids,
                                      "generated_asset": None, "verdict": "unverified",
                                      "note": "Requested change vs generated output must be compared by a human; no compatibility or equivalence is established."},
                       "warning": "AI-generated illustration. Must not be treated as verified evidence of exact model features; applicability requires human verification."},
                      status="review", idempotency_key=idem)
    try:
        prov = dict(a.provenance or {})
        comp = dict(prov.get("comparison") or {})
        comp["generated_asset"] = a.id
        prov["comparison"] = comp
        a.provenance = prov
        from sqlalchemy.orm.attributes import flag_modified as _flag_modified
        _flag_modified(a, "provenance")
        db.commit()
    except Exception:
        db.rollback()
    db.refresh(a)
    return {"ok": True, "asset": _visual_out(a), "duplicate": False}


_ALLOWED_ANNOTATION_SHAPES = {"point", "circle", "rect", "arrow", "label", "dimension"}
_ALLOWED_DIM_UNITS = {"mm", "cm", "m", "inch", "in", "px"}


def _validate_annotation_shapes(shapes: object) -> list[dict]:
    if not isinstance(shapes, list) or not shapes:
        raise HTTPException(422, "Provide at least one annotation shape")
    if len(shapes) > 50:
        raise HTTPException(422, "Too many annotation shapes (max 50)")
    clean: list[dict] = []
    for i, s in enumerate(shapes):
        if not isinstance(s, dict):
            raise HTTPException(422, f"Shape {i} must be an object")
        kind = str(s.get("type", ""))
        if kind not in _ALLOWED_ANNOTATION_SHAPES:
            raise HTTPException(422, f"Shape {i}: type must be one of point|circle|rect|arrow|label|dimension")
        pts = s.get("points")
        if kind in ("rect", "arrow"):
            if not (isinstance(pts, list) and len(pts) == 2 and all(isinstance(p, list) and len(p) == 2 for p in pts)):
                raise HTTPException(422, f"Shape {i} ({kind}) needs exactly 2 [x,y] points in 0..1 coordinates")
        elif kind in ("point", "circle"):
            if not (isinstance(pts, list) and len(pts) == 1 and isinstance(pts[0], list) and len(pts[0]) == 2):
                raise HTTPException(422, f"Shape {i} ({kind}) needs exactly 1 [x,y] point in 0..1 coordinates")
        for p in (pts or []):
            for v in p:
                if not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 1.0):
                    raise HTTPException(422, f"Shape {i}: coordinates must be numbers in 0..1")
        text = str(s.get("text", "") or "")[:200]
        dim = s.get("dimension")
        if kind == "dimension":
            if not isinstance(dim, dict):
                raise HTTPException(422, "Dimension annotations need {value, unit}")
            try:
                value = float(dim.get("value"))
            except (TypeError, ValueError):
                raise HTTPException(422, "Dimension value must be a number")
            if not (value > 0):
                raise HTTPException(422, "Dimension value must be positive")
            unit = str(dim.get("unit", "") or "")
            if unit not in _ALLOWED_DIM_UNITS:
                raise HTTPException(422, "Dimension unit must be one of mm|cm|m|inch|in|px")
        elif dim is not None:
            raise HTTPException(422, "Only dimension shapes carry a dimension")
        clean.append({"type": kind, "points": [[float(v) for v in p] for p in (pts or [])],
                      "text": text, **({"dimension": {"value": float(dim["value"]), "unit": str(dim["unit"])}} if kind == "dimension" else {})})
    return clean


def _annotation_svg(shapes: list[dict], w: int, h: int) -> str:
    def X(x: float) -> float:
        return round(float(x) * w, 1)

    def Y(y: float) -> float:
        return round(float(y) * h, 1)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    for i, s in enumerate(shapes):
        t, pts, text = s["type"], s["points"], s.get("text", "")
        tag = f" data-shape=\"{t}\" data-index=\"{i}\""
        if t == "point":
            x, y = X(pts[0][0]), Y(pts[0][1])
            parts.append(f'<g{tag}><circle cx="{x}" cy="{y}" r="10" fill="none" stroke="#ffb020" stroke-width="4"/><circle cx="{x}" cy="{y}" r="3" fill="#ffb020"/></g>')
        elif t == "circle":
            x, y = X(pts[0][0]), Y(pts[0][1])
            parts.append(f'<g{tag}><circle cx="{x}" cy="{y}" r="26" fill="rgba(255,176,32,.15)" stroke="#ffb020" stroke-width="4"/></g>')
        elif t == "rect":
            x1, y1, x2, y2 = X(pts[0][0]), Y(pts[0][1]), X(pts[1][0]), Y(pts[1][1])
            x, y = min(x1, x2), min(y1, y2)
            parts.append(f'<g{tag}><rect x="{x}" y="{y}" width="{abs(x2-x1)}" height="{abs(y2-y1)}" fill="rgba(255,176,32,.12)" stroke="#ffb020" stroke-width="4" rx="6"/></g>')
        elif t == "arrow":
            x1, y1, x2, y2 = X(pts[0][0]), Y(pts[0][1]), X(pts[1][0]), Y(pts[1][1])
            parts.append(f'<g{tag}><defs><marker id="ah{i}" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L9,4 L0,8 Z" fill="#ffb020"/></marker></defs><line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#ffb020" stroke-width="5" marker-end="url(#ah{i})"/></g>')
        if (text or t == "dimension") and t in ("label", "dimension", "point", "arrow"):
            ax, ay = (X(pts[-1][0]) + 12, Y(pts[-1][1]) - 12) if pts else (12, 24)
            label = text if t != "dimension" else f"{s['dimension']['value']} {s['dimension']['unit']} (required — unverified)"
            esc = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            parts.append(f'<g{tag}><rect x="{ax-6}" y="{ay-20}" width="{max(60, len(esc) * 8.5)}" height="28" rx="6" fill="#201600"/><text x="{ax}" y="{ay}" font-size="17" font-family="sans-serif" fill="#ffb020">{esc}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


@app.post("/api/tutorial/{jid}/visuals/annotate")
def visual_annotate(jid: str, body: dict, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    """Deterministic annotation overlay (SVG, no AI): exact callouts stay exact.

    Dimensions are stored exactly as the user states them and labelled as
    user requirements — never measured, never invented.
    """
    from . import processing as proc
    job = _get_tutorial(db, jid, x_tutorial_token)
    source = (body or {}).get("source") or {}
    shapes = _validate_annotation_shapes((body or {}).get("shapes"))
    note = str((body or {}).get("note") or "")[:500]
    # Base dimensions come from the source file so the SVG aligns 1:1.
    raw, mime, parent_id, label = _visual_source_bytes(db, job, source)
    from PIL import Image as _Image
    import io as _io
    try:
        with _Image.open(_io.BytesIO(raw)) as im:
            w, h = im.size
    except Exception:
        raise HTTPException(422, "Source image could not be read")
    svg = _annotation_svg(shapes, max(1, w), max(1, h))
    store_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / job.id / "visuals"
    store_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.svg"
    (store_dir / name).write_text(svg, encoding="utf-8")
    a = M.VisualAsset(tutorial_id=job.id, parent_id=parent_id, kind="annotation", status="review",
                      storage_key=f"data/tutorials/{job.id}/visuals/{name}",
                      mime_type="image/svg+xml", width=w, height=h,
                      instruction=str((body or {}).get("label") or note or "Annotation overlay"),
                      model="deterministic-svg", simulated=False,
                      provenance={"shapes": shapes, "source": parent_id, "source_label": label,
                                  "note": "Deterministic overlay — geometry is exact, imagery unchanged."},
                      created_by=who["id"])
    db.add(a)
    db.flush()
    proc.safe_record(db, "tutorial", job.id, "annotate", "succeeded", operation="annotate_overlay",
                     model="deterministic-svg", actor=who["id"],
                     summary={"shapes": len(shapes), "parent": parent_id, "svg_chars": len(svg)})
    db.commit(); db.refresh(a)
    return {"ok": True, "asset": _visual_out(a)}


@app.post("/api/visuals/{aid}/accept")
def visual_accept(aid: str, body: dict, db: Session = Depends(get_db), who=Depends(actor)):
    """Accept a derivative/annotation for guide use. Never rewrites the source.

    Optionally links it to an editable procedure step: the asset becomes an
    Evidence row and its id is appended to step.visual_refs (presentation).
    Locked versions are refused with 409 — create a new revision first.
    """
    from . import processing as proc
    a = db.get(M.VisualAsset, aid)
    if not a:
        raise HTTPException(404, "Visual asset not found")
    if a.status == "accepted":
        return {"ok": True, "asset": _visual_out(a), "already": True}
    if a.status not in ("review",):
        raise HTTPException(409, f"Only visuals under review can be accepted (status={a.status})")
    step_id = str((body or {}).get("step_id") or "")
    version_id = str((body or {}).get("version_id") or "")
    evidence_id: str | None = None
    if step_id or version_id:
        if not (step_id and version_id):
            raise HTTPException(422, "Linking needs both step_id and version_id")
        v = db.get(M.ProcedureVersion, version_id)
        if not v:
            raise HTTPException(404, "Procedure version not found")
        if v.status not in ("draft", "rejected"):
            raise HTTPException(409, "That version is locked. Create a new revision first, then attach the visual there.")
        step = next((s for s in v.steps if s.id == step_id), None)
        if step is None:
            raise HTTPException(404, "Step not found in that version")
        e = M.Evidence(capture_session_id=None, evidence_type="image",
                       storage_key=a.storage_key, description=f"Accepted {a.kind}: {a.instruction or a.id[:8]}",
                       source_reference=f"tutorial:{a.tutorial_id}" if a.tutorial_id else "visual-asset",
                       created_by=who["id"],
                       extra={"visual_asset_id": a.id, "kind": a.kind, "model": a.model})
        db.add(e)
        db.flush()
        evidence_id = e.id
        refs = list(step.visual_refs or [])
        if e.id not in refs:
            refs.append(e.id)
        step.visual_refs = refs
        a.step_id = step_id
        a.version_id = version_id
    a.status = "accepted"
    db.flush()
    proc.safe_record(db, "tutorial", a.tutorial_id or "-", "accept_visual", "succeeded",
                     operation="accept_visual", actor=who["id"],
                     summary={"asset": aid, "kind": a.kind, "step_id": step_id or None,
                              "version_id": version_id or None, "evidence_id": evidence_id})
    db.commit(); db.refresh(a)
    snapshot_id = None
    if evidence_id and a.tutorial_id:
        # Attach accepted visuals to the visible guide as labelled presentation
        # assets (deterministic re-injection, no LLM): the draft step link is
        # the canonical change; the guide shows what was accepted for it.
        try:
            from . import tutorial as tut
            job = db.get(M.TutorialJob, a.tutorial_id)
            if job is not None and job.guide_markdown:
                extra = tut.accepted_visuals_by_step(db, version_id)
                if extra:
                    job.guide_markdown = tut.inject_illustrations(
                        job.guide_markdown, job.steps or [], job.objects or [], extra)
            if job is not None:
                snap = tut.snapshot_guide(db, job, "visual_accept", job.guide_markdown or "",
                                          job.objects or [], model=a.model or "",
                                          simulated=bool(a.simulated), materials=job.materials or [])
                db.commit()
                snapshot_id = snap.id
        except Exception:
            db.rollback()
    return {"ok": True, "asset": _visual_out(a), "evidence_id": evidence_id, "snapshot_id": snapshot_id}


@app.post("/api/visuals/{aid}/reject")
def visual_reject(aid: str, db: Session = Depends(get_db), who=Depends(actor)):
    """Reject a derivative. Originals stay untouched and usable."""
    a = db.get(M.VisualAsset, aid)
    if not a:
        raise HTTPException(404, "Visual asset not found")
    if a.status == "accepted":
        raise HTTPException(409, "Accepted visuals cannot be rejected; archive the guide instead")
    a.status = "rejected"
    db.commit()
    return {"ok": True, "asset": _visual_out(a)}


@app.post("/api/tutorial/{jid}/archive")
def tutorial_archive(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status not in ("done", "error"):
        raise HTTPException(409, "Only finished or failed tutorials can be archived")
    job.status = "archived"; db.commit()
    return {"ok": True, "status": job.status}


@app.post("/api/tutorial/{jid}/unarchive")
def tutorial_unarchive(jid: str, x_tutorial_token: str = Header(default=""), db: Session = Depends(get_db)):
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status != "archived":
        raise HTTPException(409, "Only archived tutorials can be restored")
    job.status = "done" if job.guide_markdown else "error"; db.commit()
    return {"ok": True, "status": job.status}


@app.get("/api/processing/events")
def processing_events(entity_type: str = "", entity_id: str = "", model: str = "",
                      status: str = "", stage: str = "", q: str = "",
                      limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    """Observability timeline: newest first, filterable by entity, model,
    status, stage, or free text over operation/notes."""
    stmt = select(M.ProcessingEvent).order_by(M.ProcessingEvent.created_at.desc())
    if entity_type:
        stmt = stmt.where(M.ProcessingEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(M.ProcessingEvent.entity_id == entity_id)
    if model:
        stmt = stmt.where(M.ProcessingEvent.model == model)
    if status:
        stmt = stmt.where(M.ProcessingEvent.status == status)
    if stage:
        stmt = stmt.where(M.ProcessingEvent.stage == stage)
    rows = list(db.scalars(stmt).all())
    if q:
        needle = q.strip().lower()
        rows = [e for e in rows if needle in (e.operation or "").lower()
                or needle in str((e.summary or {}).get("note", "")).lower()
                or needle in str((e.summary or {}).get("label", "")).lower()
                or needle in (e.correlation_id or "")]
    total = len(rows)
    page = rows[offset:offset + max(1, min(limit, 500))]
    return {"total": total, "offset": offset,
            "items": [{"id": e.id, "correlation_id": e.correlation_id, "entity_type": e.entity_type,
                       "entity_id": e.entity_id, "actor": e.actor, "stage": e.stage,
                       "operation": e.operation, "provider": e.provider, "model": e.model,
                       "status": e.status, "duration_ms": e.duration_ms, "summary": e.summary or {},
                       "created_at": e.created_at.isoformat()} for e in page]}


@app.get("/api/tutorial/{jid}/bundle.zip")
def tutorial_bundle(jid: str, token: str = "", db: Session = Depends(get_db)):
    """Portable export: guide.md (with illustration links) + illustrations/*.png."""
    import io as _io
    import zipfile as _zipfile
    from fastapi.responses import StreamingResponse
    job = _get_tutorial(db, jid, token)
    if job.status != "done":
        raise HTTPException(409, "The guide is not finished yet")
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as z:
        z.writestr("guide.md", job.guide_markdown or "")
        ill_dir = Path(__file__).resolve().parent.parent / "data" / "tutorials" / jid
        for o in job.objects or []:
            for key in ("overlay", "illustration"):
                name = (o or {}).get(key)
                if name:
                    p = ill_dir / Path(name).name
                    if p.is_file():
                        z.write(p, f"illustrations/{Path(name).name}")
    buf.seek(0)
    slug = re.sub(r"[^\w\- ]+", "", job.title or "tutorial-guide").strip() or "tutorial-guide"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'})


@app.get("/api/live-recordings")
def list_recordings(db: Session = Depends(get_db), who=Depends(actor)):
    out = []
    for rec in db.scalars(select(M.LiveRecording).where(M.LiveRecording.actor == who["id"]).order_by(M.LiveRecording.created_at.desc()).limit(20)).all():
        chunks = db.scalars(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id).order_by(M.LiveChunk.chunk_index)).all()
        out.append({"id": rec.id, "session_id": rec.session_id, "status": rec.status, "actor": rec.actor,
                    "access_token": rec.access_token, "created_at": rec.created_at.isoformat(), "transcript": rec.transcript or "",
                    "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
                    "chunks": [_chunk_out(ch) for ch in chunks]})
    return out


@app.get("/api/live-recordings/{rid}")
def get_recording(rid: str, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    chunks = db.scalars(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id).order_by(M.LiveChunk.chunk_index)).all()
    return {"id": rec.id, "session_id": rec.session_id, "status": rec.status, "transcript": rec.transcript or "",
            "created_at": rec.created_at.isoformat(), "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
            "chunks": [_chunk_out(ch) for ch in chunks]}


@app.get("/api/live-recordings/{rid}/chunks/{idx}/video")
def recording_video(rid: str, idx: int, token: str = "", x_live_token: str = Header(default=""), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    rec = _get_recording(db, rid, x_live_token or token)
    ch = db.scalar(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id, M.LiveChunk.chunk_index == idx))
    if not ch or not ch.storage_key: raise HTTPException(404, "Chunk video not found")
    path = Path(__file__).resolve().parent.parent / ch.storage_key
    if not path.is_file(): raise HTTPException(404, "Chunk video file missing")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.post("/api/live-recordings/{rid}/transcript")
def save_recording_transcript(rid: str, body: dict, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    segments = body.get("segments") or []
    by_chunk: dict[int, list[str]] = {}
    for seg in segments:
        try:
            idx = int(seg.get("chunk_index", 0))
        except Exception:
            continue
        text = str(seg.get("text", "")).strip()
        if text:
            by_chunk.setdefault(idx, []).append(text)
    for idx, texts in by_chunk.items():
        ch = db.scalar(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id, M.LiveChunk.chunk_index == idx))
        if ch is not None:
            ch.transcript = " ".join(texts)
    chunks = db.scalars(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id).order_by(M.LiveChunk.chunk_index)).all()
    rec.transcript = " ".join(ch.transcript for ch in chunks if ch.transcript)
    db.commit()
    return {"ok": True, "transcript": rec.transcript, "chunks": {str(ch.chunk_index): ch.transcript for ch in chunks}}


@app.post("/api/live-recordings/{rid}/chunks/{idx}/review")
def review_chunk(rid: str, idx: int, body: dict, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    status = str(body.get("status", ""))
    if status not in ("pending", "verified", "needs_correction", "incorrect", "corrected"):
        raise HTTPException(422, "Invalid review status")
    ch = db.scalar(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id, M.LiveChunk.chunk_index == idx))
    if not ch: raise HTTPException(404, "Chunk not found")
    ch.review_status = status; db.commit()
    return {"ok": True, "review_status": ch.review_status}


@app.post("/api/live-recordings/{rid}/chunks/{idx}/resegment")
def resegment_chunk(rid: str, idx: int, body: dict, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    ch = db.scalar(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id, M.LiveChunk.chunk_index == idx))
    if not ch or not ch.storage_key: raise HTTPException(404, "Chunk not found")
    path = Path(__file__).resolve().parent.parent / ch.storage_key
    if not path.is_file(): raise HTTPException(404, "Chunk video file missing")
    prompt_text = str(body.get("prompt_text", "")).strip()
    nx, ny = body.get("prompt_nx"), body.get("prompt_ny")
    if nx is not None and ny is not None and ch.width and ch.height:
        prompt = ai.build_point_prompt(min(max(int(float(nx) * ch.width), 0), ch.width - 1),
                                       min(max(int(float(ny) * ch.height), 0), ch.height - 1), ch.width, ch.height)
        prompt_label = prompt_text or "tapped object (correction)"
    elif prompt_text:
        prompt = prompt_text; prompt_label = prompt_text
    else:
        raise HTTPException(422, "Provide prompt_text or a tap point for re-segmentation")
    if not ai.live_enabled():
        return {"frames": [], "simulated": True, "note": "No META_API_KEY configured; re-segmentation unavailable."}
    file_id = ai.upload_video_file(path.read_bytes())
    try:
        result = ai.segment_video_clip(file_id, prompt)
    finally:
        ai.delete_video_file(file_id)
    if not result.get("simulated"):
        ch.corrected_segmentation = {"frames": result.get("frames", [])}
        ch.corrected_prompt = prompt_label
        ch.review_status = "corrected"
        db.commit()
    return {"frames": result.get("frames", []), "simulated": result.get("simulated", True),
            "status": result.get("status", "ok"), "note": result.get("note", ""), "corrected_prompt": prompt_label}


@app.post("/api/live-recordings/{rid}/chunks/{idx}/frame-evidence")
def frame_evidence(rid: str, idx: int, body: dict, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    cap_id = str(body.get("capture_session_id", ""))
    cap = db.get(M.CaptureSession, cap_id)
    if not cap: raise HTTPException(404, "Capture session not found")
    ch = db.scalar(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id, M.LiveChunk.chunk_index == idx))
    if not ch or not ch.storage_key: raise HTTPException(404, "Chunk not found")
    path = Path(__file__).resolve().parent.parent / ch.storage_key
    if not path.is_file(): raise HTTPException(404, "Chunk video file missing")
    frame_idx = int(body.get("frame_index", 0))
    import subprocess as _sp
    import imageio_ffmpeg as _ff
    e = M.Evidence(capture_session_id=cap_id, evidence_type="image",
                   description=f"Live recording frame (chunk {idx}, frame {frame_idx})",
                   source_reference=f"live:{rid}:{idx}:{frame_idx}", created_by=who["id"])
    db.add(e); db.flush()
    store_dir = Path(__file__).resolve().parent.parent / "data" / "evidence"
    store_dir.mkdir(parents=True, exist_ok=True)
    out = store_dir / f"{e.id}.jpg"
    proc = _sp.run([_ff.get_ffmpeg_exe(), "-y", "-i", str(path), "-vf", f"select='eq(n\\,{frame_idx})'",
                    "-vframes", "1", "-q:v", "3", str(out)], capture_output=True, timeout=60)
    if proc.returncode != 0 or not out.exists():
        db.rollback(); raise HTTPException(502, "Could not extract that frame from the recording")
    data = out.read_bytes()
    e.storage_key = f"data/evidence/{e.id}.jpg"
    e.extra = {"sha256_16": hashlib.sha256(data).hexdigest()[:16], "size": len(data), "live_recording_id": rid, "chunk_index": idx, "frame_index": frame_idx}
    db.commit(); db.refresh(e)
    return {"id": e.id, "size": len(data)}


@app.delete("/api/live-recordings/{rid}")
def delete_recording(rid: str, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    import shutil as _shutil
    rec = _get_recording(db, rid, x_live_token)
    for ch in db.scalars(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id)).all():
        db.delete(ch)
    store_dir = Path(__file__).resolve().parent.parent / "data" / "live" / rid
    if store_dir.is_dir(): _shutil.rmtree(store_dir, ignore_errors=True)
    db.delete(rec); db.commit()
    return {"ok": True}


def _delete_chunks(db: Session, rec: M.LiveRecording, indexes: list[int]) -> dict:
    base = (Path(__file__).resolve().parent.parent / "data" / "live" / rec.id).resolve()
    deleted, not_found = [], []
    for idx in dict.fromkeys(indexes):  # dedupe, keep order
        ch = db.scalar(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id, M.LiveChunk.chunk_index == idx))
        if ch is None:
            not_found.append(idx); continue
        if ch.storage_key:
            path = (Path(__file__).resolve().parent.parent / ch.storage_key).resolve()
            if base in path.parents and path.is_file():
                path.unlink()
        db.delete(ch)
        deleted.append(idx)
    db.flush()
    chunks = db.scalars(select(M.LiveChunk).where(M.LiveChunk.recording_id == rec.id).order_by(M.LiveChunk.chunk_index)).all()
    rec.transcript = " ".join(ch.transcript for ch in chunks if ch.transcript)
    db.commit()
    return {"deleted": deleted, "not_found": not_found, "remaining": len(chunks), "recording_empty": len(chunks) == 0,
            "transcript": rec.transcript}


@app.delete("/api/live-recordings/{rid}/chunks/{idx}")
def delete_chunk(rid: str, idx: int, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    out = _delete_chunks(db, rec, [idx])
    if out["not_found"]:
        raise HTTPException(404, "Chunk not found")
    return {"ok": True, **out}


@app.post("/api/live-recordings/{rid}/chunks/delete")
def delete_chunks_batch(rid: str, body: dict, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    rec = _get_recording(db, rid, x_live_token)
    raw = body.get("chunk_indexes") or []
    try:
        indexes = [int(i) for i in raw]
    except Exception:
        raise HTTPException(422, "chunk_indexes must be a list of integers")
    if not indexes: raise HTTPException(422, "No chunk_indexes provided")
    if len(indexes) > 200: raise HTTPException(422, "Too many chunks in one delete request")
    return {"ok": True, **_delete_chunks(db, rec, indexes)}


@app.post("/api/live-session/{sid}/chunk")
async def live_chunk(sid: str, frames: list[UploadFile] = File(...), fps: float = Form(default=6.0),
                     prompt_text: str = Form(default=""), prompt_x: int = Form(default=-1), prompt_y: int = Form(default=-1),
                     reset: bool = Form(default=False), audio: UploadFile | None = File(default=None),
                     chunk_start_ms: int = Form(default=0), chunk_end_ms: int = Form(default=0),
                     prompt_source: str = Form(default=""), speech_phrase: str = Form(default=""),
                     x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    session = live_mod.get_session(sid, x_live_token)
    if not session: raise HTTPException(403, "Invalid or expired live session. Start a new live session.")
    if not (1.0 <= fps <= 15.0): raise HTTPException(422, "fps must be between 1 and 15")
    data = []
    for f in frames:
        b = await f.read()
        if len(b) > live_mod.MAX_FRAME_BYTES: raise HTTPException(413, "Frame too large (max 1 MB per frame)")
        data.append(b)
    audio_bytes = None
    audio_suffix = ".webm"
    if audio is not None:
        audio_bytes = await audio.read()
        if len(audio_bytes) > 5 * 1024 * 1024: raise HTTPException(413, "Chunk audio too large (max 5 MB)")
        audio_suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
        if not audio_bytes: audio_bytes = None
    point = (prompt_x, prompt_y) if prompt_x >= 0 and prompt_y >= 0 else None
    try:
        # process_chunk is fully synchronous (ffmpeg + httpx): keep it off the
        # event loop so the voice realtime relay never stalls behind SAM.
        result = await run_in_threadpool(live_mod.process_chunk, session, data, fps, prompt_text, point, reset, db, audio_bytes, audio_suffix,
                                         chunk_start_ms, chunk_end_ms, prompt_source, speech_phrase)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, f"Live segmentation pipeline failed ({type(e).__name__})")
    result["session_id"] = sid
    result["chunk_number"] = session["chunks"]
    return result


@app.post("/api/live-session/{sid}/end")
def live_end(sid: str, x_live_token: str = Header(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    session = live_mod.get_session(sid, x_live_token)
    if not session: raise HTTPException(403, "Invalid or expired live session")
    rid = session.get("recording_id")
    if rid:
        rec = db.get(M.LiveRecording, rid)
        if rec is not None:
            rec.status = "finished"; rec.ended_at = datetime.now(timezone.utc); db.commit()
    live_mod.end_session(sid, x_live_token)
    return {"ok": True, "recording_id": rid}


@app.post("/api/jobs")
def start_job(body: S.JobCreate, db: Session = Depends(get_db), who=Depends(actor)):
    v = db.get(M.ProcedureVersion, body.procedure_version_id)
    if not v: raise HTTPException(404, "Procedure version not found")
    if v.procedure_id != body.procedure_id: raise HTTPException(409, "Procedure version does not belong to the selected procedure")
    if v.status != "approved": raise HTTPException(409, "Jobs can only start from an approved procedure version")
    if body.id:
        existing = db.get(M.JobSession, body.id)
        if existing is not None:
            if existing.procedure_version_id != body.procedure_version_id:
                raise HTTPException(409, "A job with this id already exists for a different procedure version")
            return {"id": existing.id, "status": existing.status, "procedure_version_id": existing.procedure_version_id, "already_registered": True}
    j = M.JobSession(id=body.id or M.uid(), asset_id=body.asset_id, procedure_id=body.procedure_id, procedure_version_id=body.procedure_version_id,
                     technician_id=who["id"])
    db.add(j); db.flush(); audit(db, who["id"], "job.start", "job_session", j.id)
    db.commit(); db.refresh(j)
    return {"id": j.id, "status": j.status, "procedure_version_id": j.procedure_version_id}


@app.get("/api/jobs")
def list_jobs(db: Session = Depends(get_db)):
    out = []
    for j in db.scalars(select(M.JobSession).order_by(M.JobSession.started_at.desc())).all():
        p = db.get(M.Procedure, j.procedure_id)
        n = db.scalar(select(func.count()).select_from(M.JobEvent).where(M.JobEvent.session_id == j.id)) or 0
        out.append({"id": j.id, "procedure_title": p.title if p else "", "status": j.status, "outcome": j.outcome,
                    "technician_id": j.technician_id, "started_at": j.started_at.isoformat(),
                    "ended_at": j.ended_at.isoformat() if j.ended_at else None, "events": n})
    return out


@app.get("/api/jobs/{jid}")
def get_job(jid: str, db: Session = Depends(get_db)):
    j = db.get(M.JobSession, jid)
    if not j: raise HTTPException(404, "Job not found")
    evs = db.scalars(select(M.JobEvent).where(M.JobEvent.session_id == jid).order_by(M.JobEvent.occurred_at)).all()
    return {"id": j.id, "status": j.status, "outcome": j.outcome, "procedure_version_id": j.procedure_version_id,
            "started_at": j.started_at.isoformat(), "ended_at": j.ended_at.isoformat() if j.ended_at else None,
            "events": [{"event_id": e.event_id, "event_type": e.event_type, "step_id": e.step_id,
                        "payload": e.payload, "occurred_at": e.occurred_at.isoformat()} for e in evs],
            "evidence": job_evidence_list(jid, db)}


def job_evidence_list(jid: str, db) -> list:
    """Photos attached during a job (source_reference "job:{jid}" or "job:{jid}:{step}")."""
    items = []
    for e in db.scalars(select(M.Evidence).where(M.Evidence.source_reference.like(f"job:{jid}%")).order_by(M.Evidence.captured_at)).all():
        has_file = bool(e.storage_key) and (Path(__file__).resolve().parent.parent / e.storage_key).is_file()
        items.append({"id": e.id, "description": e.description, "step_id": (e.source_reference or "").split(":")[2] if (e.source_reference or "").count(":") >= 2 else None,
                      "captured_at": e.captured_at.isoformat() if e.captured_at else None,
                      "image_url": f"/api/evidence/{e.id}/image" if e.evidence_type == "image" and has_file else None})
    return items


@app.get("/api/jobs/{jid}/evidence")
def get_job_evidence(jid: str, db: Session = Depends(get_db)):
    if not db.get(M.JobSession, jid): raise HTTPException(404, "Job not found")
    return {"job_id": jid, "evidence": job_evidence_list(jid, db)}


@app.post("/api/jobs/{jid}/evidence")
async def add_job_evidence(jid: str, file: UploadFile = File(...), description: str = Form(default="Job photo evidence"),
                           step_id: str = Form(default=""), db: Session = Depends(get_db), who=Depends(actor)):
    j = db.get(M.JobSession, jid)
    if not j: raise HTTPException(404, "Job not found")
    if j.status == "finished": raise HTTPException(409, "Job is finished; evidence can no longer be attached")
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "Only JPEG, PNG or WebP images are supported")
    data = await file.read()
    if len(data) > MAX_IMG_BYTES: raise HTTPException(413, "Image too large (max 8 MB)")
    digest = hashlib.sha256(data).hexdigest()[:16]
    ref = f"job:{jid}" + (f":{step_id}" if step_id else "")
    e = M.Evidence(capture_session_id=None, evidence_type="image", description=description or "Job photo evidence",
                   source_reference=ref, created_by=who["id"], extra={"sha256_16": digest, "size": len(data)})
    db.add(e); db.flush()
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(file.content_type or "", ".jpg")
    store_dir = Path(__file__).resolve().parent.parent / "data" / "evidence"
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / f"{e.id}{suffix}").write_bytes(data)
    e.storage_key = f"data/evidence/{e.id}{suffix}"
    audit(db, who["id"], "job.evidence", "evidence", e.id, {"job": jid})
    db.commit(); db.refresh(e)
    return {"id": e.id, "size": len(data)}


@app.post("/api/jobs/{jid}/finish")
def finish_job(jid: str, body: S.FinishJob, db: Session = Depends(get_db), who=Depends(actor)):
    j = db.get(M.JobSession, jid)
    if not j: raise HTTPException(404, "Job not found")
    if j.status == "finished": return {"ok": True, "already_finished": True}
    j.status = "finished"; j.outcome = body.outcome; j.finish_reason = body.reason
    j.ended_at = datetime.now(timezone.utc)
    audit(db, who["id"], "job.finish", "job_session", j.id, {"outcome": body.outcome})
    db.commit()
    return {"ok": True}


@app.post("/api/sync/events")
def sync_events(body: S.SyncRequest, db: Session = Depends(get_db), who=Depends(actor)):
    acked, dupes, failed = [], [], []
    seen: set[str] = set()
    for ev in body.events:
        if not ev.event_id or not ev.session_id:
            failed.append({"event_id": ev.event_id, "error": "event_id and session_id are required"}); continue
        if ev.event_id in seen:
            dupes.append(ev.event_id); continue
        seen.add(ev.event_id)
        existing = db.scalar(select(M.JobEvent).where(M.JobEvent.event_id == ev.event_id))
        if existing:
            dupes.append(ev.event_id); continue
        if not db.get(M.JobSession, ev.session_id):
            failed.append({"event_id": ev.event_id, "error": "Unknown session_id"}); continue
        occ = datetime.now(timezone.utc)
        if ev.occurred_at:
            try: occ = datetime.fromisoformat(ev.occurred_at.replace("Z", "+00:00"))
            except ValueError: pass
        db.add(M.JobEvent(event_id=ev.event_id, session_id=ev.session_id, step_id=ev.step_id,
                          event_type=ev.event_type, payload=ev.payload, occurred_at=occ, created_by=who["id"]))
        acked.append(ev.event_id)
    db.commit()
    return {"acknowledged": acked, "duplicates": dupes, "failed": failed}


@app.post("/api/ask")
def ask(body: S.AskRequest, db: Session = Depends(get_db)):
    chunks: list[str] = []
    if body.procedure_version_id:
        v = db.get(M.ProcedureVersion, body.procedure_version_id)
        if v: chunks += [f"{s.title}: {s.instruction}" for s in v.steps]
    hits = search_manuals(q=body.question, db=db) if body.question else []
    chunks += [h["snippet"] for h in hits[:3]]
    q = body.question.lower()
    chunks = [c for c in chunks if any(w in c.lower() for w in q.split() if len(w) > 3)] or chunks[:3]
    return ai.answer_question(body.question, chunks)


@app.get("/api/audit")
def get_audit(db: Session = Depends(get_db)):
    return [{"actor": a.actor, "action": a.action, "entity_id": a.entity_id, "created_at": a.created_at.isoformat()}
            for a in db.scalars(select(M.AuditLog).order_by(M.AuditLog.created_at.desc()).limit(100)).all()]


@app.post("/api/seed")
def seed(db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(M.Procedure)):
        return {"seeded": False, "note": "Demo data already present"}
    asset = M.Asset(name="Benchtop Cable Trainer v1", asset_type="training-assembly", model="BCT-1",
                    description="Harmless desk-sized training assembly: enclosure, blue adjustment knob, cable harness.")
    db.add(asset); db.flush()
    proc = M.Procedure(title="Inspect and reseat the trainer cable harness", asset_id=asset.id, asset_type="training-assembly")
    db.add(proc); db.flush()
    ver = M.ProcedureVersion(procedure_id=proc.id, version_number=1, status="approved", summary="Visual inspection and reseat of the low-voltage trainer harness.",
                             prerequisites="Trainer powered off and unplugged. Phillips screwdriver and inspection light available.",
                             reviewed_by="demo-reviewer", reviewed_at=datetime.now(timezone.utc),
                             source_evidence={"origin": "seeded-demo", "note": "Deterministic demo data, not AI output."})
    db.add(ver); db.flush()
    steps = [
        ("Power off and open the enclosure", "Confirm the trainer is powered off, then remove the two enclosure screws and lift the cover.", "Cover removed; no cables pinched.", ["Phillips screwdriver"]),
        ("Inspect the blue adjustment knob", "Check the blue adjustment knob turns smoothly through its full range without grinding.", "Knob turns smoothly; pointer aligns with the scale.", ["Inspection light"]),
        ("Reseat the cable harness", "Press each harness connector firmly until it seats; confirm the latch engages on the main connector.", "All connectors seated; latch engaged.", []),
        ("Check cable routing", "Confirm cables follow the guide clips and do not touch the knob shaft.", "Cables clipped, clear of moving parts.", []),
        ("Close and verify", "Replace the cover and screws, power on, and confirm the indicator lights in sequence.", "Indicator sequence completes without faults.", ["Phillips screwdriver"]),
    ]
    for i, (t, ins, exp, tools) in enumerate(steps, start=1):
        db.add(M.ProcedureStep(procedure_version_id=ver.id, step_order=i, title=t, instruction=ins, expected_result=exp, required_tools=tools))
    man = M.Manual(title="Benchtop Cable Trainer - Operator Notes", model="BCT-1", document_version="1.0",
                   extracted_text="The blue adjustment knob controls trainer speed. Always power off before opening the enclosure. The harness latch must click when seated.")
    db.add(man); db.flush()
    db.add(M.ManualChunk(manual_id=man.id, chunk_index=0, page_number=1, text=man.extracted_text))
    db.commit()
    return {"seeded": True, "procedure_id": proc.id, "version_id": ver.id}


# ---------------------------------------------------------------------------
# Frontend hosting (production): serve the built PWA from this same origin so
# the manifest, service worker and /api calls share one scope. Skipped when no
# dist exists (local dev uses the Vite server on :5173 with its /api proxy).
# Registered last: API routes above always take precedence.
# ---------------------------------------------------------------------------
def _frontend_dist() -> Path | None:
    env = _os.getenv("FRONTEND_DIST")
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve()
    candidates += [here.parent.parent.parent / "frontend" / "dist", here.parent.parent / "frontend" / "dist"]
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


_DIST = _frontend_dist()
if _DIST is not None:
    from fastapi.responses import FileResponse as _FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "Not found")
        candidate = (_DIST / full_path).resolve()
        if candidate.is_file() and _DIST.resolve() in candidate.parents:
            if candidate.name == "manifest.webmanifest":
                media = "application/manifest+json"
            elif candidate.name == "assetlinks.json":
                # Android's asset-link verifier requires application/json;
                # system mimetypes tables map .json inconsistently.
                media = "application/json"
            else:
                media = None
            headers = {"Cache-Control": "no-store"} if candidate.name == "sw.js" else None
            return _FileResponse(candidate, media_type=media, headers=headers)
        return _FileResponse(_DIST / "index.html")
