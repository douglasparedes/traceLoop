import { useCallback, useEffect, useRef, useState } from "react";
import { api, authPost, authDelete } from "./api";
import { SAM_LIVE } from "./samLiveConfig";
import LiveTranscribe from "./LiveTranscribe";
import { promptVariants } from "./speechPrompt";

interface LiveMask { svg_path: string; width: number; height: number }
interface LiveObject { object_id: number; bbox_norm: number[]; confidence?: number | null; mask?: LiveMask | null }
interface LiveFrame { frame: number; objects: LiveObject[] }
interface ChunkResp {
  frames: LiveFrame[]; simulated: boolean; status: string; note?: string;
  prompt_kind?: string; frame_count: number; chunk_number: number;
  recording_id?: string; chunk_id?: string; video_url?: string; prompt_used?: string;
}
interface FrameRec { blob: Blob; tMs: number }
interface Draft {
  seq: number; startMs: number; endMs: number; frames: FrameRec[];
  status: "queued" | "sending" | "done" | "failed"; phrase?: string; serverIndex?: number;
}

interface ReplayChunk {
  chunkIndex: number; chunkId?: string; videoUrl: string; token: string;
  byFrame: Record<number, LiveObject[]>; correctedByFrame?: Record<number, LiveObject[]> | null;
  promptKind: string; reviewStatus: string; fps: number; frameCount: number; transcript?: string;
  startMs?: number; endMs?: number;
}

const OBJ_COLORS = ["#ffb020", "#37c8d9", "#b79cff"];

function framesToMap(frames: LiveFrame[] | undefined): Record<number, LiveObject[]> {
  const map: Record<number, LiveObject[]> = {};
  for (const f of frames || []) map[f.frame] = (f.objects || []).slice(0, SAM_LIVE.MAX_OBJECTS);
  return map;
}

export default function LiveMode({ captureId, onEvidenceSaved, onTranscript }: { captureId?: string | null; onEvidenceSaved?: (evidenceId: string) => void; onTranscript?: (text: string) => void }) {
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [paused, setPaused] = useState(false);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [promptText, setPromptText] = useState("blue adjustment knob");
  const [tap, setTap] = useState<{ nx: number; ny: number } | null>(null);
  const [status, setStatus] = useState("Near-live SAM 3.1: the camera records short clips; SAM tracks your prompt through each clip and masks play back here. Expect a 5–10 second delay — this is clip-based, not instant.");
  const [statusKind, setStatusKind] = useState<"warn" | "error" | "ok">("warn");
  const [processing, setProcessing] = useState(false);
  const [lastStatus, setLastStatus] = useState("");
  const [heardPhrase, setHeardPhrase] = useState("");
  const [segLog, setSegLog] = useState("");
  const [speechStatus, setSpeechStatus] = useState("");
  const [selectedChunks, setSelectedChunks] = useState<Set<number>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const [chunkNum, setChunkNum] = useState(0);
  const [simulated, setSimulated] = useState<boolean | null>(null);
  const [stage, setStage] = useState<"live" | "playback">("live");
  const [history, setHistory] = useState<ReplayChunk[]>([]);
  const [selChunk, setSelChunk] = useState(0);
  const [replayFrame, setReplayFrame] = useState(0);
  const [showCorrected, setShowCorrected] = useState(true);
  const [correctionPrompt, setCorrectionPrompt] = useState("");
  const [correctionTap, setCorrectionTap] = useState<{ nx: number; ny: number } | null>(null);
  const replayVideoRef = useRef<HTMLVideoElement | null>(null);
  const audioRecRef = useRef<MediaRecorder | null>(null);
  const audioBlobsRef = useRef<Blob[]>([]);
  const transcriptSegsRef = useRef<{ chunk_index: number; start_ms: number; end_ms: number; text: string }[]>([]);
  const [playback, setPlayback] = useState<{ urls: string[]; byFrame: Record<number, LiveObject[]> }>({ urls: [], byFrame: {} });
  const [playIdx, setPlayIdx] = useState(0);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [camStream, setCamStream] = useState<MediaStream | null>(null);
  const sessionRef = useRef<{ id: string; token: string; recordingId: string } | null>(null);
  const bufferRef = useRef<FrameRec[]>([]);
  const processingRef = useRef(false);
  const draftsRef = useRef<Draft[]>([]);
  const draftSeqRef = useRef(0);
  const liveStartRef = useRef(0);
  const pendingFormingRef = useRef<{ phrase: string; spokenAtMs: number } | null>(null);
  const pendingCorrectionsRef = useRef<{ phrase: string; draft: Draft }[]>([]);
  const promptedRef = useRef(false);
  const resetRef = useRef(false);
  const frameSizeRef = useRef<{ w: number; h: number }>({ w: 0, h: 0 });
  const playbackUrlsRef = useRef<string[]>([]);
  const runningRef = useRef(false);

  const say = (t: string, k: "warn" | "error" | "ok" = "warn") => { setStatus(t); setStatusKind(k); };

  const endSession = useCallback(() => {
    const s = sessionRef.current;
    sessionRef.current = null; promptedRef.current = false;
    if (s) void api.upload(`/api/live-session/${s.id}/end`, new FormData(), { "X-Live-Token": s.token }).catch(() => undefined);
  }, []);

  async function postTranscript() {
    const s = sessionRef.current;
    if (!s?.recordingId || transcriptSegsRef.current.length === 0) return;
    try {
      const r = await authPost<{ transcript: string; chunks: Record<string, string> }>(
        `/api/live-recordings/${s.recordingId}/transcript`,
        { segments: transcriptSegsRef.current }, { "X-Live-Token": s.token });
      setHistory((h) => h.map((x) => ({ ...x, transcript: r.chunks[String(x.chunkIndex)] ?? x.transcript })));
      if (r.transcript) onTranscript?.(r.transcript);
    } catch { /* transcript stays in the browser session; chunks keep their video */ }
  }

  const stopChunkAudio = useCallback(() => {
    const rec = audioRecRef.current;
    audioRecRef.current = null;
    if (rec && rec.state === "recording") { try { rec.stop(); } catch { /* already stopped */ } }
  }, []);

  const stopCamera = useCallback((end = true) => {
    runningRef.current = false; setRunning(false); setPaused(false);
    setCamStream(null);
    stopChunkAudio(); audioBlobsRef.current = [];
    streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null;
    bufferRef.current = [];
    if (end) { void postTranscript(); endSession(); }
  }, [endSession, stopChunkAudio]);

  useEffect(() => () => {
    runningRef.current = false;
    try { audioRecRef.current?.state === "recording" && audioRecRef.current.stop(); } catch { /* ignore */ }
    audioRecRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    playbackUrlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    endSession();
  }, [endSession]);

  useEffect(() => {
    const onVis = () => { if (document.hidden && runningRef.current) { setPaused(true); say("Tab hidden — capture paused to save cost. Resume when you're back."); } };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // Restore the latest saved recording for replay after a reload.
  useEffect(() => {
    void (async () => {
      try {
        type RecChunk = { chunk_index: number; id: string; video_url: string; segmentation?: { frames?: LiveFrame[] }; corrected_segmentation?: { frames?: LiveFrame[] } | null; prompt_kind: string; review_status: string; fps: number; frame_count: number; transcript?: string; start_ms?: number; end_ms?: number };
        type Rec = { id: string; access_token: string; chunks: RecChunk[] };
        const recs = await api.get<Rec[]>("/api/live-recordings");
        const rec = recs.find((x) => x.chunks?.length);
        if (!rec) return;
        setHistory(rec.chunks.map((ch) => ({
          chunkIndex: ch.chunk_index, chunkId: ch.id,
          videoUrl: `${ch.video_url}?token=${encodeURIComponent(rec.access_token)}`, token: rec.access_token,
          byFrame: framesToMap(ch.segmentation?.frames), correctedByFrame: ch.corrected_segmentation ? framesToMap(ch.corrected_segmentation.frames) : null,
          promptKind: ch.prompt_kind, reviewStatus: ch.review_status, fps: ch.fps || SAM_LIVE.TARGET_FPS, frameCount: ch.frame_count, transcript: ch.transcript || "",
          startMs: ch.start_ms || 0, endMs: ch.end_ms || 0,
        })));
        setSelChunk(rec.chunks.length - 1);
      } catch { /* offline / no recordings yet */ }
    })();
  }, []);

  async function startCamera(nextFacing = facing) {
    setStarting(true);
    try {
      if (!sessionRef.current) {
        const s = await api.post<{ session_id: string; token: string; simulated: boolean; recording_id: string }>("/api/live-session/start", {});
        sessionRef.current = { id: s.session_id, token: s.token, recordingId: s.recording_id };
        setSimulated(s.simulated);
      }
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new DOMException("mediaDevices unavailable", "NotSupportedError");
      stopChunkAudio();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      let stream: MediaStream;
      let silent = false;
      let silentReason = "";
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: nextFacing }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: true });
      } catch (e) {
        if (e instanceof DOMException && (e.name === "OverconstrainedError" || e.name === "NotFoundError" || e.name === "NotAllowedError")) {
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
          silent = true;
          silentReason = e.name === "NotAllowedError" ? "microphone permission was denied" : "no working microphone was found";
        } else throw e;
      }
      streamRef.current = stream;
      setCamStream(stream);
      liveStartRef.current = performance.now();
      draftsRef.current = []; draftSeqRef.current = 0; bufferRef.current = []; transcriptSegsRef.current = [];
      // Per-chunk audio track (timesliced to roughly one chunk per blob).
      // MediaRecorder needs an audio-only stream: passing the full A/V stream
      // with an audio mime throws at start() on Chrome/Android.
      audioBlobsRef.current = [];
      const audioTracks = stream.getAudioTracks();
      if (audioTracks.length && typeof MediaRecorder !== "undefined") {
        try {
          const audioOnly = new MediaStream(audioTracks);
          const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
          const rec = mime ? new MediaRecorder(audioOnly, { mimeType: mime }) : new MediaRecorder(audioOnly);
          rec.ondataavailable = (ev) => { if (ev.data.size) audioBlobsRef.current.push(ev.data); };
          rec.onerror = () => { /* chunk audio degrades to silent; video keeps running */ };
          audioRecRef.current = rec;
          rec.start(Math.round((SAM_LIVE.CHUNK_FRAMES / SAM_LIVE.TARGET_FPS) * 1000));
        } catch {
          stopChunkAudio();
          silent = true;
          silentReason = silentReason || "chunk audio could not start on this device";
        }
      } else if (audioTracks.length === 0) {
        silent = true;
        silentReason = silentReason || "no working microphone was found";
      }
      runningRef.current = true; setRunning(true); setPaused(false); setStage("live");
      say(silent
        ? `Camera live (no microphone track${silentReason ? ` — ${silentReason}` : ""}; chunks will be silent). Tap the object on the preview, then keep it in frame.`
        : "Camera + mic live. Tap the object on the preview (or use the concept prompt), then keep it in frame — the first tracked chunk arrives in ~5–10s.");
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      say(name === "NotAllowedError" ? "Camera blocked. Allow camera access in the address-bar site settings, then retry." : e instanceof Error ? e.message : "Camera unavailable.", "error");
    } finally { setStarting(false); }
  }

  useEffect(() => {
    if (running && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => undefined);
    }
  }, [running, stage]);

  async function correctChunk(entry: ReplayChunk, phrase: string): Promise<boolean> {
    const rid = entry.videoUrl.split("/live-recordings/")[1]?.split("/")[0];
    if (!rid) return false;
    try {
      const r = await authPost<{ frames: LiveFrame[]; simulated: boolean; status: string; note?: string }>(
        `/api/live-recordings/${rid}/chunks/${entry.chunkIndex}/resegment`, { prompt_text: phrase }, { "X-Live-Token": entry.token });
      if (r.simulated) { say(r.note || "Correction unavailable (simulated).", "error"); return false; }
      const corrected = framesToMap(r.frames);
      setHistory((h) => h.map((x) => (x.chunkIndex === entry.chunkIndex && x.videoUrl === entry.videoUrl
        ? { ...x, correctedByFrame: corrected, reviewStatus: "corrected" } : x)));
      setShowCorrected(true);
      return r.status === "ok";
    } catch (e) { say(e instanceof Error ? e.message : "Correction failed", "error"); return false; }
  }

  const sendChunk = useCallback(async (draft: Draft): Promise<ChunkResp | null> => {
    const session = sessionRef.current;
    if (!session) return null;
    processingRef.current = true; setProcessing(true);
    const blobs = draft.frames.map((f) => f.blob);
    const urls = blobs.map((b) => URL.createObjectURL(b));
    const started = performance.now();
    try {
      const fd = new FormData();
      blobs.forEach((b, i) => fd.append("frames", new File([b], `frame-${String(i).padStart(4, "0")}.jpg`, { type: "image/jpeg" })));
      const audioBlob = audioBlobsRef.current.shift();
      if (audioBlob) fd.append("audio", new File([audioBlob], audioBlob.type.includes("mp4") ? "chunk-audio.mp4" : "chunk-audio.webm", { type: audioBlob.type || "audio/webm" }));
      fd.append("fps", String(SAM_LIVE.TARGET_FPS));
      fd.append("chunk_start_ms", String(Math.round(draft.startMs)));
      fd.append("chunk_end_ms", String(Math.round(draft.endMs)));
      const useTap = !draft.phrase && tap && !promptedRef.current;
      fd.append("prompt_text", draft.phrase || (useTap ? "" : promptText.trim()));
      fd.append("prompt_source", draft.phrase ? "speech" : useTap ? "tap" : "manual");
      if (draft.phrase) fd.append("speech_phrase", draft.phrase);
      if (useTap) {
        fd.append("prompt_x", String(Math.round(tap.nx * frameSizeRef.current.w)));
        fd.append("prompt_y", String(Math.round(tap.ny * frameSizeRef.current.h)));
      }
      if (resetRef.current) { fd.append("reset", "true"); resetRef.current = false; }
      const r = await api.upload<ChunkResp>(`/api/live-session/${session.id}/chunk`, fd, { "X-Live-Token": session.token });
      draft.serverIndex = r.chunk_number;
      setLastLatencyMs(Math.round(performance.now() - started));
      setChunkNum(r.chunk_number); setSimulated(r.simulated); setLastStatus(r.status);
      setSegLog(`Chunk ${r.chunk_number}: SAM prompt “${r.prompt_used || r.prompt_kind || "—"}” (${r.prompt_kind || ""}) → ${r.simulated ? "simulated/unavailable" : r.status}`);
      if (useTap && r.status === "ok" && !r.simulated) promptedRef.current = true;
      const byFrame: Record<number, LiveObject[]> = {};
      for (const f of r.frames || []) byFrame[f.frame] = (f.objects || []).slice(0, SAM_LIVE.MAX_OBJECTS);
      if (r.video_url && session.recordingId) {
        const videoUrl = `${r.video_url}?token=${encodeURIComponent(session.token)}`;
        setHistory((h) => {
          const entry: ReplayChunk = { chunkIndex: r.chunk_number, chunkId: r.chunk_id, videoUrl, token: session.token,
            byFrame, promptKind: r.prompt_kind || "", reviewStatus: "pending", fps: SAM_LIVE.TARGET_FPS, frameCount: r.frame_count,
            startMs: draft.startMs, endMs: draft.endMs };
          const next = [...h.filter((x) => x.chunkIndex !== entry.chunkIndex || x.videoUrl !== entry.videoUrl), entry].sort((a, b) => a.chunkIndex - b.chunkIndex);
          setSelChunk(next.length - 1);
          return next;
        });
      }
      playbackUrlsRef.current.forEach((u) => URL.revokeObjectURL(u));
      playbackUrlsRef.current = urls;
      setPlayback({ urls, byFrame }); setPlayIdx(0); setStage("playback");
      if (r.simulated) say(r.note || "Live segmentation unavailable — showing your captured clip without masks.", "error");
      else if (r.status === "no_match") say(r.note || "SAM found no match in that clip. Re-tap the object on the live view or clear the prompt.", "warn");
      else say(`Chunk ${r.chunk_number} tracked (${r.prompt_kind || "prompt"}) — playing back while the next chunk records.`, "ok");
      return r;
    } catch (e) {
      urls.forEach((u) => URL.revokeObjectURL(u));
      const msg = e instanceof Error ? e.message : "Chunk upload failed";
      if (msg.includes("403") || msg.toLowerCase().includes("session")) { sessionRef.current = null; promptedRef.current = false; say("Live session expired. Stop and start the camera to begin a new session.", "error"); }
      else say(`Chunk failed (${msg}). Your camera is still running — the next chunk will retry.`, "error");
      return null;
    } finally {
      processingRef.current = false; setProcessing(false);
    }
  }, [promptText, tap]);

  const pumpQueue = useCallback(async () => {
    if (processingRef.current) return;
    const draft = draftsRef.current.find((d) => d.status === "queued");
    if (!draft) return;
    draft.status = "sending";
    const r = await sendChunk(draft);
    draft.status = r ? "done" : "failed";
    // Targeted corrections queued while this chunk was in flight.
    const due = pendingCorrectionsRef.current.filter((c) => c.draft === draft);
    pendingCorrectionsRef.current = pendingCorrectionsRef.current.filter((c) => c.draft !== draft);
    for (const c of due) {
      if (draft.serverIndex) {
        setSpeechStatus(`Re-segmenting Chunk ${draft.serverIndex} with “${c.phrase}” (spoken while it was processing)…`);
        setHistory((h) => {
          const entry = h.find((x) => x.chunkIndex === draft.serverIndex);
          if (entry) void correctChunk(entry, c.phrase).then((ok) => {
            if (ok) setSpeechStatus(`Chunk ${draft.serverIndex} corrected with “${c.phrase}”.`);
          });
          return h;
        });
      }
    }
    void pumpQueue();
  }, [sendChunk]);

  function handleSpeechPhrase(phrase: string, timing: { firstSeenPerf: number; detectedPerf: number }) {
    const spokenAtMs = Math.max(0, timing.firstSeenPerf - liveStartRef.current);
    const spokenSec = (spokenAtMs / 1000).toFixed(1);
    setHeardPhrase(phrase);
    setPromptText(phrase); setTap(null); promptedRef.current = false;
    // Resolve the chunk that was on screen when the phrase began.
    const target = draftsRef.current.find((d) => spokenAtMs >= d.startMs - 250 && spokenAtMs <= d.endMs + 500);
    if (target && target.status === "queued") {
      target.phrase = phrase;
      resetRef.current = true;
      setSegLog(`Heard “${phrase}” at ${spokenSec}s → attached to Chunk ${target.seq} before it was sent.`);
      setSpeechStatus(`“${phrase}” spoken at ${spokenSec}s → will segment Chunk ${target.seq} with it.`);
    } else if (target && target.status === "sending") {
      pendingCorrectionsRef.current.push({ phrase, draft: target });
      resetRef.current = true;
      setSegLog(`Heard “${phrase}” at ${spokenSec}s → Chunk ${target.seq} is already processing; it will be re-segmented when it returns.`);
      setSpeechStatus(`“${phrase}” spoken at ${spokenSec}s → correcting Chunk ${target.seq} when it returns.`);
    } else if (target && target.status === "done" && target.serverIndex) {
      const serverIndex = target.serverIndex;
      resetRef.current = true;
      setSegLog(`Heard “${phrase}” at ${spokenSec}s → Chunk ${serverIndex} already processed; re-segmenting it now.`);
      setSpeechStatus(`“${phrase}” spoken at ${spokenSec}s → re-segmenting Chunk ${serverIndex}.`);
      setHistory((h) => {
        const entry = h.find((x) => x.chunkIndex === serverIndex);
        if (entry) void correctChunk(entry, phrase).then((ok) => { if (ok) setSpeechStatus(`Chunk ${serverIndex} corrected with “${phrase}”.`); });
        return h;
      });
    } else {
      // Spoken in the currently-filling chunk (or just before capture starts).
      pendingFormingRef.current = { phrase, spokenAtMs };
      resetRef.current = true;
      setSegLog(`Heard “${phrase}” at ${spokenSec}s → attached to the chunk now recording.`);
      setSpeechStatus(`“${phrase}” spoken at ${spokenSec}s → attached to the chunk now recording.`);
    }
  }

  // Capture loop
  useEffect(() => {
    if (!running || paused) return;
    const canvas = document.createElement("canvas");
    const timer = window.setInterval(() => {
      const video = videoRef.current;
      if (!video || !streamRef.current) return;
      // The <video> element unmounts in playback stage; capture via a detached draw of the stream is
      // not possible there, so capture only while the live stage is mounted OR keep video mounted.
      if (!video.videoWidth || !video.videoHeight) return;
      const scale = Math.min(1, SAM_LIVE.MAX_WIDTH / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(2, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(2, Math.round(video.videoHeight * scale));
      frameSizeRef.current = { w: canvas.width, h: canvas.height };
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (!blob || !runningRef.current) return;
        bufferRef.current.push({ blob, tMs: Math.max(0, performance.now() - liveStartRef.current) });
        if (bufferRef.current.length >= SAM_LIVE.CHUNK_FRAMES) {
          const frames = bufferRef.current.splice(0, SAM_LIVE.CHUNK_FRAMES);
          draftSeqRef.current += 1;
          const draft: Draft = { seq: draftSeqRef.current, startMs: frames[0].tMs, endMs: frames[frames.length - 1].tMs, frames, status: "queued" };
          const pending = pendingFormingRef.current;
          if (pending && pending.spokenAtMs <= draft.endMs + 500) { draft.phrase = pending.phrase; pendingFormingRef.current = null; }
          draftsRef.current.push(draft);
          // Bounded queue: drop the oldest unsent draft (explicit gap) rather than shifting timing.
          const queued = draftsRef.current.filter((d) => d.status === "queued");
          if (queued.length > 3) {
            const drop = queued[0];
            drop.status = "failed";
            draftsRef.current = draftsRef.current.filter((d) => d !== drop);
            setSegLog(`Dropped queued Chunk ${drop.seq} — SAM pipeline is behind; timeline gap recorded.`);
          }
          void pumpQueue();
        }
      }, "image/jpeg", SAM_LIVE.JPEG_QUALITY);
    }, Math.round(1000 / SAM_LIVE.TARGET_FPS));
    return () => window.clearInterval(timer);
  }, [running, paused, pumpQueue, stage]);

  // Playback loop
  useEffect(() => {
    if (stage !== "playback" || playback.urls.length === 0) return;
    const timer = window.setInterval(() => setPlayIdx((i) => (i + 1) % playback.urls.length), Math.round(1000 / SAM_LIVE.TARGET_FPS));
    return () => window.clearInterval(timer);
  }, [stage, playback.urls.length]);

  function onTapStage(e: React.MouseEvent<HTMLDivElement>) {
    if (stage !== "live") return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    setTap({ nx: Math.min(0.999, Math.max(0, (e.clientX - rect.left) / rect.width)), ny: Math.min(0.999, Math.max(0, (e.clientY - rect.top) / rect.height)) });
    promptedRef.current = false;
    say("Tap set. The next chunk will prompt SAM 3.1 with this point — keep the object in frame.");
  }

  function clearMask() {
    setTap(null); resetRef.current = true; promptedRef.current = false;
    setPlayback((p) => ({ ...p, byFrame: {} }));
    say("Mask cleared. The next chunk starts fresh from the concept prompt (or a new tap).");
  }

  const sel = history[Math.min(selChunk, Math.max(0, history.length - 1))] as ReplayChunk | undefined;
  const activeMap = sel ? (showCorrected && sel.correctedByFrame ? sel.correctedByFrame : sel.byFrame) : {};
  const replayObjects = sel ? (activeMap[replayFrame] || []) : [];

  async function reviewSelected(status: string) {
    if (!sel) return;
    const rid = sel.videoUrl.split("/live-recordings/")[1]?.split("/")[0];
    try {
      await authPost(`/api/live-recordings/${rid}/chunks/${sel.chunkIndex}/review`, { status }, { "X-Live-Token": sel.token });
      setHistory((h) => h.map((x) => (x.chunkIndex === sel.chunkIndex ? { ...x, reviewStatus: status } : x)));
      say(`Chunk ${sel.chunkIndex} marked ${status}.`, "ok");
    } catch (e) { say(e instanceof Error ? e.message : "Review update failed", "error"); }
  }

  async function resegmentSelected(useTap: boolean) {
    if (!sel) return;
    const rid = sel.videoUrl.split("/live-recordings/")[1]?.split("/")[0];
    try {
      say(`Re-segmenting chunk ${sel.chunkIndex} with SAM 3.1…`);
      const r = await authPost<{ frames: LiveFrame[]; simulated: boolean; status: string; note?: string }>(`/api/live-recordings/${rid}/chunks/${sel.chunkIndex}/resegment`, useTap && correctionTap ? { prompt_nx: correctionTap.nx, prompt_ny: correctionTap.ny, prompt_text: correctionPrompt } : { prompt_text: correctionPrompt }, { "X-Live-Token": sel.token });
      if (r.simulated) { say(r.note || "Re-segmentation unavailable (simulated).", "error"); return; }
      const corrected = framesToMap(r.frames);
      setHistory((h) => h.map((x) => (x.chunkIndex === sel.chunkIndex ? { ...x, correctedByFrame: corrected, reviewStatus: "corrected" } : x)));
      setShowCorrected(true);
      say(r.status === "no_match" ? "Re-segmentation found no match — try another prompt or tap." : `Chunk ${sel.chunkIndex} corrected. Toggle Original/Corrected to compare.`, r.status === "no_match" ? "warn" : "ok");
    } catch (e) { say(e instanceof Error ? e.message : "Re-segmentation failed", "error"); }
  }

  async function deleteChunks(indexes: number[]) {
    if (!indexes.length) return;
    // Group by recording (history may mix the restored recording + current session).
    const groups = new Map<string, { token: string; idxs: number[] }>();
    for (const idx of indexes) {
      const entry = history.find((h) => h.chunkIndex === idx);
      if (!entry) continue;
      const rid = entry.videoUrl.split("/live-recordings/")[1]?.split("/")[0];
      if (!rid) continue;
      const g = groups.get(rid) || { token: entry.token, idxs: [] };
      g.idxs.push(idx); groups.set(rid, g);
    }
    const deleted = new Set<number>();
    const failed: number[] = [];
    for (const [rid, g] of groups) {
      try {
        if (g.idxs.length === 1) {
          await authDelete(`/api/live-recordings/${rid}/chunks/${g.idxs[0]}`, { "X-Live-Token": g.token });
          deleted.add(g.idxs[0]);
        } else {
          const r = await authPost<{ deleted: number[]; not_found: number[] }>(`/api/live-recordings/${rid}/chunks/delete`, { chunk_indexes: g.idxs }, { "X-Live-Token": g.token });
          (r.deleted || []).forEach((i) => deleted.add(i));
          (r.not_found || []).forEach((i) => failed.push(i));
        }
      } catch { g.idxs.forEach((i) => failed.push(i)); }
    }
    if (deleted.size) {
      setHistory((h) => {
        const next = h.filter((x) => !deleted.has(x.chunkIndex));
        setSelChunk((cur) => Math.min(cur, Math.max(0, next.length - 1)));
        return next;
      });
      setSelectedChunks((s) => new Set([...s].filter((i) => !deleted.has(i))));
      if (replayVideoRef.current) { replayVideoRef.current.pause(); }
    }
    setConfirmDelete(false);
    if (failed.length) say(`Deleted ${deleted.size} chunk(s); ${failed.length} could not be deleted (${failed.join(", ")}).`, "error");
    else say(`Deleted ${deleted.size} chunk(s). Surviving chunks keep their original numbers.`, "ok");
  }

  async function saveFrameEvidence() {
    if (!sel) return;
    if (!captureId) { say("Create a capture session in Photo mode first, then save a corrected frame as evidence.", "error"); return; }
    const rid = sel.videoUrl.split("/live-recordings/")[1]?.split("/")[0];
    try {
      const r = await authPost<{ id: string }>(`/api/live-recordings/${rid}/chunks/${sel.chunkIndex}/frame-evidence`, { capture_session_id: captureId, frame_index: replayFrame }, { "X-Live-Token": sel.token });
      say("Frame saved as photo evidence. Opening it in Photo mode.", "ok");
      onEvidenceSaved?.(r.id);
    } catch (e) { say(e instanceof Error ? e.message : "Frame export failed", "error"); }
  }

  const waitingFirst = running && processing && playback.urls.length === 0;
  const currentObjects = playback.byFrame[playIdx] || [];
  const slow = lastLatencyMs !== null && lastLatencyMs > SAM_LIVE.SLOW_CHUNK_MS;

  return (
    <div>
      <div className={`live-status ${statusKind === "error" ? "error" : statusKind === "ok" ? "ok" : ""}`} role={statusKind === "error" ? "alert" : "status"}>
        {processing && <span className="spinner" aria-hidden="true" />}
        <span>
          {waitingFirst
            ? "Contacting SAM 3.1… the first tracked chunk takes ~5–10s (clip-based near-live). Keep the object in frame."
            : status}
        </span>
      </div>
      <div className="row" style={{ margin: "10px 0" }} aria-label="Live status indicators">
        <span className="tag ai">{simulated === null ? "SAM 3.1" : simulated ? "SAM unavailable (no key)" : "SAM 3.1 · live"}</span>
        <span className="tag">Target {SAM_LIVE.TARGET_FPS} FPS capture</span>
        {lastLatencyMs !== null && <span className={`tag ${slow ? "warn" : ""}`}>Last chunk {(lastLatencyMs / 1000).toFixed(1)}s{slow ? " (slow)" : ""}</span>}
        {chunkNum > 0 && <span className="tag">Chunk {chunkNum}</span>}
        {stage === "playback" && <span className="tag">Frame {playIdx + 1}/{playback.urls.length} · {currentObjects.length} object(s)</span>}
      </div>

      <div className="live-stage" onClick={onTapStage} role={stage === "live" ? "button" : undefined} aria-label={stage === "live" ? "Live camera preview. Tap the object to segment it." : "Tracked clip playback"}>
        {!running && <div className="live-placeholder">Camera is off. Start the camera, then tap an object or use a concept prompt.</div>}
        {running && <video ref={videoRef} className={stage === "live" ? "live-video" : "live-pip"} autoPlay playsInline muted aria-label="Live camera preview" />}
        {stage === "playback" && playback.urls.length > 0 && (
          <>
            <img className="live-video" src={playback.urls[playIdx]} alt="Tracked clip frame" />
            {currentObjects.map((o) => {
              const [x1, y1, x2, y2] = o.bbox_norm;
              const color = OBJ_COLORS[(o.object_id || 0) % OBJ_COLORS.length];
              return (
                <div key={o.object_id} className="bbox" style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%`, borderColor: color, background: "rgba(255,255,255,0.08)" }}>
                  <span style={{ background: color }}>{`Object ${o.object_id}`}{o.confidence != null ? ` · ${Math.round(o.confidence * 100)}%` : ""}</span>
                  {o.mask?.svg_path && (
                    <svg className="mask-svg" viewBox={`0 0 ${o.mask.width} ${o.mask.height}`} preserveAspectRatio="none" aria-hidden="true">
                      <path d={o.mask.svg_path} style={{ fill: color, fillOpacity: 0.4, stroke: color }} />
                    </svg>
                  )}
                </div>
              );
            })}
          </>
        )}
        {tap && stage === "live" && <div className="tap-dot" style={{ left: `${tap.nx * 100}%`, top: `${tap.ny * 100}%` }} aria-hidden="true" />}
        {processing && <div className="live-processing"><span className="spinner" aria-hidden="true" /> Processing chunk with SAM 3.1…</div>}
      </div>
      <p className="muted small-text">{stage === "live" ? "Tap the object on the live preview to prompt SAM, or clear the tap and use the concept prompt below." : "Playing the latest tracked clip on loop while the next chunk records. Switch to Live view to re-tap."}</p>

      <label htmlFor="live-prompt">Concept prompt (used when there is no tap)</label>
      <input id="live-prompt" value={promptText} onChange={(e) => { setPromptText(e.target.value); promptedRef.current = false; }} placeholder="e.g. blue adjustment knob" disabled={!!tap} />
      {tap && <p className="muted small-text">Tap prompt active at ({Math.round(tap.nx * 100)}%, {Math.round(tap.ny * 100)}%). Clear the mask to return to the concept prompt.</p>}
      <p className="muted small-text" style={{ marginTop: 10 }}>Or narrate: say <strong>“this is my flag”</strong> and Live will segment the flag automatically.</p>
      <LiveTranscribe compact captureId={captureId ?? null} sharedStream={camStream} autoStart onFinal={() => undefined}
        onSegment={(seg) => {
          const atMs = Math.max(0, performance.now() - liveStartRef.current);
          const inChunk = draftsRef.current.find((d) => atMs >= d.startMs - 250 && atMs <= d.endMs + 500);
          const inHistory = history.find((h) => h.startMs !== undefined && atMs >= (h.startMs || 0) - 250 && atMs <= (h.endMs || 0) + 500);
          const chunkIdx = inChunk?.serverIndex || inHistory?.chunkIndex || Math.floor(atMs / 1000 / (SAM_LIVE.CHUNK_FRAMES / SAM_LIVE.TARGET_FPS)) + 1;
          transcriptSegsRef.current.push({ chunk_index: chunkIdx, start_ms: Math.round(atMs), end_ms: Math.round(atMs) + 1500, text: seg.text });
          void postTranscript();
        }}
        onObjectPhrase={(phrase, timing) => handleSpeechPhrase(phrase, timing)} />

      {heardPhrase && (
        <div className="notice info" role="status">
          Heard <strong>“{heardPhrase}”</strong> → SAM prompt: <strong>{promptText}</strong>{segLog ? <> · {segLog}</> : " · waiting for the next chunk…"}{speechStatus ? <><br />{speechStatus}</> : null}
        </div>
      )}
      {lastStatus === "no_match" && running && (
        <div className="notice warn" role="status">
          <strong>No match in that clip.</strong> The object may be too small, blurry, or named differently by SAM.
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn small" onClick={() => setStage("live")}>Re-tap on live view</button>
            <button className="btn small secondary" onClick={() => { const v = promptVariants(promptText); const simpler = v.find((x) => x !== promptText.trim().toLowerCase()); if (simpler) { setPromptText(simpler); setTap(null); resetRef.current = true; promptedRef.current = false; say(`Retrying with simpler prompt “${simpler}” on the next chunk.`); } }}>Broaden prompt</button>
            <button className="btn small secondary" onClick={clearMask}>Clear and start over</button>
          </div>
        </div>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        {!running
          ? <button className="btn" onClick={() => void startCamera()} disabled={starting}>{starting ? "Starting…" : "Start camera"}</button>
          : <button className="btn danger" onClick={() => stopCamera()}>Stop camera</button>}
        <button className="btn secondary" onClick={() => setPaused((p) => !p)} disabled={!running}>{paused ? "Resume capture" : "Pause capture"}</button>
        <button className="btn secondary" onClick={() => { const nf = facing === "environment" ? "user" : "environment"; setFacing(nf); if (running) void startCamera(nf); }} disabled={starting}>Switch camera</button>
        <button className="btn secondary" onClick={() => setStage((s) => (s === "live" ? "playback" : "live"))} disabled={!running || playback.urls.length === 0}>{stage === "live" ? "Show tracked clip" : "Show live view"}</button>
        <button className="btn secondary" onClick={clearMask} disabled={!running}>Clear mask</button>
      </div>

      {history.length > 0 && sel && (
        <div style={{ marginTop: 18 }}>
          <h3>Replay &amp; verify recording</h3>
          <p className="muted small-text">Saved chunks stay on the server, so you can rewatch, verify, and correct them after stopping — even after a reload.</p>
          <div role="group" aria-label="Recorded chunks">
            <div className="row">
              {history.map((ch, i) => (
                <span key={`${ch.videoUrl}-${ch.chunkIndex}`} className="row" style={{ gap: 4 }}>
                  <input type="checkbox" aria-label={`Select chunk ${ch.chunkIndex} for deletion`} style={{ width: 22, minHeight: 22 }}
                    checked={selectedChunks.has(ch.chunkIndex)}
                    onChange={(e) => setSelectedChunks((s) => { const n = new Set(s); if (e.target.checked) n.add(ch.chunkIndex); else n.delete(ch.chunkIndex); return n; })} />
                  <button className={`btn small ${i === selChunk ? "" : "secondary"}`} aria-pressed={i === selChunk}
                    onClick={() => { setSelChunk(i); setReplayFrame(0); setCorrectionTap(null); if (replayVideoRef.current) replayVideoRef.current.currentTime = 0; }}>
                    Chunk {ch.chunkIndex} · {ch.reviewStatus}
                  </button>
                </span>
              ))}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn small secondary" onClick={() => setSelectedChunks(new Set(history.map((h) => h.chunkIndex)))}>Select all</button>
              <button className="btn small secondary" onClick={() => setSelectedChunks(new Set())} disabled={selectedChunks.size === 0}>Clear selection</button>
              <button className="btn small danger" onClick={() => setConfirmDelete(true)} disabled={selectedChunks.size === 0}>Delete selected ({selectedChunks.size})</button>
              <button className="btn small danger" onClick={() => { setSelectedChunks(new Set([sel.chunkIndex])); setConfirmDelete(true); }}>Delete chunk {sel.chunkIndex}</button>
            </div>
            {confirmDelete && (
              <div className="notice error" role="alert" style={{ marginTop: 8 }}>
                Delete {selectedChunks.size} chunk(s) ({[...selectedChunks].sort((a, b) => a - b).join(", ")})? This removes the video, segmentation, and transcript for those chunks. Surviving chunks keep their original numbers.
                <div className="row" style={{ marginTop: 8 }}>
                  <button className="btn small danger" onClick={() => void deleteChunks([...selectedChunks])}>Confirm delete</button>
                  <button className="btn small secondary" onClick={() => setConfirmDelete(false)}>Cancel</button>
                </div>
              </div>
            )}
          </div>
          <div className="live-stage" style={{ marginTop: 10 }}
            onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setCorrectionTap({ nx: (e.clientX - r.left) / r.width, ny: (e.clientY - r.top) / r.height }); }}>
            <video ref={replayVideoRef} className="live-video" src={sel.videoUrl} controls playsInline
              onTimeUpdate={() => { const v = replayVideoRef.current; if (v) setReplayFrame(Math.min(sel.frameCount - 1, Math.floor(v.currentTime * sel.fps))); }}
              aria-label={`Recorded chunk ${sel.chunkIndex} replay`} />
            {replayObjects.map((o) => {
              const [x1, y1, x2, y2] = o.bbox_norm;
              const color = OBJ_COLORS[(o.object_id || 0) % OBJ_COLORS.length];
              return (
                <div key={o.object_id} className="bbox" style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%`, borderColor: color, background: "rgba(255,255,255,0.08)" }}>
                  <span style={{ background: color }}>{`Object ${o.object_id}`}{o.confidence != null ? ` · ${Math.round(o.confidence * 100)}%` : ""}</span>
                  {o.mask?.svg_path && (
                    <svg className="mask-svg" viewBox={`0 0 ${o.mask.width} ${o.mask.height}`} preserveAspectRatio="none" aria-hidden="true">
                      <path d={o.mask.svg_path} style={{ fill: color, fillOpacity: 0.4, stroke: color }} />
                    </svg>
                  )}
                </div>
              );
            })}
            {correctionTap && <div className="tap-dot" style={{ left: `${correctionTap.nx * 100}%`, top: `${correctionTap.ny * 100}%` }} aria-hidden="true" />}
          </div>
          <p className="muted small-text">Frame {replayFrame + 1}/{sel.frameCount} · prompt: {sel.promptKind || "—"} · showing {showCorrected && sel.correctedByFrame ? "corrected" : "original"} segmentation. Click the replay to set a correction tap point.</p>
          {sel.transcript
            ? <div className="notice info" role="status"><strong>Narration in this chunk:</strong> {sel.transcript}</div>
            : <p className="muted small-text">No narration transcript stored for this chunk yet. Record narration while live and it will appear here.</p>}
          <div className="row">
            <button className="btn small secondary" onClick={() => { const v = replayVideoRef.current; if (v) { v.currentTime = Math.max(0, v.currentTime - 1 / sel.fps); } }}>◀ Frame</button>
            <button className="btn small secondary" onClick={() => { const v = replayVideoRef.current; if (v) { v.currentTime = Math.min(sel.frameCount / sel.fps, v.currentTime + 1 / sel.fps); } }}>Frame ▶</button>
            {sel.correctedByFrame && <button className="btn small secondary" onClick={() => setShowCorrected((s) => !s)}>{showCorrected ? "Show original" : "Show corrected"}</button>}
            <button className="btn small" onClick={() => void reviewSelected("verified")}>Verify chunk</button>
            <button className="btn small secondary" onClick={() => void reviewSelected("needs_correction")}>Needs correction</button>
            <button className="btn small danger" onClick={() => void reviewSelected("incorrect")}>Incorrect</button>
          </div>
          <label htmlFor="correction-prompt">Correction prompt (or tap the replay above)</label>
          <input id="correction-prompt" value={correctionPrompt} onChange={(e) => setCorrectionPrompt(e.target.value)} placeholder={promptText} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn small" onClick={() => void resegmentSelected(false)} disabled={!correctionPrompt.trim()}>Re-segment chunk with prompt</button>
            <button className="btn small secondary" onClick={() => void resegmentSelected(true)} disabled={!correctionTap}>Re-segment at tap point</button>
            <button className="btn small secondary" onClick={() => void saveFrameEvidence()}>Save this frame as photo evidence</button>
          </div>
        </div>
      )}
    </div>
  );
}
