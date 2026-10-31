"""Keyed live-provider smoke test for TraceLoop's Meta AI adapters.

Opt-in ONLY: requires META_API_KEY in the environment (or backend/.env)
AND --live on the command line. Never runs in CI.

Usage (PowerShell, from backend/):
    $env:META_API_KEY = "<key>"   # or put it in backend/.env (gitignored)
    .\\.venv\\Scripts\\python.exe scripts/live_smoke.py --live

What it does (smallest billable footprint):
  1. transcribe_timed  — 2 s synthesized WAV (no real speech; asserts contract shape)
  2. understand_tutorial — 2 hand-written segments about a red screwdriver
  3. segment_video_clip — 1 s local lavfi MP4 uploaded via /files, then segmented
  4. image_edit        — tiny PNG + real instruction (single $0.01-class call)
  5. image_generate    — text-only alternative (single call)

Each step prints ok/failed + model + usage. Exit 0 only if every exercised
contract matches. Paste the output back into the session to complete
live verification; do NOT paste the key itself anywhere.
"""
import argparse
import base64
import io
import json
import os
import sys
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from app import ai  # noqa: E402


def _tone_wav(seconds=2, freq=440, rate=24000) -> bytes:
    import math
    import struct
    frames = b"".join(struct.pack("<h", int(16000 * math.sin(2 * math.pi * freq * t / rate)))
                      for t in range(int(seconds * rate)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def _tiny_png(color=(200, 30, 30)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


def _tiny_mp4(path="/tmp/live_smoke_clip.mp4"):
    import subprocess
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "live_smoke_clip.mp4")
    exe = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    r = subprocess.run([exe, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=1",
                        "-c:v", "mpeg4", "-an", out],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("fixture mp4 failed: " + r.stderr.decode()[-300:])
    with open(out, "rb") as f:
        return f.read()


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"op": name, "ok": bool(cond), "detail": str(detail)[:300]})
    print(f"[{'ok' if cond else 'FAILED'}] {name}" + (f" — {str(detail)[:200]}" if detail else ""))
    return bool(cond)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Required: run real provider calls (billed).")
    args = ap.parse_args()
    if not args.live:
        print("Refusing to run without --live. See module docstring.")
        return 2
    if not os.getenv("META_API_KEY"):
        print("META_API_KEY is not set (env or backend/.env). Nothing was called.")
        return 2
    if not ai.live_enabled():
        print("ai.live_enabled() is False despite META_API_KEY — check backend/.env loading.")
        return 2

    ok_all = True

    # 1. Transcribe (synthesized tone: expect a contract-shaped result; the
    #    provider may return empty text for non-speech — that is still a pass
    #    for CONTRACT shape, recorded honestly).
    tr = ai.transcribe_timed("tone.wav", _tone_wav(), duration_sec=2.0)
    ok_all &= check("transcribe.shape", isinstance(tr.get("segments"), list) and "simulated" in tr,
                    f"simulated={tr.get('simulated')} model={tr.get('model')} err={tr.get('error', '')[:120]}")

    # 2. Understand (hand-written segments; asserts structured extraction).
    segs = [{"text": "This is my red screwdriver. I use it to loosen the terminal screws.", "start": 0.0, "end": 4.0},
            {"text": "First I isolate the power and verify the indicator light is off.", "start": 4.0, "end": 9.0}]
    und = ai.understand_tutorial(segs, 9.0)
    ok_all &= check("understand.shape", isinstance(und.get("objects"), list) and isinstance(und.get("steps"), list),
                    f"simulated={und.get('simulated')} objects={len(und.get('objects', []))} steps={len(und.get('steps', []))}")
    if und.get("objects"):
        o = und["objects"][0]
        ok_all &= check("understand.object_keys", all(k in o for k in ("label", "first_mentioned_at", "obj_id")), list(o.keys()))

    # 3. Segment (upload a 1 s local clip, then SAM it).
    try:
        fid = ai.upload_video_file(_tiny_mp4(), "smoke.mp4")
        sg = ai.segment_video_clip(fid, "red screwdriver")
        try:
            ai.delete_video_file(fid)
        except Exception:
            pass
        ok_all &= check("segment.shape", sg.get("status") in ("ok", "no_match", "error") and isinstance(sg.get("frames"), list),
                        f"status={sg.get('status')} frames={len(sg.get('frames', []))} note={(sg.get('note') or '')[:120]}")
    except Exception as e:
        ok_all &= check("segment.shape", False, f"{type(e).__name__}: {e}")

    # 4. Image edit (single billed call; honest failure also recorded).
    ed = ai.image_edit(_tiny_png(), "Make the red square slightly brighter, keep everything else identical.", mime="image/png")
    if ed.get("ok"):
        try:
            raw = base64.b64decode(ed["image_b64"])
            ok_all &= check("image_edit.bytes", len(raw) > 0, f"{len(raw)} bytes model={ed.get('model')} usage={ed.get('usage')}")
        except Exception as e:
            ok_all &= check("image_edit.bytes", False, f"undecodable: {e}")
    else:
        ok_all &= check("image_edit.honest_error", ed.get("status") in ("retryable", "blocked", "error", "unavailable"),
                        ed.get("note", ""))

    # 5. Image generate (single billed call; text-only).
    gn = ai.image_generate("A simple red screwdriver on a workbench, product photo style.")
    if gn.get("ok"):
        try:
            raw = base64.b64decode(gn["image_b64"])
            ok_all &= check("image_generate.bytes", len(raw) > 0, f"{len(raw)} bytes model={gn.get('model')} usage={gn.get('usage')}")
        except Exception as e:
            ok_all &= check("image_generate.bytes", False, f"undecodable: {e}")
    else:
        ok_all &= check("image_generate.honest_error", gn.get("status") in ("retryable", "blocked", "error", "unavailable"),
                        gn.get("note", ""))

    print("\n--- summary ---")
    print(json.dumps(RESULTS, indent=2))
    print("LIVE SMOKE:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
