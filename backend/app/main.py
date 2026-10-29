import asyncio
import hashlib
import json as _json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, WebSocket, WebSocketDisconnect
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
                                ("live_chunks", "prompt_source", "TEXT DEFAULT ''"), ("live_chunks", "speech_phrase", "TEXT DEFAULT ''")):
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
                   "verification_notes": s.verification_notes} for s in v.steps],
    }


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.scalar(select(1)); db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "ai_live": ai.live_enabled(), "models": {"spark": ai.SPARK_MODEL, "segment": ai.SAM_MODEL, "voice": ai.VOICE_MODEL}}


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
    items = []
    if cap_id:
        for e in db.scalars(select(M.Evidence).where(M.Evidence.capture_session_id == cap_id)).all():
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
    return {"version_id": vid, "capture_session_id": cap_id, "evidence": items}


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
                                   verification_notes=s.verification_notes))
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
                               verification_notes=s.verification_notes))
    db.commit(); db.refresh(nv)
    return ver_out(nv)


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
            "objects": job.objects or [], "steps": job.steps or [], "materials": job.materials or [],
            "guide_markdown": job.guide_markdown, "created_at": job.created_at.isoformat()}


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
def list_tutorials(db: Session = Depends(get_db), who=Depends(actor)):
    jobs = db.scalars(select(M.TutorialJob).where(M.TutorialJob.actor == who["id"]).order_by(M.TutorialJob.created_at.desc()).limit(20)).all()
    return [{"id": j.id, "title": j.title, "status": j.status, "progress": j.progress, "access_token": j.access_token,
             "duration_sec": j.duration_sec, "created_at": j.created_at.isoformat()} for j in jobs]


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
    """Deterministically re-inject illustration links after tap corrections (no LLM call)."""
    job = _get_tutorial(db, jid, x_tutorial_token)
    if job.status != "done":
        raise HTTPException(409, "The guide is not finished yet")
    job.guide_markdown = tut.inject_illustrations(job.guide_markdown or "", job.steps or [], job.objects or [])
    db.commit(); db.refresh(job)
    return {"ok": True, "guide_markdown": job.guide_markdown}


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
            media = "application/manifest+json" if candidate.name == "manifest.webmanifest" else None
            return _FileResponse(candidate, media_type=media)
        return _FileResponse(_DIST / "index.html")
