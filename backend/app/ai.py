"""Meta AI adapters. All provider calls stay server-side.

Live contracts verified against dev.meta.ai docs (Meta Model API,
https://api.meta.ai/v1, Bearer META_API_KEY):
- Muse Spark: POST /chat/completions (OpenAI-compatible) with
  response_format json_schema for structured drafts / grounded answers.
- Muse Voice Transcribe: POST /asr/transcribe?sessionId=... multipart
  {request: JSON, audio: WAV mono 16-bit PCM}. Browser recordings
  (webm/mp4/ogg) are converted to WAV with the ffmpeg binary bundled
  via imageio-ffmpeg before upload.
- SAM 3.1: POST /responses model=sam-3.1 with input_text + input_image
  (data URL); segmentation arrives as special-token output_text parsed
  here (boxes in source pixels, masks via meta_sam_parser -> SVG path).

When META_API_KEY is unset, or a live call fails, adapters return
deterministic, clearly labelled simulated results so the product loop
can be demonstrated and tested offline. Simulated output is never
marked as a live API result.
"""
import base64
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)
except ImportError:
    pass

META_API_KEY = os.getenv("META_API_KEY", "")
META_BASE_URL = os.getenv("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
SPARK_MODEL = os.getenv("MUSE_SPARK_MODEL", "muse-spark-1.3")
SAM_MODEL = os.getenv("SAM_MODEL", "sam-3.1")
VOICE_MODEL = os.getenv("VOICE_MODEL", "muse-voice-transcribe-1.0")
IMAGE_MODEL = os.getenv("MUSE_IMAGE_MODEL", "muse-image-1.0")
# Cost control: single-image calls only, low reasoning pass (same $0.01/image price).
IMAGE_REASONING = os.getenv("MUSE_IMAGE_REASONING", "low")
IMAGE_TIMEOUT = int(os.getenv("MUSE_IMAGE_TIMEOUT", "180"))


def live_enabled() -> bool:
    return bool(META_API_KEY)


def _headers() -> dict:
    return {"Authorization": f"Bearer {META_API_KEY}", "Content-Type": "application/json"}


# ---------------------------------------------------------------- Spark (LLM)

def _chat(content_system: str, content_user: str, json_schema: dict | None = None) -> str:
    """One Muse Spark chat completion. Returns message content text. Raises on failure."""
    import httpx

    body: dict = {
        "model": SPARK_MODEL,
        "messages": [
            {"role": "system", "content": content_system},
            {"role": "user", "content": content_user},
        ],
    }
    if json_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": json_schema}
    r = httpx.post(f"{META_BASE_URL}/chat/completions", headers=_headers(), json=body, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


_DRAFT_SCHEMA = {
    "name": "ProcedureDraft",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "prerequisites": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "instruction": {"type": "string"},
                        "expected_result": {"type": "string"},
                        "required_tools": {"type": "array", "items": {"type": "string"}},
                        "evidence_refs": {"type": "array", "items": {"type": "string"}},
                        "visual_refs": {"type": "array", "items": {"type": "string"}},
                        "verification_notes": {"type": "string"},
                    },
                    "required": ["title", "instruction", "expected_result", "required_tools", "evidence_refs", "visual_refs", "verification_notes"],
                    "additionalProperties": False,
                },
            },
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "safety_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "summary", "prerequisites", "steps", "uncertainties", "missing_information", "safety_notes"],
        "additionalProperties": False,
    },
}


def _fallback_draft(title: str, task_description: str, transcript: str, evidence_ids: list[str]) -> dict:
    """Deterministic evidence-grounded draft. Only restates supplied evidence."""
    text = (transcript or task_description or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    steps = []
    for i, s in enumerate(sentences[:8], start=1):
        steps.append({
            "title": (s.split(":")[0][:60] or f"Step {i}"),
            "instruction": s,
            "expected_result": "Technician visually confirms the described result before continuing.",
            "required_tools": [],
            "evidence_refs": evidence_ids,
            "visual_refs": [],
            "verification_notes": "Verify against source evidence; do not assume unspecified values.",
        })
    if not steps:
        steps = [{
            "title": "Confirm task scope with expert",
            "instruction": "Evidence is insufficient to draft steps. Ask the expert to describe each action and its expected result.",
            "expected_result": "Expert confirms the missing steps.",
            "required_tools": [], "evidence_refs": evidence_ids, "visual_refs": [],
            "verification_notes": "Incomplete draft - human input required.",
        }]
    return {
        "title": title,
        "summary": task_description or "Draft generated from capture evidence. Requires human review.",
        "prerequisites": "Confirm the training assembly is powered off and all listed tools are available. (Verify before approval.)",
        "steps": steps,
        "uncertainties": ["Exact tool sizes and any numeric settings were not specified in evidence and must be confirmed by the reviewer."],
        "missing_information": [] if len(sentences) >= 2 else ["Step-by-step narration with expected results for each step."],
        "safety_notes": ["Training assembly only. Stop and record an issue if the observed condition does not match the instruction."],
    }


def generate_draft(title: str, task_description: str, transcript: str, manual_excerpt: str, evidence_ids: list[str]) -> dict:
    """Muse Spark structured draft, with deterministic labelled fallback."""
    if not live_enabled():
        return {"draft": _fallback_draft(title, task_description, transcript, evidence_ids), "model": SPARK_MODEL, "simulated": True}
    system = (
        "You draft maintenance procedures ONLY from the supplied evidence. "
        "Never invent torque values, part numbers, measurements, or limits that are not in the evidence. "
        "Put anything unspecified into uncertainties or missing_information. "
        "evidence_refs on a step may only contain ids from the supplied evidence id list (or be empty)."
    )
    user = (
        f"Title: {title}\nTask: {task_description}\nEvidence ids: {evidence_ids}\n"
        f"Transcript:\n{transcript or '(none)'}\nManual excerpt:\n{manual_excerpt or '(none)'}"
    )
    try:
        parsed = json.loads(_chat(system, user, json_schema=_DRAFT_SCHEMA))
        steps = []
        for s in (parsed.get("steps") or [])[:12]:
            steps.append({
                "title": str(s.get("title") or "Step")[:120],
                "instruction": str(s.get("instruction") or ""),
                "expected_result": str(s.get("expected_result") or ""),
                "required_tools": [str(t) for t in (s.get("required_tools") or [])],
                "evidence_refs": [e for e in (s.get("evidence_refs") or []) if e in evidence_ids],
                "visual_refs": [str(v) for v in (s.get("visual_refs") or [])],
                "verification_notes": str(s.get("verification_notes") or ""),
            })
        if not steps:
            raise ValueError("empty steps")
        draft = {
            "title": str(parsed.get("title") or title),
            "summary": str(parsed.get("summary") or task_description or ""),
            "prerequisites": str(parsed.get("prerequisites") or ""),
            "steps": steps,
            "uncertainties": [str(u) for u in (parsed.get("uncertainties") or [])],
            "missing_information": [str(u) for u in (parsed.get("missing_information") or [])],
            "safety_notes": [str(u) for u in (parsed.get("safety_notes") or [])],
        }
        return {"draft": draft, "model": SPARK_MODEL, "simulated": False}
    except Exception as e:  # recoverable provider failure -> labelled fallback
        return {"draft": _fallback_draft(title, task_description, transcript, evidence_ids), "model": SPARK_MODEL,
                "simulated": True, "note": f"Live Muse Spark draft failed ({type(e).__name__}); deterministic fallback shown, not live AI."}


# ---------------------------------------------------------------- Voice

def _to_wav(data: bytes, filename: str) -> bytes:
    """Convert browser audio to mono 16-bit PCM WAV @24kHz via bundled ffmpeg."""
    import imageio_ffmpeg

    suffix = Path(filename or "audio.webm").suffix or ".webm"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(data)
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [exe, "-y", "-i", str(src), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", "-map_metadata", "-1", str(dst)],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0 or not dst.exists():
            raise RuntimeError("ffmpeg conversion failed")
        return dst.read_bytes()


def transcribe_audio(filename: str, data: bytes) -> dict:
    """Muse Voice Transcribe. Mocked (labelled) when no key is configured."""
    if not live_enabled():
        return {
            "text": "",
            "simulated": True,
            "model": VOICE_MODEL,
            "note": "No META_API_KEY configured. Paste or type the transcript, or configure the key and retry. This placeholder is not a live transcription.",
        }
    import httpx

    try:
        wav = data if data[:4] == b"RIFF" else _to_wav(data, filename)
    except Exception as e:
        return {"text": "", "simulated": False, "error": f"Audio conversion to WAV failed ({type(e).__name__}). Record again or paste the transcript.", "model": VOICE_MODEL}
    try:
        r = httpx.post(
            f"{META_BASE_URL}/asr/transcribe?sessionId={uuid.uuid4()}",
            headers={"Authorization": f"Bearer {META_API_KEY}"},
            files={
                "request": (None, json.dumps({"mode": "PUSH_TO_TALK", "model": VOICE_MODEL, "audioEncoding": "WAV"}), "application/json"),
                "audio": ("audio.wav", wav, "audio/wav"),
            },
            timeout=90,
        )
        r.raise_for_status()
        body = r.json()
        text = body.get("transcript") or " ".join(t.get("transcript", "") for t in body.get("turns", [])).strip()
        return {"text": text, "simulated": False, "model": VOICE_MODEL, "raw_keys": list(body.keys())}
    except Exception as e:  # recoverable provider failure
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" HTTP {status}" if status else ""
        return {"text": "", "simulated": False, "error": f"Transcription failed: {type(e).__name__}{detail}", "model": VOICE_MODEL}


# ---------------------------------------------------------------- SAM 3.1

def _placeholder_geometry(prompt_text: str) -> dict:
    p = prompt_text.lower()
    cx = 0.5 + (0.08 if "knob" in p else -0.05 if "left" in p else 0.0)
    cy = 0.45
    return {"type": "bbox", "bbox_norm": [round(cx - 0.14, 3), round(cy - 0.14, 3), round(cx + 0.14, 3), round(cy + 0.14, 3)], "label": prompt_text, "objects": [], "mask": None}


_BOX_RE = re.compile(r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([\d.]+))?\|>")
_MASK_RE = re.compile(r"<\|mask;x=0;y=0(?:;c=[\d.]+)?;data=(\d+),(\d+),([~!])(.*?)\|>", re.S)


def _mask_svg(mask_match: re.Match) -> dict | None:
    try:
        from meta_sam_parser import SegmentationMask, decode_mask_to_svg_path

        h, w, enc, payload = int(mask_match.group(1)), int(mask_match.group(2)), mask_match.group(3), mask_match.group(4)
        mask = SegmentationMask(
            encoding="one_bit" if enc == "!" else "lossless",
            payload=enc + payload, width=w, height=h,
        )
        return {"svg_path": decode_mask_to_svg_path(mask), "width": w, "height": h}
    except Exception:
        return None


def segment_image(prompt_text: str, image_bytes: bytes | None = None, filename: str = "photo.jpg", content_type: str = "image/jpeg",
                  prompt_point_norm: tuple[float, float] | None = None) -> dict:
    """SAM 3.1 via POST /responses. Labelled simulated bbox only as fallback.

    prompt_point_norm=(nx, ny) in 0..1 switches to a point prompt (tap-to-segment)
    built with build_point_prompt in media pixels; prompt_text is then only a label.
    """
    display_label = prompt_text or "tapped object"
    placeholder = _placeholder_geometry(display_label)
    if not live_enabled():
        return {"geometry": placeholder, "model": SAM_MODEL, "simulated": True, "status": "ok",
                "note": "No META_API_KEY configured; showing simulated highlight."}
    if not image_bytes:
        return {"geometry": placeholder, "model": SAM_MODEL, "simulated": True, "status": "ok",
                "note": "This evidence has no stored image (attach/capture it again); showing simulated highlight."}
    import httpx

    mime = content_type if content_type in ("image/jpeg", "image/png", "image/webp") else "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    try:
        sam_prompt = prompt_text
        if prompt_point_norm is not None:
            from PIL import Image
            with Image.open(__import__("io").BytesIO(image_bytes)) as im:
                iw, ih = im.size
            px = min(max(int(prompt_point_norm[0] * iw), 0), iw - 1)
            py = min(max(int(prompt_point_norm[1] * ih), 0), ih - 1)
            sam_prompt = build_point_prompt(px, py, iw, ih)
        r = httpx.post(
            f"{META_BASE_URL}/responses",
            headers=_headers(),
            json={
                "model": SAM_MODEL,
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": sam_prompt},
                    {"type": "input_image", "image_url": data_url},
                ]}],
                "stream": False,
                "metadata": {"mask_encoding": "one_bit"},
            },
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        text = "".join(
            part.get("text", "")
            for item in body.get("output", []) if isinstance(item, dict)
            for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"
        )
        if not text.strip():
            return {"geometry": {"type": "bbox", "bbox_norm": [], "label": display_label, "objects": [], "mask": None},
                    "model": SAM_MODEL, "simulated": False, "status": "no_match",
                    "note": f"SAM 3.1 found no match for “{display_label}” in this photo."}
        boxes = list(_BOX_RE.finditer(text))
        masks = list(_MASK_RE.finditer(text))
        if not boxes:
            raise ValueError("no box records in SAM output")
        objects = []
        for i, b in enumerate(boxes):
            oid, x1, y1, x2, y2, w, h = (int(b.group(j)) for j in range(1, 8))
            conf = float(b.group(8)) if b.group(8) else None
            mask = _mask_svg(masks[i]) if i < len(masks) else None
            objects.append({
                "object_id": oid,
                "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
                "bbox_px": [x1, y1, x2, y2], "image_size": [w, h],
                "confidence": conf, "mask": mask,
            })
        first = objects[0]
        geometry = {"type": "bbox", "bbox_norm": first["bbox_norm"], "label": display_label,
                    "objects": objects, "mask": first.get("mask"), "image_size": first["image_size"]}
        return {"geometry": geometry, "model": SAM_MODEL, "simulated": False, "status": "ok"}
    except Exception as e:  # recoverable provider failure -> labelled fallback
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" HTTP {status}" if status else ""
        return {"geometry": placeholder, "model": SAM_MODEL, "simulated": True, "status": "ok",
                "note": f"Live SAM failed ({type(e).__name__}{detail}); showing simulated highlight, not a live result."}


_SUGGEST_SCHEMA = {
    "name": "SegmentSuggestions",
    "schema": {
        "type": "object",
        "properties": {"suggestions": {"type": "array", "items": {"type": "string"}}},
        "required": ["suggestions"], "additionalProperties": False,
    },
}


def suggest_segment_prompts(image_bytes: bytes | None, content_type: str = "image/jpeg") -> dict:
    """Muse Spark image understanding: name visible objects for SAM prompts."""
    if not live_enabled():
        return {"suggestions": [], "simulated": True, "model": SPARK_MODEL,
                "note": "No META_API_KEY configured; object suggestions unavailable."}
    if not image_bytes:
        return {"suggestions": [], "simulated": False, "model": SPARK_MODEL,
                "note": "This evidence has no stored image to inspect."}
    import httpx

    mime = content_type if content_type in ("image/jpeg", "image/png", "image/webp") else "image/jpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    try:
        r = httpx.post(
            f"{META_BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": SPARK_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "List 3 to 5 concrete objects clearly visible in this image. Each item must be a short noun phrase of 1-4 words (e.g. 'blue adjustment knob'), most prominent first. Name only objects you can actually see."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]}],
                "response_format": {"type": "json_schema", "json_schema": _SUGGEST_SCHEMA},
            },
            timeout=90,
        )
        r.raise_for_status()
        parsed = json.loads(r.json()["choices"][0]["message"]["content"] or "{}")
        sugg = [str(s).strip() for s in (parsed.get("suggestions") or []) if str(s).strip()][:5]
        return {"suggestions": sugg, "simulated": False, "model": SPARK_MODEL}
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" HTTP {status}" if status else ""
        return {"suggestions": [], "simulated": True, "model": SPARK_MODEL,
                "note": f"Object suggestions failed ({type(e).__name__}{detail}); type a prompt or tap the object instead."}


# ---------------------------------------------------------------- Muse Image (muse-image-1.0)

_IMAGE_TOOLS_OFF = {"enable_image_search": False, "enable_web_search": False, "enable_shell": False}


def _image_error(e: Exception, op: str) -> dict:
    """Honest failure envelope. Never fabricates image bytes.

    503 (retryable) and 5xx are surfaced distinctly from 400 validation /
    safety blocks so callers can decide whether a retry makes sense.
    """
    status = getattr(getattr(e, "response", None), "status_code", None)
    detail = f" HTTP {status}" if status else ""
    try:
        body = getattr(e, "response", None).json() if getattr(e, "response", None) is not None else {}
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        code = str(err.get("code", "") or "")
        msg = str(err.get("message", "") or "")
    except Exception:
        code, msg = "", ""
    if status == 503:
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "retryable",
                "note": f"Muse Image temporarily unavailable{detail} — safe to retry once. {msg}".strip()}
    if status == 400 and code == "content_policy_violation":
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "blocked",
                "note": "Muse Image declined this prompt (safety filter). Rephrase the request."}
    return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
            "note": f"Muse Image {op} failed ({type(e).__name__}{detail}). Original image kept." + (f" {msg}" if msg and len(msg) < 200 else "")}


def _image_result(data: dict, usage: dict | None) -> dict:
    return {"ok": True, "model": IMAGE_MODEL, "simulated": False, "status": "ok",
            "image_b64": (data.get("data") or [{}])[0].get("b64_json", ""),
            "output_format": data.get("output_format", "webp"),
            "usage": usage or {}}


def image_edit(image_bytes: bytes, prompt: str, mime: str = "image/png") -> dict:
    """Edit one image with an instruction; keeps the rest intact.

    Uses raw JSON (data-URL reference) so no multipart SDK is required.
    Web/image search tools are disabled: edits must preserve the source,
    never pull in external references.
    """
    if not prompt or not prompt.strip():
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                "note": "An edit instruction is required."}
    if not live_enabled():
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "unavailable",
                "note": "No META_API_KEY configured; image editing unavailable. Original kept."}
    import base64 as _b64
    import httpx
    import time as _time

    data_url = f"data:{mime};base64,{_b64.b64encode(image_bytes).decode()}"
    body = {"model": IMAGE_MODEL, "prompt": prompt.strip(),
            "images": [{"image_url": data_url}], "n": 1,
            "output_format": "png", "reasoning_strength": IMAGE_REASONING,
            "tool_enablement": dict(_IMAGE_TOOLS_OFF)}
    last: dict | None = None
    for attempt in (1, 2):
        try:
            r = httpx.post(f"{META_BASE_URL}/images/edits", headers=_headers(), json=body, timeout=IMAGE_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            if not ((payload.get("data") or [{}])[0].get("b64_json")):
                return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                        "note": "Muse Image returned no image bytes. Original kept."}
            out = _image_result(payload, payload.get("usage"))
            out["attempts"] = attempt
            return out
        except Exception as e:
            last = _image_error(e, "edit")
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 503 and attempt == 1:
                _time.sleep(2)  # single bounded retry for retryable failures only
                continue
            return last
    return last or {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                    "note": "Muse Image edit failed. Original kept."}


def image_generate(prompt: str, reference_bytes: list[tuple[bytes, str]] | None = None) -> dict:
    """Text-to-image, optionally steered by reference images (data URLs).

    References guide composition only; the result is ALWAYS labelled an
    AI-generated illustrative alternative, never source evidence.
    """
    if not prompt or not prompt.strip():
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                "note": "A description is required."}
    if not live_enabled():
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "unavailable",
                "note": "No META_API_KEY configured; image generation unavailable."}
    import base64 as _b64
    import httpx
    import time as _time

    images = []
    for raw, mime in (reference_bytes or [])[:4]:
        images.append({"image_url": f"data:{mime};base64,{_b64.b64encode(raw).decode()}"})
    body: dict = {"model": IMAGE_MODEL, "prompt": prompt.strip(), "n": 1,
                 "output_format": "png", "reasoning_strength": IMAGE_REASONING,
                 "tool_enablement": dict(_IMAGE_TOOLS_OFF)}
    if images:
        body["images"] = images
    endpoint = "/images/edits" if images else "/images/generations"
    last: dict | None = None
    for attempt in (1, 2):
        try:
            r = httpx.post(f"{META_BASE_URL}{endpoint}", headers=_headers(), json=body, timeout=IMAGE_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            if not ((payload.get("data") or [{}])[0].get("b64_json")):
                return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                        "note": "Muse Image returned no image bytes."}
            out = _image_result(payload, payload.get("usage"))
            out["attempts"] = attempt
            return out
        except Exception as e:
            last = _image_error(e, "generate")
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 503 and attempt == 1:
                _time.sleep(2)
                continue
            return last
    return last or {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                    "note": "Muse Image generation failed."}


# ---------------------------------------------------------------- SAM 3.1 Video (Option A: clip chunks)


def image_refine(previous_b64: str, instruction: str, mime: str = "image/png") -> dict:
    """One follow-up edit on a just-generated image (stateless refine)."""
    import base64 as _b64
    try:
        raw = _b64.b64decode(previous_b64)
    except Exception:
        return {"ok": False, "model": IMAGE_MODEL, "simulated": False, "status": "error",
                "note": "Previous image data is unreadable; cannot refine."}
    return image_edit(raw, instruction, mime=mime)

def upload_video_file(mp4_bytes: bytes, filename: str = "live-chunk.mp4") -> str:
    """Upload a clip to Meta Files API (purpose=user_data). Returns file_id."""
    import httpx

    r = httpx.post(
        f"{META_BASE_URL}/files",
        headers={"Authorization": f"Bearer {META_API_KEY}"},
        data={"purpose": "user_data"},
        files={"file": (filename, mp4_bytes, "video/mp4")},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["id"]


def delete_video_file(file_id: str) -> None:
    import httpx

    try:
        httpx.delete(f"{META_BASE_URL}/files/{file_id}", headers={"Authorization": f"Bearer {META_API_KEY}"}, timeout=30)
    except Exception:
        pass  # best-effort cleanup; files expire server-side


_FRAME_RE = re.compile(r"<(\d+)f>(.*?)(?=<\d+f>|\Z)", re.S)


def _parse_video_text(text: str, prompt_text: str) -> list[dict]:
    frames: list[dict] = []
    for fm in _FRAME_RE.finditer(text):
        frame_idx = int(fm.group(1))
        seg = fm.group(2)
        boxes = list(_BOX_RE.finditer(seg))
        masks = list(_MASK_RE.finditer(seg))
        objects = []
        for i, b in enumerate(boxes):
            oid, x1, y1, x2, y2, w, h = (int(b.group(j)) for j in range(1, 8))
            conf = float(b.group(8)) if b.group(8) else None
            objects.append({
                "object_id": oid,
                "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
                "bbox_px": [x1, y1, x2, y2], "image_size": [w, h],
                "confidence": conf,
                "mask": _mask_svg(masks[i]) if i < len(masks) else None,
            })
        if objects:
            frames.append({"frame": frame_idx, "objects": objects})
    return frames


def segment_video_clip(file_id: str, prompt_text: str) -> dict:
    """SAM 3.1 video segmentation of one uploaded clip (Meta Model API).

    prompt_text is either a short noun phrase OR a build_object_prompt()
    token string (box/point prompts) — never both, per Meta docs.
    """
    if not live_enabled():
        return {"frames": [], "model": SAM_MODEL, "simulated": True, "status": "ok",
                "note": "No META_API_KEY configured; live video segmentation unavailable."}
    import httpx

    try:
        r = httpx.post(
            f"{META_BASE_URL}/responses",
            headers=_headers(),
            json={
                "model": SAM_MODEL,
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": prompt_text},
                    {"type": "input_video", "file_id": file_id},
                ]}],
                "stream": False,
                "metadata": {"mask_encoding": "one_bit", "include_confidence": "true", "propagation_direction": "forward"},
            },
            timeout=180,
        )
        r.raise_for_status()
        body = r.json()
        text = "".join(
            part.get("text", "")
            for item in body.get("output", []) if isinstance(item, dict)
            for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"
        )
        if not text.strip():
            return {"frames": [], "model": SAM_MODEL, "simulated": False, "status": "no_match",
                    "note": "SAM 3.1 found no match in this clip. Try a clearer prompt or re-tap the object."}
        frames = _parse_video_text(text, prompt_text)
        if not frames:
            return {"frames": [], "model": SAM_MODEL, "simulated": False, "status": "no_match",
                    "note": "SAM 3.1 returned no tracked objects in this clip."}
        return {"frames": frames, "model": SAM_MODEL, "simulated": False, "status": "ok"}
    except Exception as e:  # recoverable provider failure
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" HTTP {status}" if status else ""
        return {"frames": [], "model": SAM_MODEL, "simulated": True, "status": "error",
                "note": f"Live SAM video failed ({type(e).__name__}{detail})."}


def build_point_prompt(x: int, y: int, w: int, h: int, obj_id: int = 1, frame: int = 0) -> str:
    from meta_sam_parser import FramePrompt, PromptObject, PromptPoint, build_object_prompt

    return build_object_prompt(size=(w, h), objects=[PromptObject(id=obj_id, prompts=[FramePrompt(frame=frame, points=[PromptPoint(x, y)])])])


def build_box_prompt(bbox_px: list[int], w: int, h: int, obj_id: int = 1) -> str:
    from meta_sam_parser import FramePrompt, PromptBox, PromptObject, build_object_prompt

    x1, y1, x2, y2 = bbox_px
    return build_object_prompt(size=(w, h), objects=[PromptObject(id=obj_id, prompts=[FramePrompt(frame=0, box=PromptBox(x1, y1, x2 + 1, y2 + 1))])])


# ---------------------------------------------------------------- Tutorial (Muse Voice turns + Spark)

def transcribe_timed(filename: str, data: bytes, duration_sec: float = 0) -> dict:
    """Muse Voice with ENDPOINTING: returns turn-level timed segments.

    Muse Voice has no word timestamps: segments are speech turns with
    startMs/endMs. If turns come back empty, the whole transcript is one
    segment spanning the audio (documented fallback).
    """
    if not live_enabled():
        return {"text": "", "segments": [], "simulated": True, "model": VOICE_MODEL,
                "note": "No META_API_KEY configured."}
    import httpx

    try:
        wav = data if data[:4] == b"RIFF" else _to_wav(data, filename)
    except Exception as e:
        return {"text": "", "segments": [], "simulated": False, "error": f"Audio conversion failed ({type(e).__name__})", "model": VOICE_MODEL}
    try:
        r = httpx.post(
            f"{META_BASE_URL}/asr/transcribe?sessionId={uuid.uuid4()}",
            headers={"Authorization": f"Bearer {META_API_KEY}"},
            files={
                "request": (None, json.dumps({"mode": "ENDPOINTING", "model": VOICE_MODEL, "audioEncoding": "WAV"}), "application/json"),
                "audio": ("audio.wav", wav, "audio/wav"),
            },
            timeout=300,
        )
        r.raise_for_status()
        body = r.json()
        text = body.get("transcript") or ""
        segments = []
        for t in body.get("turns", []) or []:
            tx = (t.get("transcript") or "").strip()
            if tx:
                segments.append({"text": tx, "start": round(float(t.get("startMs", 0)) / 1000, 2),
                                 "end": round(float(t.get("endMs", 0)) / 1000, 2)})
        if not segments and text.strip():
            segments = [{"text": text.strip(), "start": 0.0, "end": round(float(duration_sec or 0), 2)}]
        if not text.strip() and segments:
            text = " ".join(s["text"] for s in segments)
        return {"text": text, "segments": segments, "simulated": False, "model": VOICE_MODEL,
                "audio_duration_ms": body.get("audioDurationMs")}
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f" HTTP {status}" if status else ""
        return {"text": "", "segments": [], "simulated": False, "error": f"Transcription failed: {type(e).__name__}{detail}", "model": VOICE_MODEL}


_UNDERSTAND_SCHEMA = {
    "name": "TutorialUnderstanding",
    "schema": {
        "type": "object",
        "properties": {
            "objects": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "first_mentioned_at": {"type": "number"}, "obj_id": {"type": "integer"}},
                "required": ["label", "first_mentioned_at", "obj_id"], "additionalProperties": False}},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "step_number": {"type": "integer"}, "title": {"type": "string"},
                "start": {"type": "number"}, "end": {"type": "number"},
                "summary": {"type": "string"}, "objects_used": {"type": "array", "items": {"type": "integer"}}},
                "required": ["step_number", "title", "start", "end", "summary", "objects_used"], "additionalProperties": False}},
        },
        "required": ["objects", "steps"], "additionalProperties": False,
    },
}

_GUIDE_SCHEMA = {
    "name": "TutorialGuide",
    "schema": {
        "type": "object",
        "properties": {
            "guide_markdown": {"type": "string"},
            "materials": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["guide_markdown", "materials"], "additionalProperties": False,
    },
}


def understand_tutorial(segments: list[dict], duration_sec: float) -> dict:
    """Muse Spark: extract objects + steps from a timed transcript."""
    if not live_enabled():
        return {"objects": [], "steps": [], "simulated": True, "model": SPARK_MODEL}
    timed = "\n".join(f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s.get('text', '')}" for s in segments)
    system = (
        "You analyze a tutorial transcript with segment timestamps (seconds). Extract: "
        "objects = every distinct physical object/tool/part the speaker shows or uses "
        "(label = short noun phrase SAM can segment, e.g. 'red screwdriver'; "
        "first_mentioned_at = when it first appears; obj_id sequential from 1). "
        "Resolve pronouns: 'this', 'it', 'this tool' refer to the most recent object — do not create objects for pronouns. "
        "steps = the tutorial's logical steps in order with start/end seconds inside the video duration, "
        "a short title, a 1-2 sentence summary from the transcript, and objects_used as obj_id list. "
        "Use ONLY what the transcript supports; never invent objects, values, or steps."
    )
    try:
        parsed = json.loads(_chat(system, f"Video duration: {duration_sec:.1f}s\nTimed transcript:\n{timed}", json_schema=_UNDERSTAND_SCHEMA))
        objects, seen = [], set()
        for i, o in enumerate(parsed.get("objects") or [], start=1):
            label = str(o.get("label") or "").strip()
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            objects.append({"label": label, "first_mentioned_at": max(0.0, min(float(o.get("first_mentioned_at", 0)), duration_sec)),
                            "obj_id": i, "status": "pending", "confidence": None, "illustration": "", "overlay": "", "track": []})
        valid_ids = {o["obj_id"] for o in objects}
        steps = []
        for j, s in enumerate(parsed.get("steps") or [], start=1):
            steps.append({"step_number": j, "title": str(s.get("title") or f"Step {j}"),
                          "start": max(0.0, min(float(s.get("start", 0)), duration_sec)),
                          "end": max(0.0, min(float(s.get("end", duration_sec)), duration_sec)),
                          "summary": str(s.get("summary") or ""),
                          "objects_used": [int(x) for x in (s.get("objects_used") or []) if int(x) in valid_ids]})
        return {"objects": objects[:8], "steps": steps, "simulated": False, "model": SPARK_MODEL}
    except Exception as e:
        return {"objects": [], "steps": [], "simulated": True, "model": SPARK_MODEL,
                "note": f"Understanding failed ({type(e).__name__})"}


def generate_guide(title: str, steps: list[dict], objects: list[dict], segments: list[dict],
                   guide_format: str = "work_instruction") -> dict:
    """Muse Spark: final guide markdown + materials from validated steps/objects.

    guide_format selects the presentation structure (work_instruction |
    reference_manual | interactive). Content always comes from the validated
    inputs; unsupported sections are omitted, never invented.
    """
    structure = {
        "work_instruction": (
            "Structure: # title, a 2-3 sentence task objective, ## Before you start (prerequisites + tools), "
            "## Safety only if the transcript supports it, ## Steps with one ### per step including its time range like (0:45-1:10) "
            "and 2-4 imperative sentences starting with a verb, each step ending with an 'Expected:' verification line where supported, "
            "## If something goes wrong only if supported. Never invent tools, values, warnings, or steps."
        ),
        "reference_manual": (
            "Structure: # title plus scope, ## Equipment (only if identifiable from input, else omit), "
            "## Prerequisites, ## Tools and materials (only items named in the input), ## Safety (only transcript-supported notes), "
            "## Procedure overview (2-3 sentences), ## Numbered procedure (same ### per step with time ranges), "
            "## Expected outcomes (only supported checkpoints), ## Troubleshooting (only supported), "
            "## Sources (transcript ranges and objects used). Never invent torque, ratings, measurements, model identities, "
            "or specifications; omit unsupported sections entirely."
        ),
        "interactive": (
            "Structure: # title, one-line objective, ## Before you start (prerequisites + tools only if in input), "
            "## Steps with one ### per step including its time range, each step exactly: one imperative instruction paragraph, "
            "then an 'Expected:' line only if verifiable from input, then a 'Watch for:' safety line only if transcript-supported. "
            "Keep each step self-contained for field execution. Never invent checks, values, or warnings."
        ),
    }.get(guide_format, "")
    if not live_enabled():
        return {"guide_markdown": "", "materials": [], "simulated": True, "model": SPARK_MODEL,
                "format": guide_format}
    system = (
        "Write a clear tutorial guide in Markdown from the validated steps, objects, and transcript excerpts. "
        + structure + " "
        + "A Table of contents is allowed only for the reference_manual format. "
        + "Never invent tools, values, warnings, steps, or specifications."
    )
    user = (f"Title: {title}\nObjects: {json.dumps(objects)}\nSteps: {json.dumps(steps)}\n"
            f"Transcript excerpts:\n" + "\n".join(f"[{s.get('start', 0):.0f}s] {s.get('text', '')}" for s in segments[:60]))
    try:
        parsed = json.loads(_chat(system, user, json_schema=_GUIDE_SCHEMA))
        md = str(parsed.get("guide_markdown") or "").strip()
        if not md:
            raise ValueError("empty guide")
        return {"guide_markdown": md, "materials": [str(m) for m in (parsed.get("materials") or [])], "simulated": False, "model": SPARK_MODEL, "format": guide_format}
    except Exception as e:
        return {"guide_markdown": "", "materials": [o.get("label", "") for o in objects], "simulated": True, "model": SPARK_MODEL, "format": guide_format,
                "note": f"Guide generation failed ({type(e).__name__})"}


def fallback_guide_markdown(title: str, steps: list[dict], objects: list[dict]) -> str:
    lines = [f"# {title}", "", "## What you need", ""]
    lines += [f"- {o.get('label', 'object')}" for o in objects] or ["- (see video)"]
    lines += ["", "## Steps", ""]
    for s in steps:
        lines += [f"### {s.get('step_number', '')}. {s.get('title', '')} ({s.get('start', 0):.0f}s-{s.get('end', 0):.0f}s)", "", s.get("summary", ""), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- Ask (Spark)

def answer_question(question: str, context_chunks: list[str]) -> dict:
    if not context_chunks:
        return {"answer": "No matching approved-procedure or manual excerpt is available locally for this question. Try different keywords, or reconnect to use AI assistance.", "simulated": not live_enabled(), "sources": []}
    if live_enabled():
        try:
            answer = _chat(
                "Answer ONLY from the supplied approved-procedure/manual excerpts. If the excerpts do not answer the question, say so plainly. Do not invent values.",
                f"Question: {question}\n\nExcerpts:\n" + "\n---\n".join(context_chunks[:5]),
            ).strip()
            if answer:
                return {"answer": answer, "simulated": False, "sources": context_chunks[:3], "model": SPARK_MODEL}
        except Exception:
            pass  # fall through to local excerpt answer, labelled simulated
    joined = " ".join(context_chunks)[:1200]
    return {"answer": f"Based on the retrieved approved/manual excerpts: {joined}", "simulated": True, "sources": context_chunks[:3]}
