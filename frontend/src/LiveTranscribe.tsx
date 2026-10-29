import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { extractObjectPhrase } from "./speechPrompt";

interface Props {
  captureId: string | null;
  disabled?: boolean;
  compact?: boolean;
  onFinal: (text: string) => void;
  onPartial?: (text: string) => void;
  onObjectPhrase?: (phrase: string, timing: { firstSeenPerf: number; detectedPerf: number }) => void;
  onSegment?: (seg: { text: string; elapsedMs: number }) => void;
  /** Shared mic stream owned by the caller (Live camera). When provided, no second getUserMedia is opened. */
  sharedStream?: MediaStream | null;
  /** When true with sharedStream, transcription starts/stops with the shared stream. */
  autoStart?: boolean;
}

import { wsUrl } from "./api";


/**
 * Live transcription via the backend Muse Voice realtime proxy (PCM over
 * WebSocket), with a stop-and-transcribe MediaRecorder fallback. Shows a
 * recording HUD: pulsing dot, elapsed timer, level meter, live captions.
 */
export default function LiveTranscribe({ captureId, disabled, compact, onFinal, onPartial, onObjectPhrase, onSegment, sharedStream, autoStart }: Props) {
  const [phase, setPhase] = useState<"idle" | "connecting" | "recording" | "stopping">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [partial, setPartial] = useState("");
  const [note, setNote] = useState("");
  const [fallback, setFallback] = useState(false);
  const [debug, setDebug] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedRef = useRef(0);
  const finalsRef = useRef<string[]>([]);
  const lastFinalRef = useRef("");
  const phraseCountRef = useRef<Map<string, number>>(new Map());
  const firedPhraseRef = useRef<string>("");
  const lastPartialPhraseRef = useRef("");
  const partialCountRef = useRef(0);
  const pendingPhraseRef = useRef("");
  const phraseTimerRef = useRef<number | null>(null);
  const pendingSinceRef = useRef(0);
  const finalWaitRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);
  const ownedRef = useRef(false);
  const lastAutoRef = useRef<MediaStream | null>(null);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const gotTranscriptRef = useRef(false);
  const fallbackStartedRef = useRef(false);
  const lastAudibleRef = useRef(0);
  const silentWarnedRef = useRef(false);
  const bytesSentRef = useRef(0);
  const droppedRef = useRef(0);
  const liveDeadRef = useRef(false);
  const modeRef = useRef<"live" | "fallback">("live");
  const lastAudioMsRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
      if (ownedRef.current) streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      void ctxRef.current?.close().catch(() => undefined);
    };
  }, []);

  useEffect(() => {
    if (phase !== "recording" && phase !== "connecting") return;
    let lastBytes = bytesSentRef.current;
    let lastT = Date.now();
    const t = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedRef.current) / 1000));
      const now = Date.now();
      const kbps = ((bytesSentRef.current - lastBytes) / 1024) / Math.max(0.25, (now - lastT) / 1000);
      lastBytes = bytesSentRef.current; lastT = now;
      if (!fallback) setDebug(`PCM ${(kbps).toFixed(0)} KB/s${droppedRef.current ? ` · dropped ${droppedRef.current}` : ""}`);
      if (!fallback && phase === "recording" && !silentWarnedRef.current && startedRef.current && now - startedRef.current > 4000 && now - lastAudibleRef.current > 3000) {
        silentWarnedRef.current = true;
        setNote("No audio is reaching the transcription service. Check the mic is not muted and speak closer to it — or press Stop and type the transcript.");
      }
    }, 250);
    return () => window.clearInterval(t);
  }, [phase, fallback]);

  function firePhrase(phrase: string) {
    if (phrase === firedPhraseRef.current) return;
    firedPhraseRef.current = phrase;
    pendingPhraseRef.current = "";
    if (phraseTimerRef.current) { window.clearTimeout(phraseTimerRef.current); phraseTimerRef.current = null; }
    onObjectPhrase?.(phrase, { firstSeenPerf: pendingSinceRef.current || performance.now(), detectedPerf: performance.now() });
  }

  function detectPhrase(text: string, isFinal: boolean) {
    const phrase = extractObjectPhrase(text);
    if (!phrase || phrase === firedPhraseRef.current) return;
    if (isFinal) { firePhrase(phrase); return; }
    // Fire mid-sentence on stability: same phrase in 2 consecutive partials,
    // or a phrase that stays unchanged for ~800ms (Meta may emit few partials).
    if (phrase === lastPartialPhraseRef.current) {
      partialCountRef.current += 1;
      if (partialCountRef.current >= 2) { firePhrase(phrase); return; }
    } else {
      lastPartialPhraseRef.current = phrase;
      partialCountRef.current = 1;
    }
    if (pendingPhraseRef.current !== phrase) {
      pendingPhraseRef.current = phrase;
      pendingSinceRef.current = performance.now();
      if (phraseTimerRef.current) window.clearTimeout(phraseTimerRef.current);
      phraseTimerRef.current = window.setTimeout(() => {
        if (pendingPhraseRef.current === phrase) firePhrase(phrase);
      }, 800);
    }
  }

  function commitFinal(text: string) {
    const t = text.trim();
    if (!t || t === lastFinalRef.current) return;
    lastFinalRef.current = t;
    finalsRef.current.push(t);
    setPartial("");
    detectPhrase(t, true);
    onFinal(finalsRef.current.join(" "));
    onSegment?.({ text: t, elapsedMs: Math.max(lastAudioMsRef.current, Date.now() - startedRef.current) });
  }

  function cleanupAudio(stopTracks: boolean) {
    if (stopTracks) streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ownedRef.current = false;
    void ctxRef.current?.close().catch(() => undefined);
    ctxRef.current = null;
  }

  /** Shadow MediaRecorder that always runs during live streaming, so a
   *  dead realtime stream can still be recovered via stop-and-transcribe.
   *  Uses an audio-only substream: an audio-mime recorder rejects a stream
   *  that also carries video tracks (Chrome/Android). Never throws — a
   *  backup failure must not kill live transcription. */
  function startShadowRecorder(stream: MediaStream) {
    if (recRef.current && recRef.current.state === "recording") return;
    if (typeof MediaRecorder === "undefined") return;
    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) return;
    try {
      const audioOnly = new MediaStream(audioTracks);
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m));
      const rec = mime ? new MediaRecorder(audioOnly, { mimeType: mime }) : new MediaRecorder(audioOnly);
    chunksRef.current = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
    rec.onstop = async () => {
      cleanupAudio(false); // never stop tracks here; stop() owns track teardown
      if (!mountedRef.current) return;
      setPhase("idle");
      const useBackup = modeRef.current === "fallback" || liveDeadRef.current;
      if (!useBackup) return; // live path succeeded: shadow is discarded
      if (!captureId) { setNote("Recording finished, but there is no capture session to transcribe against. Create the session first next time."); return; }
      const type = rec.mimeType || mime || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      const fd = new FormData();
      fd.append("file", new Blob(chunksRef.current, { type }), `narration.${ext}`);
      setNote("Uploading backup recording for transcription…");
      try {
        const r = await api.upload<{ text: string; simulated: boolean; note: string }>(`/api/capture-sessions/${captureId}/transcribe`, fd);
        if (r.text) { commitFinal(r.text); setNote(r.simulated ? `Simulated transcription: ${r.note}` : "Backup transcription received. Correct any errors before generating the draft."); }
        else setNote(r.note || "Backup transcription returned no text. Type the transcript instead.");
      } catch (e) { setNote(e instanceof Error ? e.message : "Backup transcription failed. Type the transcript instead."); }
    };
    recRef.current = rec;
    try {
      rec.start();
    } catch {
      // Backup unavailable on this device/browser: live transcription continues without it.
      recRef.current = null;
      setDebug((d) => (d ? `${d} · backup rec unavailable` : "backup rec unavailable"));
    }
    } catch {
      // Constructor (mime/stream) rejected: live transcription continues without backup.
      recRef.current = null;
      setDebug((d) => (d ? `${d} · backup rec unavailable` : "backup rec unavailable"));
    }
  }

  async function startFallback(stream: MediaStream, why: string) {
    setFallback(true); modeRef.current = "fallback";
    if (typeof MediaRecorder === "undefined") { setNote("Live transcription and MediaRecorder are both unavailable here. Type the transcript instead."); cleanupAudio(ownedRef.current); setPhase("idle"); return; }
    setNote(`${why} Recording for stop-and-transcribe instead — text arrives when you press Stop.`);
    startShadowRecorder(stream);
    setPhase("recording");
  }

  async function start(providedStream?: MediaStream | null) {
    setNote(""); setPartial(""); setElapsed(0); setFallback(false); setDebug("");
    gotTranscriptRef.current = false; fallbackStartedRef.current = false;
    liveDeadRef.current = false; modeRef.current = "live"; lastAudioMsRef.current = 0; droppedRef.current = 0;
    silentWarnedRef.current = false; lastAudibleRef.current = Date.now(); bytesSentRef.current = 0;
    phraseCountRef.current.clear();
    setPhase("connecting");
    startedRef.current = Date.now();
    let stream: MediaStream;
    if (providedStream) {
      // Shared stream owned by the caller (Live camera): reuse it, never stop its tracks.
      stream = providedStream;
      ownedRef.current = false;
    } else {
      try {
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new DOMException("mediaDevices unavailable", "NotSupportedError");
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        ownedRef.current = true;
      } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      setNote(name === "NotAllowedError" ? "Microphone blocked. Allow mic access in the address-bar site settings, then retry — typing the transcript still works."
        : name === "NotFoundError" ? "No microphone found. Check Windows Settings > Privacy > Microphone, or type the transcript."
        : "Microphone unavailable in this browser/context (needs http://localhost or HTTPS). Type the transcript instead.");
      setPhase("idle");
      return;
      }
    }
    streamRef.current = stream;
    startShadowRecorder(stream);

    // Try the realtime WebSocket path first.
    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AC({ sampleRate: 24000 });
      ctxRef.current = ctx;
      await ctx.audioWorklet.addModule("/pcm-worklet.js");
      const ws = new WebSocket(wsUrl("/api/voice/realtime"));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      const ready = await new Promise<boolean>((resolve) => {
        const to = window.setTimeout(() => resolve(false), 9000);
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(String(ev.data)) as { type?: string };
            if (msg.type === "ready") { window.clearTimeout(to); resolve(true); }
            if (msg.type === "error") { window.clearTimeout(to); resolve(false); }
          } catch { resolve(false); }
        };
        ws.onerror = () => { window.clearTimeout(to); resolve(false); };
        ws.onclose = () => { window.clearTimeout(to); resolve(false); };
      });
      if (!ready || ws.readyState !== WebSocket.OPEN) throw new Error("realtime unavailable");

      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "fieldguard-pcm");
      const mute = ctx.createGain();
      mute.gain.value = 0;
      source.connect(node); node.connect(mute); mute.connect(ctx.destination);
      await ctx.resume();
      const inputRate = ctx.sampleRate;
      setDebug(`Mic ${inputRate} Hz → 24 kHz`);
      // Resample any device rate to 24kHz and pace into 100ms PCM frames (4,800 bytes).
      let pending: number[] = [];
      const inputPerFrame = Math.round(inputRate / 10);
      node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const samples = ev.data;
        let sum = 0;
        for (let i = 0; i < samples.length; i++) { const s = samples[i]; sum += s * s; pending.push(s); }
        const rms = Math.sqrt(sum / Math.max(1, samples.length));
        setLevel(Math.min(1, rms * 3));
        if (rms > 0.01) lastAudibleRef.current = Date.now();
        while (pending.length >= inputPerFrame) {
          const seg = pending.splice(0, inputPerFrame);
          const pcm = new Int16Array(2400);
          for (let i = 0; i < 2400; i++) {
            const pos = (i * inputRate) / 24000;
            const idx = Math.floor(pos);
            const frac = pos - idx;
            const a = seg[Math.min(idx, seg.length - 1)];
            const b = seg[Math.min(idx + 1, seg.length - 1)];
            const s = Math.max(-1, Math.min(1, a + (b - a) * frac));
            pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
          if (ws.readyState === WebSocket.OPEN) {
            if (ws.bufferedAmount > 96000) { droppedRef.current += 1; /* drop instead of building a backlog Meta will reject */ }
            else { ws.send(pcm.buffer); bytesSentRef.current += pcm.byteLength; }
          }
        }
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data)) as { type?: string; transcript?: string; final?: boolean; message?: string };
          if (msg.type === "transcript" && msg.transcript) {
            gotTranscriptRef.current = true;
            if (msg.final) commitFinal(msg.transcript);
            else { setPartial(msg.transcript); onPartial?.(msg.transcript); detectPhrase(msg.transcript, false); }
          } else if (msg.type === "speechComplete" && msg.transcript) {
            gotTranscriptRef.current = true;
            commitFinal(msg.transcript);
          } else if (msg.type === "error") {
            const detail = msg.message ? `Voice service: ${msg.message}` : "Voice service error (no detail returned).";
            liveDeadRef.current = true;
            if (!gotTranscriptRef.current && !fallbackStartedRef.current && streamRef.current) {
              // Provider rejected the live stream before any transcript: the shadow
              // recorder is already running, so Stop will recover the full take.
              fallbackStartedRef.current = true; modeRef.current = "fallback"; setFallback(true);
              setNote(`${detail} Backup recording is running — press Stop for the full transcript.`);
              try { ws.close(); } catch { /* ignore */ }
              void ctx.close().catch(() => undefined);
              ctxRef.current = null;
            } else {
              const backlog = (msg.message || "").toLowerCase().includes("backlog");
              setNote(backlog
                ? "The voice service fell behind while segmentation was running. Backup recording is running — press Stop and the full narration will be transcribed from the backup."
                : `${detail} Backup recording is running — press Stop and the full narration will be transcribed from the backup.`);
            }
          }
          if (typeof (msg as { audioProcessedMs?: number }).audioProcessedMs === "number") lastAudioMsRef.current = (msg as { audioProcessedMs: number }).audioProcessedMs;
          if (msg.type === "transcript" && msg.final) finalWaitRef.current?.();
          if (msg.type === "speechComplete") finalWaitRef.current?.();
        } catch { /* non-JSON keepalive */ }
      };
      ws.onclose = () => { if (mountedRef.current && phase === "recording") setNote("Live transcription connection closed. Press Stop; any final text already shown is kept."); };
      setPhase("recording");
      setNote("Listening… speak now. Captions appear live below.");
    } catch {
      try { wsRef.current?.close(); } catch { /* ignore */ }
      await startFallback(stream, "Live transcription could not connect.");
    }
  }

  async function stop() {
    if (fallback || liveDeadRef.current) {
      // Recover from the shadow backup recording (its onstop uploads it).
      try { wsRef.current?.close(); } catch { /* ignore */ }
      wsRef.current = null;
      if (recRef.current && recRef.current.state === "recording") { recRef.current.stop(); setPhase("stopping"); }
      else { cleanupAudio(ownedRef.current); setPhase("idle"); }
      return;
    }
    setPhase("stopping");
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      const wait = new Promise<void>((resolve) => {
        finalWaitRef.current = resolve;
        window.setTimeout(resolve, 3500);
      });
      try { ws.send(JSON.stringify({ type: "endStream" })); } catch { /* ignore */ }
      await wait;
      finalWaitRef.current = null;
    }
    try { ws?.close(); } catch { /* ignore */ }
    wsRef.current = null;
    if (recRef.current && recRef.current.state === "recording") { try { recRef.current.stop(); } catch { /* ignore */ } } // discard shadow (live succeeded)
    cleanupAudio(ownedRef.current);
    if (mountedRef.current) { setPhase("idle"); setPartial(""); setLevel(0); setNote(finalsRef.current.length ? "Transcription complete. Correct any errors, then generate the draft." : note || "Stopped. No speech was transcribed — speak closer to the mic or type the transcript."); }
  }

  const recording = phase === "recording" || phase === "connecting";
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  // Shared-stream mode (Live camera owns the mic): auto-start when the
  // shared stream arrives, auto-stop when it goes away. A manual stop is
  // respected until a new stream arrives.
  useEffect(() => {
    if (!autoStart) return;
    if (sharedStream && sharedStream !== lastAutoRef.current && phaseRef.current === "idle") {
      lastAutoRef.current = sharedStream;
      void start(sharedStream).catch(() => { /* start() handles its own errors; never reject outward */ });
    } else if (!sharedStream) {
      lastAutoRef.current = null;
      if (phaseRef.current === "recording" || phaseRef.current === "connecting") void stop();
    }
  }, [autoStart, sharedStream]);

  return (
    <div className={compact ? "" : "rec-wrap"}>
      <div className="row">
        {!recording
          ? <button className="btn secondary" onClick={() => void start()} disabled={disabled || phase === "stopping"}>{phase === "stopping" ? "Finishing…" : "Record narration"}</button>
          : <button className="btn danger" onClick={() => void stop()}>Stop recording</button>}
        {phase === "recording" && (
          <span className="rec-hud" role="status" aria-label={`Recording, ${mm} minutes ${ss} seconds`}>
            <span className="rec-dot" aria-hidden="true" /> REC {mm}:{ss}
            <span className="meter" aria-hidden="true"><span style={{ width: `${Math.round(level * 100)}%` }} /></span>
          </span>
        )}
        {phase === "connecting" && <span className="rec-hud"><span className="spinner" aria-hidden="true" /> Connecting mic…</span>}
      </div>
      {partial && <p className="live-caption" aria-live="polite">{partial}</p>}
      {debug && phase === "recording" && <p className="muted small-text">{debug}</p>}
      {note && <p className="muted small-text" role="status">{note}</p>}
    </div>
  );
}
