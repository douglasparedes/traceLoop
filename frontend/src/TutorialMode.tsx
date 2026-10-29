import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders, authPost, getIdentity, getToken } from "./api";
import { listCameras, setPreferredCameraId, getPreferredCameraId, type CameraDevice } from "./camera";
import { STATUS_LABELS, TUTORIAL } from "./museTutorialConfig";

const API = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_URL || "";

interface TutAttempt { prompt: string; status?: string; frames?: number; simulated?: boolean }
interface TutObject {
  obj_id: number; label: string; first_mentioned_at: number; status: string;
  confidence?: number | null; illustration?: string; overlay?: string; note?: string;
  prompt_used?: string; attempts?: TutAttempt[];
  best_frame?: number | null; best_time?: number | null; best_confidence?: number | null;
  best_bbox_norm?: number[] | null; distinct_count?: number | null; margin?: number | null;
  frames_seen?: number; frames_with_match?: number; coverage?: number;
  diagnostic_frame?: string | null;
  track?: { frame: number; objects: { object_id: number; bbox_norm: number[]; confidence?: number | null }[] }[];
}
interface TutStep { step_number: number; title: string; start: number; end: number; summary: string; objects_used: number[] }
interface TutSegment { text: string; start: number; end: number }
interface ProcEvent { id: string; correlation_id: string; stage: string; operation: string; provider: string; model: string; status: string; duration_ms?: number | null; summary: Record<string, unknown>; created_at: string }

interface TutJob {
  id: string; title: string; status: string; progress: number; error?: string;
  duration_sec: number; access_token: string; video_url: string;
  full_transcript: string; timed_segments: TutSegment[]; objects: TutObject[];
  steps: TutStep[]; materials: string[]; guide_markdown: string; cached?: boolean;
  draft_procedure_id?: string | null; draft_version_id?: string | null;
  guide_format?: string; format_source?: string; format_rationale?: string;
}
interface PastItem {
  id: string; title: string; status: string; access_token: string; actor: string;
  duration_sec: number; created_at: string; draft_version_id?: string | null;
  objects_total: number; objects_unresolved: number; has_guide: boolean;
}

import GuideFormatSelector from "./GuideFormatSelector";
import VisualStudio from "./VisualStudio";
import type { GuideSnapshotItem, VisualAsset } from "./guideFormats";
import { acceptVisual, rejectVisual, visualFileUrl } from "./guideFormats";

/** Current format badge + change-format entry point. */
function fmt(sec: number): string {
  const m = Math.floor(sec / 60); const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Current format badge + change-format entry point. */
function GuideFormatBanner({ job, onPick }: {
  job: { guide_format?: string; format_source?: string; format_rationale?: string };
  onPick: () => void;
}) {
  const names: Record<string, string> = {
    work_instruction: "Illustrated Work Instruction",
    reference_manual: "Reference Manual",
    interactive: "Interactive Guided Execution",
  };
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <span className="eyebrow">Guide format</span>
          <h3 style={{ margin: "2px 0" }}>{job.guide_format ? names[job.guide_format] || job.guide_format : "Not set yet"}</h3>
          {job.format_rationale && <p className="muted small-text" style={{ margin: 0 }}>{job.format_source === "user" ? "You selected this format. " : ""}{job.format_rationale}</p>}
        </div>
        <button className="btn small secondary" onClick={onPick}>Change format</button>
      </div>
    </div>
  );
}

function VersionHistory({ snaps, currentMarkdown, compareId, compareMd, onView, onCompare, onCloseCompare, resolveImage }: {
  snaps: GuideSnapshotItem[]; currentMarkdown: string; compareId: string | null; compareMd: string;
  onView: (id: string) => void; onCompare: (id: string | null) => void; onCloseCompare: () => void;
  resolveImage: (src: string) => string;
}) {
  if (!snaps.length) return null;
  const TRIGGER_LABEL: Record<string, string> = { initial: "Initial generation", refresh: "Illustration refresh", tap: "Tap correction", retry: "Retry", format: "Format change" };
  const FMT: Record<string, string> = { work_instruction: "Work instruction", reference_manual: "Reference manual", interactive: "Interactive" };
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <h3 style={{ marginTop: 0 }}>Version history ({snaps.length})</h3>
      <p className="muted small-text">Every generation is kept. New versions never overwrite older ones; drafts only move to Review when you send them.</p>
      {snaps.map((s) => (
        <p key={s.id} className="list-row">
          <span className="tag">{TRIGGER_LABEL[s.trigger] || s.trigger}</span>
          {s.guide_format && <span className="tag ai">{FMT[s.guide_format] || s.guide_format}</span>}
          {s.simulated && <span className="tag warn">simulated model</span>}
          <span className="muted small-text"> · {new Date(s.created_at).toLocaleString()} · {s.markdown_chars} chars</span>{" "}
          <button className="btn small secondary" onClick={() => onView(s.id)}>View</button>{" "}
          <button className="btn small secondary" aria-pressed={compareId === s.id}
            onClick={() => onCompare(compareId === s.id ? null : s.id)}>{compareId === s.id ? "Hide compare" : "Compare"}</button>
        </p>
      ))}
      {compareId && (
        <div style={{ marginTop: 8 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>Comparing with current guide</strong>
            <button className="btn small secondary" onClick={onCloseCompare}>Close compare</button>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <div className="card"><h4>Selected version</h4><Markdown text={compareMd} resolveImage={resolveImage} /></div>
            <div className="card"><h4>Current guide</h4><Markdown text={currentMarkdown} resolveImage={resolveImage} /></div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Compact, honest rendering of one processing event's diagnostic summary. */
function PipelineSummary({ summary }: { summary: Record<string, unknown> }) {
  const s = summary as Record<string, unknown>;
  const bits: string[] = [];
  const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
  if (Array.isArray(s.labels)) bits.push(`objects: ${(s.labels as unknown[]).map(String).join(", ") || "—"}`);
  if (typeof s.label === "string") bits.push(`object: ${s.label}`);
  if (typeof s.prompt_used === "string" && s.prompt_used) bits.push(`prompt: “${s.prompt_used}”`);
  if (Array.isArray(s.attempts)) {
    bits.push(...(s.attempts as { prompt?: string; status?: unknown; frames?: unknown }[]).map((a) => `tried “${a.prompt}” → ${String(a.status)} (${String(a.frames)} frames)`));
  }
  for (const k of ["frames_seen", "frames_with_match", "distinct_count"] as const) {
    if (s[k] != null) bits.push(`${k.replace(/_/g, " ")}: ${String(s[k])}`);
  }
  if (s.coverage != null) bits.push(`coverage: ${Math.round(Number(s.coverage) * 100)}%`);
  if (s.margin != null) bits.push(`margin: ${Math.round(Number(s.margin) * 100)}%`);
  if (s.best_confidence != null) bits.push(`best: ${Math.round(Number(s.best_confidence) * 100)}% @ frame ${String(s.best_frame ?? "?")}`);
  if (s.best_bbox_norm) bits.push(`box: [${(s.best_bbox_norm as number[]).map((v) => Number(v).toFixed(2)).join(", ")}]`);
  if (typeof s.text_chars === "number") bits.push(`transcript: ${s.text_chars} chars, ${String(s.segments)} segments`);
  if (typeof s.markdown_chars === "number") bits.push(`guide: ${s.markdown_chars} chars, ${String(s.materials)} materials`);
  if (typeof s.error === "string" && s.error) bits.push(`error: ${s.error}`);
  if (typeof s.note === "string" && s.note) bits.push(s.note);
  if (!bits.length) return null;
  return <p className="muted small-text" style={{ margin: "2px 0 0" }}>{bits.join(" · ")}</p>;
}

async function getJob(id: string, token: string): Promise<TutJob> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${id}`, { headers: authHeaders({ "X-Tutorial-Token": token }) });
  if (!res.ok) throw new Error(`Status check failed (${res.status})`);
  return res.json() as Promise<TutJob>;
}

/** Very small safe Markdown renderer (headings, lists, bold, paragraphs, images). */
function Markdown({ text, resolveImage }: { text: string; resolveImage?: (src: string) => string }) {
  const blocks: React.ReactNode[] = [];
  const lines = (text || "").split("\n");
  let list: string[] = [];
  const flush = (key: number) => {
    if (list.length) { blocks.push(<ul key={`l${key}`}>{list.map((li, i) => <li key={i}>{inline(li)}</li>)}</ul>); list = []; }
  };
  const inline = (s: string): React.ReactNode => {
    const parts = s.split(/(\*\*[^*]+\*\*|!\[[^\]]*\]\([^)]+\))/g);
    return parts.map((p, i) => {
      if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
      const m = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(p);
      if (m) {
        const src = resolveImage ? resolveImage(m[2]) : m[2];
        return <img key={i} src={src} alt={m[1]} style={{ maxWidth: "100%", borderRadius: 8 }} loading="lazy" />;
      }
      return <span key={i}>{p}</span>;
    });
  };
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (/^<!--.*-->$/.test(line)) return; // injection markers stay out of the render
    if (/^\s*[-*] /.test(line)) { list.push(line.replace(/^\s*[-*] /, "")); return; }
    flush(i);
    if (line.startsWith("### ")) blocks.push(<h4 key={i}>{inline(line.slice(4))}</h4>);
    else if (line.startsWith("## ")) blocks.push(<h3 key={i}>{inline(line.slice(3))}</h3>);
    else if (line.startsWith("# ")) blocks.push(<h2 key={i}>{inline(line.slice(2))}</h2>);
    else if (line.trim()) blocks.push(<p key={i}>{inline(line)}</p>);
  });
  flush(lines.length);
  return <div>{blocks}</div>;
}

export default function TutorialMode({ onUseTranscript, onOpenReview }: { onUseTranscript?: (text: string) => void; onOpenReview?: (versionId: string) => void }) {
  const [phase, setPhase] = useState<"record" | "review" | "processing" | "guide">("record");
  const [uploadFailed, setUploadFailed] = useState(false);
  const [title, setTitle] = useState("How to reseat the trainer cable harness");
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [recorded, setRecorded] = useState<{ blob: Blob; url: string } | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [job, setJob] = useState<TutJob | null>(null);
  const [status, setStatus] = useState("");
  const [tab, setTab] = useState<"guide" | "transcript" | "objects" | "pipeline" | "visuals">("guide");
  const [events, setEvents] = useState<ProcEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [snaps, setSnaps] = useState<GuideSnapshotItem[]>([]);
  const [snapId, setSnapId] = useState<string | null>(null);
  const [snapMd, setSnapMd] = useState("");
  const [compareId, setCompareId] = useState<string | null>(null);
  const [compareMd, setCompareMd] = useState("");
  const [showFormatPicker, setShowFormatPicker] = useState(false);
  const [visuals, setVisuals] = useState<VisualAsset[]>([]);
  const [visualSource, setVisualSource] = useState<{ id: string; label: string; imageUrl: string; kind: string; source: Record<string, unknown> } | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [past, setPast] = useState<PastItem[]>([]);
  const [pastTotal, setPastTotal] = useState(0);
  const [pastQ, setPastQ] = useState("");
  const [pastStatus, setPastStatus] = useState("");
  const [pastShown, setPastShown] = useState(20);
  const [now, setNow] = useState(0);
  const [tapTarget, setTapTarget] = useState<number | null>(null);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [cameraId, setCameraId] = useState<string | null>(() => getPreferredCameraId());

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedRef = useRef(0);
  const xhrRef = useRef<XMLHttpRequest | null>(null);
  const uploadingRef = useRef(false);
  const titleRef = useRef(title);
  titleRef.current = title;
  const uploadRef = useRef<((blob: Blob) => void) | null>(null);

  const loadPast = useCallback(async () => {
    try {
      const idn = getIdentity();
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      if (pastQ.trim()) params.set("q", pastQ.trim());
      if (pastStatus) params.set("status", pastStatus);
      const res = await fetch(`${API}/api/tutorial?${params}`, { headers: authHeaders() });
      if (!res.ok) return;
      const body = await res.json();
      const items: PastItem[] = Array.isArray(body) ? body : body.items || [];
      setPast(items);
      setPastTotal(Array.isArray(body) ? items.length : body.total ?? items.length);
      setPastShown(items.length);
    } catch { /* offline */ }
  }, [pastQ, pastStatus]);
  useEffect(() => { void loadPast(); }, [loadPast]);

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    if (recorded) URL.revokeObjectURL(recorded.url);
  }, [recorded]);

  useEffect(() => {
    if (!recording) return;
    const t = window.setInterval(() => {
      const el = Math.floor((Date.now() - startedRef.current) / 1000);
      setElapsed(el);
      if (el >= TUTORIAL.MAX_VIDEO_SEC) stopRecording();
    }, 250);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording]);

  // Poll job status.
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") {
      if (job?.status === "done") setPhase("guide");
      return;
    }
    const t = window.setInterval(async () => {
      try { setJob(await getJob(job.id, job.access_token)); } catch { /* keep polling */ }
    }, TUTORIAL.POLL_MS);
    return () => window.clearInterval(t);
  }, [job?.id, job?.status, job?.access_token]);

  async function openCamera() {
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new DOMException("mediaDevices unavailable", "NotSupportedError");
      streamRef.current?.getTracks().forEach((t) => t.stop());
      void listCameras().then(setCameras).catch(() => undefined);
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: cameraId ? { deviceId: { exact: cameraId }, width: { ideal: 1280 }, height: { ideal: 720 } }
                            : { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: true,
        });
      } catch (e) {
        if (cameraId && e instanceof DOMException && (e.name === "OverconstrainedError" || e.name === "NotFoundError")) {
          setCameraId(null); setPreferredCameraId(null);
          stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: true,
          });
        } else throw e;
      }
      streamRef.current = stream;
      if (previewRef.current) { previewRef.current.srcObject = stream; await previewRef.current.play().catch(() => undefined); }
      setStatus("");
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      setStatus(name === "NotAllowedError" ? "Camera/microphone blocked. Allow both in the address-bar site settings, then retry."
        : name === "NotFoundError" ? "No camera/microphone found on this device."
        : "Camera unavailable here (needs http://localhost or HTTPS).");
    }
  }

  function startRecording() {
    const stream = streamRef.current;
    if (!stream) { setStatus("Open the camera first."); return; }
    if (typeof MediaRecorder === "undefined") { setStatus("MediaRecorder is not supported in this browser. Use current Chrome/Edge."); return; }
    const mime = ["video/mp4;codecs=avc1,mp4a.40.2", "video/mp4", "video/webm;codecs=vp9,opus", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m));
    const rec = mime ? new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 2_500_000 }) : new MediaRecorder(stream);
    chunksRef.current = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
    rec.onstop = () => {
      const type = rec.mimeType || mime || "video/webm";
      const blob = new Blob(chunksRef.current, { type });
      setRecorded((old) => { if (old) URL.revokeObjectURL(old.url); return { blob, url: URL.createObjectURL(blob) }; });
      setPhase("review");
      uploadRef.current?.(blob);
    };
    recRef.current = rec;
    startedRef.current = Date.now();
    setElapsed(0);
    rec.start(1000);
    setRecording(true);
    setStatus("Recording… narrate each step and show each object. Say “this is my …” as you show it.");
  }

  function stopRecording() {
    if (recRef.current && recRef.current.state === "recording") recRef.current.stop();
    setRecording(false);
  }

  function upload(source?: Blob) {
    const blob = source || recorded?.blob;
    if (!blob || uploadingRef.current) return;
    uploadingRef.current = true;
    setUploadFailed(false);
    setUploadPct(0);
    setStatus("Uploading tutorial video…");
    const idn = getIdentity();
    // Normalize to the base media type: browsers report codec-qualified
    // strings (e.g. "video/webm;codecs=vp8,opus") that servers may reject.
    const mime = (blob.type || "video/webm").split(";")[0].trim().toLowerCase();
    const isMp4 = mime === "video/mp4";
    const fd = new FormData();
    fd.append("file", new File([blob], isMp4 ? "tutorial.mp4" : "tutorial.webm", { type: isMp4 ? "video/mp4" : "video/webm" }));
    fd.append("title", titleRef.current);
    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;
    xhr.open("POST", `${API}/api/tutorial/start`);
    xhr.setRequestHeader("X-User", idn.user);
    xhr.setRequestHeader("X-Role", idn.role);
    const _tok = getToken();
    if (_tok) xhr.setRequestHeader("X-Auth-Token", _tok);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) setUploadPct(Math.round((e.loaded / e.total) * 100)); };
    xhr.onload = () => {
      xhrRef.current = null; uploadingRef.current = false;
      setUploadPct(null);
      try {
        const body = JSON.parse(xhr.responseText) as TutJob & { detail?: string };
        if (xhr.status >= 400) throw new Error(body.detail || `Upload failed (${xhr.status})`);
        setJob(body);
        setPhase(body.status === "done" ? "guide" : "processing");
        setStatus(body.cached ? "This exact video was already processed — opening the existing guide." : "");
        void loadPast();
      } catch (e) { setUploadFailed(true); setPhase("review"); setStatus(e instanceof Error ? e.message : "Upload failed"); }
    };
    xhr.onerror = () => { xhrRef.current = null; uploadingRef.current = false; setUploadPct(null); setUploadFailed(true); setPhase("review"); setStatus("Upload failed — check the connection and retry. Your recording is still here."); };
    xhr.onabort = () => { xhrRef.current = null; uploadingRef.current = false; setUploadPct(null); setPhase("review"); setStatus("Upload cancelled. Your recording is still here — retry when you're ready."); };
    xhr.send(fd);
  }
  uploadRef.current = upload;

  function cancelUpload() {
    xhrRef.current?.abort();
  }

  async function openPast(p: { id: string; access_token: string }) {
    try { const j = await getJob(p.id, p.access_token); setJob(j); setPhase(j.status === "done" ? "guide" : "processing"); }
    catch (e) { setStatus(e instanceof Error ? e.message : "Could not open that tutorial"); }
  }

  const seek = useCallback((t: number) => {
    const v = videoRef.current;
    if (v) { v.currentTime = Math.max(0, t); void v.play().catch(() => undefined); }
  }, []);

  async function tapObject(obj: TutObject, nx: number, ny: number) {
    if (!job) return;
    try {
      setTapTarget(null);
      setStatus(`Re-tracking “${obj.label}” from your tap…`);
      await authPost(`/api/tutorial/${job.id}/objects/${obj.obj_id}/tap`, { nx, ny }, { "X-Tutorial-Token": job.access_token });
      // Processing flips the object to processing/done via status polling on the job.
      const t = window.setInterval(async () => {
        try {
          const j = await getJob(job.id, job.access_token);
          setJob(j);
          const o = j.objects.find((x) => x.obj_id === obj.obj_id);
          if (o && o.status !== "processing") {
            window.clearInterval(t);
            setStatus(o.status === "ok" ? `“${o.label}” corrected from your tap.` : `SAM still could not track “${o.label}” — try tapping its center.`);
            try {
              const r = await authPost<{ guide_markdown: string }>(`/api/tutorial/${job.id}/refresh-guide`, {}, { "X-Tutorial-Token": job.access_token });
              setJob({ ...j, guide_markdown: r.guide_markdown });
            } catch { /* guide keeps its previous illustrations */ }
            void loadPipeline();
          }
        } catch { window.clearInterval(t); }
      }, TUTORIAL.POLL_MS);
    } catch (e) { setStatus(e instanceof Error ? e.message : "Tap correction failed"); }
  }

  async function loadPipeline() {
    if (!job) return;
    try {
      const res = await fetch(`${API}/api/processing/events?entity_type=tutorial&entity_id=${job.id}&limit=200`,
        { headers: authHeaders() });
      if (!res.ok) return;
      const body = await res.json();
      setEvents(body.items || []);
      setEventsTotal(body.total || 0);
    } catch { /* offline */ }
  }

  async function loadSnapshots() {
    if (!job) return;
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${job.id}/snapshots`, { headers: authHeaders({ "X-Tutorial-Token": job.access_token }) });
      if (res.ok) setSnaps((await res.json()).snapshots || []);
    } catch { /* offline */ }
  }

  async function loadVisuals() {
    if (!job) return;
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${job.id}/visuals`, { headers: authHeaders({ "X-Tutorial-Token": job.access_token }) });
      if (res.ok) setVisuals((await res.json()).items || []);
    } catch { /* offline */ }
  }

  async function openCompare(id: string) {
    if (!job) return;
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${job.id}/snapshots/${id}`, { headers: authHeaders({ "X-Tutorial-Token": job.access_token }) });
      if (res.ok) { const s = await res.json(); setCompareId(id); setCompareMd(s.guide_markdown || ""); }
    } catch { setStatus("Could not load that snapshot."); }
  }

  async function openSnapshot(id: string) {
    if (!job) return;
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${job.id}/snapshots/${id}`, { headers: authHeaders({ "X-Tutorial-Token": job.access_token }) });
      if (res.ok) { const s = await res.json(); setSnapId(id); setSnapMd(s.guide_markdown || ""); }
    } catch { setStatus("Could not load that snapshot."); }
  }

  async function downloadDiagnostics() {
    if (!job) return;
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${job.id}/diagnostics`, { headers: authHeaders({ "X-Tutorial-Token": job.access_token }) });
      if (!res.ok) throw new Error(`Diagnostics failed (${res.status})`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `tutorial-${job.id}-diagnostics.json`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) { setStatus(e instanceof Error ? e.message : "Diagnostics download failed"); }
  }

  async function ensureDraft() {
    if (!job || draftBusy) return;
    setDraftBusy(true);
    try {
      const r = await authPost<{ version_id: string; created: boolean }>(`/api/tutorial/${job.id}/draft`, {}, { "X-Tutorial-Token": job.access_token });
      const j = await getJob(job.id, job.access_token);
      setJob(j);
      setStatus(r.created ? "Review draft created — find it in the Review queue." : "Review draft already exists for this tutorial.");
    } catch (e) { setStatus(e instanceof Error ? e.message : "Draft creation failed — retry when connected."); }
    finally { setDraftBusy(false); }
  }

  const activeSeg = job?.timed_segments.find((s) => now >= s.start && now < s.end);
  const frameNow = Math.floor(now * TUTORIAL.TRACKING_FPS);
  const imgUrl = (name?: string) => (job && name ? `${API}/api/tutorial/${job.id}/illustrations/${name}?token=${encodeURIComponent(job.access_token)}` : "");
  const resolveMdImage = (src: string) => {
    const m = /^illustrations\/(.+)$/.exec(src);
    return m ? imgUrl(m[1]) || src : src;
  };

  return (
    <div>
      {phase === "record" && (
        <div>
          <p className="muted">Record a 2–10 minute tutorial. Audio is transcribed by Muse Voice, objects are segmented by SAM 3.1, and the guide is written by Muse Spark — all processing happens on the server after upload.</p>
          <label htmlFor="tut-title">Tutorial title</label>
          <input id="tut-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="live-stage" style={{ marginTop: 10 }}>
            <video ref={previewRef} className="live-video" autoPlay playsInline muted aria-label="Tutorial camera preview" />
            {recording && <div className="live-processing"><span className="rec-dot" aria-hidden="true" /> REC {fmt(elapsed)} / {fmt(TUTORIAL.MAX_VIDEO_SEC)}</div>}
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn secondary" onClick={() => void openCamera()}>Open camera</button>
            <label className="btn secondary" style={{ margin: 0 }} aria-label="Choose camera">Camera
              <select value={cameraId || ""} aria-label="Choose camera" onChange={(e) => { const id = e.target.value || null; setCameraId(id); setPreferredCameraId(id); }} style={{ width: "auto", minHeight: 0, border: 0, background: "transparent", marginLeft: 6, font: "inherit", color: "inherit" }}>
                <option value="">Auto</option>
                {cameras.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
            {!recording
              ? <button className="btn" onClick={startRecording}>Start recording</button>
              : <button className="btn danger" onClick={stopRecording}>Stop recording</button>}
          </div>
          {past.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <h3>Tutorial library {pastTotal > 0 && <span className="muted">({pastTotal})</span>}</h3>
              <div className="row">
                <input value={pastQ} onChange={(e) => setPastQ(e.target.value)} placeholder="Search tutorials…" aria-label="Search tutorials" style={{ flex: "2 1 160px" }} />
                <select value={pastStatus} onChange={(e) => setPastStatus(e.target.value)} aria-label="Filter by status" style={{ flex: "1 1 140px" }}>
                  <option value="">All statuses</option>
                  <option value="done">Done</option>
                  <option value="error">Error</option>
                  <option value="uploaded">Uploaded</option>
                  <option value="transcribing">Transcribing</option>
                  <option value="understanding">Understanding</option>
                  <option value="segmenting">Segmenting</option>
                  <option value="generating">Generating</option>
                  <option value="archived">Archived</option>
                </select>
              </div>
              {past.slice(0, pastShown).map((p) => (
                <p key={p.id} className="list-row">
                  <strong>{p.title}</strong> <span className={`tag ${p.status === "done" ? "approved" : p.status === "error" ? "error" : ""}`}>{p.status}</span>{" "}
                  {p.objects_unresolved > 0 && <span className="tag warn">{p.objects_unresolved} need{(p.objects_unresolved === 1 ? "s" : "")} tap</span>}{" "}
                  {p.draft_version_id && <span className="tag ai">draft linked</span>}{" "}
                  <span className="muted small-text">{p.created_at ? new Date(p.created_at).toLocaleDateString() : ""}</span>{" "}
                  <button className="btn small secondary" onClick={() => void openPast(p)}>Open</button></p>
              ))}
              {pastShown < past.length && <button className="btn small secondary" onClick={() => setPastShown((n) => n + 20)}>Show more ({past.length - pastShown} remaining)</button>}
            </div>
          )}
        </div>
      )}

      {phase === "review" && recorded && (
        <div>
          <h3>{uploadPct !== null ? "Uploading your tutorial…" : uploadFailed ? "Upload didn't finish" : "Review your recording"}</h3>
          <video className="live-video" src={recorded.url} controls playsInline aria-label="Recorded tutorial preview" />
          <p className="muted">{(recorded.blob.size / 1024 / 1024).toFixed(1)} MB · {fmt(elapsed)} recorded. Processing a 3-minute tutorial typically takes 1–3 minutes.</p>
          <label htmlFor="tut-title2">Tutorial title</label>
          <input id="tut-title2" value={title} onChange={(e) => setTitle(e.target.value)} disabled={uploadPct !== null} />
          <div className="row" style={{ marginTop: 10 }}>
            {uploadPct !== null
              ? <button className="btn danger" onClick={cancelUpload}>Cancel upload</button>
              : <button className="btn" onClick={() => upload()}>{uploadFailed ? "Retry upload & generate guide" : "Upload & generate guide"}</button>}
            <button className="btn secondary" onClick={() => setPhase("record")} disabled={uploadPct !== null}>Record again</button>
          </div>
          {uploadPct !== null && <div className="progress" role="progressbar" aria-valuenow={uploadPct} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress"><div style={{ width: `${uploadPct}%` }} /></div>}
        </div>
      )}

      {phase === "processing" && job && (
        <div>
          <h3>Building your guide…</h3>
          <p role="status">{STATUS_LABELS[job.status] || job.status}</p>
          <div className="progress" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${job.progress}%` }} /></div>
          <p className="muted">{job.progress}% — you can leave this screen; the tutorial keeps processing on the server and appears in the tutorial library.</p>
        </div>
      )}

      {job?.status === "error" && (() => {
        const noAudio = /no audio track/i.test(job.error || "");
        return (
          <div className="notice error" role="alert">
            <strong>Processing failed.</strong> {job.error}
            {noAudio && (
              <p className="muted small-text" style={{ margin: "6px 0 0" }}>
                This recording captured video but no sound — check the microphone is on and not muted at the OS/browser level, then record again while narrating each step out loud. Retrying this file cannot work: it contains no audio to transcribe.
              </p>
            )}
            <div className="row" style={{ marginTop: 8 }}>
              {!noAudio && (
                <button className="btn small" onClick={async () => { await authPost(`/api/tutorial/${job.id}/retry`, {}, { "X-Tutorial-Token": job.access_token }); setJob({ ...job, status: "uploaded", progress: 2, error: "" }); setPhase("processing"); }}>Retry processing</button>
              )}
              <button className="btn small secondary" onClick={() => setPhase("record")}>{noAudio ? "Record again with microphone" : "Record again"}</button>
            </div>
          </div>
        );
      })()}

      {phase === "guide" && job && job.status === "done" && (
        <div>
          <h3>{job.title}</h3>
          <div className="live-stage"
            onClick={(e) => {
              if (tapTarget === null) return;
              const target = job.objects.find((o) => o.obj_id === tapTarget);
              if (!target) return;
              const r = e.currentTarget.getBoundingClientRect();
              void tapObject(target, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
            }}>
            <video ref={videoRef} className="live-video" src={`${API}${job.video_url}?token=${encodeURIComponent(job.access_token)}`} controls playsInline
              onTimeUpdate={() => setNow(videoRef.current?.currentTime || 0)} aria-label="Tutorial video" />
            {job.objects.map((o) => {
              const fr = o.track?.find((f) => f.frame === frameNow);
              const rec = fr?.objects?.[0];
              if (!rec) return null;
              const [x1, y1, x2, y2] = rec.bbox_norm;
              return (
                <div key={o.obj_id} className="bbox" style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}>
                  <span>{o.label}</span>
                  {o.illustration && null}
                </div>
              );
            })}
          </div>
          {tapTarget !== null && <p className="notice warn" role="status">Tap the object you meant on the video above to re-track it.</p>}
          <div className="row" role="group" aria-label="Guide sections" style={{ margin: "10px 0" }}>
            {(["guide", "transcript", "objects", "pipeline", "visuals"] as const).map((t) => (
              <button key={t} className={`btn small ${tab === t ? "" : "secondary"}`} aria-pressed={tab === t} onClick={() => { setTab(t); if (t === "pipeline") void loadPipeline(); if (t === "guide") void loadSnapshots(); if (t === "visuals") void loadVisuals(); }}>
                {t === "guide" ? "Guide" : t === "transcript" ? "Transcript" : t === "objects" ? `Objects (${job.objects.length})` : t === "pipeline" ? "Pipeline" : "Visuals"}
              </button>
            ))}
            <button className="btn small secondary" onClick={async () => { try { await navigator.clipboard.writeText(job.guide_markdown); setStatus("Guide Markdown copied."); } catch { setStatus("Copy failed in this browser — use Download .md."); } }}>Copy Markdown</button>
            <button className="btn small secondary" onClick={() => {
              const a = document.createElement("a");
              a.href = URL.createObjectURL(new Blob([job.guide_markdown], { type: "text/markdown" }));
              a.download = `${job.title.replace(/[^\w\- ]+/g, "").trim() || "tutorial-guide"}.md`;
              a.click(); URL.revokeObjectURL(a.href);
            }}>Download .md</button>
            <button className="btn small secondary" onClick={() => {
              const a = document.createElement("a");
              a.href = `${API}/api/tutorial/${job.id}/bundle.zip?token=${encodeURIComponent(job.access_token)}`;
              a.download = "";
              document.body.appendChild(a); a.click(); a.remove();
            }}>Download .zip (guide + images)</button>
            <button className="btn small secondary" onClick={() => window.print()}>Print / PDF</button>
            <button className="btn small danger" onClick={async () => {
              if (!window.confirm("Delete this tutorial and all its videos and illustrations? This cannot be undone.")) return;
              try {
                const idn = getIdentity();
                const res = await fetch(`${API}/api/tutorial/${job.id}`, { method: "DELETE", headers: authHeaders({ "X-Tutorial-Token": job.access_token }) });
                if (!res.ok) throw new Error(`Delete failed (${res.status})`);
                setJob(null); setPhase("record"); setStatus("Tutorial deleted.");
                void loadPast();
              } catch (e) { setStatus(e instanceof Error ? e.message : "Delete failed"); }
            }}>Delete tutorial</button>
          </div>

          {tab === "guide" && (
            <div>
              <GuideFormatBanner job={job} onPick={() => setShowFormatPicker(true)} />
              {showFormatPicker && (
                <GuideFormatSelector tutorialId={job.id} token={job.access_token} current={job.guide_format || ""}
                  onGenerated={(sid) => { setShowFormatPicker(false); void openSnapshot(sid); void loadSnapshots(); void (async () => { try { const j = await getJob(job.id, job.access_token); setJob(j); } catch { /* keep current */ } })(); }}
                  onChanged={() => { void loadPast(); }} />
              )}
              <VersionHistory snaps={snaps} currentMarkdown={job.guide_markdown} compareId={compareId} compareMd={compareMd}
                resolveImage={resolveMdImage}
                onView={(id) => void openSnapshot(id)} onCompare={(id: string | null) => { if (id) void openCompare(id); else { setCompareId(null); setCompareMd(""); } }} onCloseCompare={() => { setCompareId(null); setCompareMd(""); }} />
              {job.guide_format === "interactive" && (
                <div className="notice info" role="status" style={{ marginBottom: 10 }}>
                  This guide is presented for <strong>interactive guided execution</strong> — one step at a time with recorded outcomes.
                  {job.draft_version_id && onOpenReview
                    ? <div className="row" style={{ marginTop: 8 }}><button className="btn small" onClick={() => onOpenReview(job.draft_version_id!)}>Review &amp; approve for guided execution</button></div>
                    : <span> Approve its Review draft first — jobs always run the exact approved revision.</span>}
                </div>
              )}
              {job.draft_version_id ? (
                <div className="notice ok" role="status">
                  This tutorial created Review draft v{job.draft_version_id.slice(0, 8)} — it persists in the Review queue even if the tutorial is deleted.
                  {onOpenReview && <div className="row" style={{ marginTop: 8 }}><button className="btn small" onClick={() => onOpenReview(job.draft_version_id!)}>Open in Review</button></div>}
                </div>
              ) : (
                <div className="notice warn" role="status">
                  No Review draft linked yet. Completed tutorials auto-create one; if this one finished before that feature, create it now.
                  <div className="row" style={{ marginTop: 8 }}><button className="btn small" onClick={() => void ensureDraft()} disabled={draftBusy}>{draftBusy ? "Creating…" : "Send to Review as draft"}</button></div>
                </div>
              )}
              {job.steps.map((s) => {
                const objs = (s.objects_used || []).map((id) => job.objects.find((o) => o.obj_id === id)).filter((o): o is TutObject => !!o?.overlay);
                return (
                  <div key={s.step_number} className="card">
                    <div className="row" style={{ alignItems: "flex-start" }}>
                      {objs.map((obj) => <img key={obj.obj_id} src={imgUrl(obj.overlay)} alt={`${obj.label} illustration`} style={{ width: 140, borderRadius: 8 }} />)}
                      <div>
                        <h4 style={{ margin: "0 0 6px" }}>{s.step_number}. {s.title}</h4>
                        <p>{s.summary}</p>
                        <button className="btn small secondary" onClick={() => seek(s.start)}>▶ {fmt(s.start)}–{fmt(s.end)}</button>
                      </div>
                    </div>
                  </div>
                );
              })}
              <div className="card"><Markdown text={job.guide_markdown} resolveImage={resolveMdImage} /></div>
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn small secondary" onClick={async () => {
                  try {
                    const r = await authPost<{ guide_markdown: string }>(`/api/tutorial/${job.id}/refresh-guide`, {}, { "X-Tutorial-Token": job.access_token });
                    setJob({ ...job, guide_markdown: r.guide_markdown });
                    setStatus("Guide illustrations refreshed from the current segmentation.");
                  } catch (e) { setStatus(e instanceof Error ? e.message : "Refresh failed"); }
                }}>Refresh guide illustrations</button>
              </div>
            </div>
          )}

          {tab === "transcript" && (
            <div className="card">
              <h3>Transcript (Muse Voice, turn timestamps)</h3>
              {job.timed_segments.length === 0 && <p className="muted">No timed segments were returned for this tutorial.</p>}
              {job.timed_segments.map((s, i) => (
                <p key={i} className="list-row" style={activeSeg === s ? { background: "var(--ok-bg)", borderRadius: 8, padding: 8 } : undefined}>
                  <button className="btn small secondary" onClick={() => seek(s.start)}>{fmt(s.start)}</button> {s.text}
                </p>
              ))}
              <button className="btn secondary" style={{ marginTop: 10 }} onClick={() => onUseTranscript?.(job.full_transcript)}>Use as capture transcript</button>
            </div>
          )}

          {tab === "objects" && (
            <div>
              {job.objects.length === 0 && <div className="empty">No objects were detected in the narration. Mention each object as you show it (“this is my …”).</div>}
              {job.objects.map((o) => (
                <div key={o.obj_id} className="card">
                  <div className="row" style={{ alignItems: "flex-start" }}>
                    {o.overlay && <img src={imgUrl(o.overlay)} alt={`${o.label} with segmentation overlay`} style={{ width: 160, borderRadius: 8 }} />}
                    {o.illustration && <img src={imgUrl(o.illustration)} alt={`${o.label} isolated`} style={{ width: 160, borderRadius: 8, background: "repeating-conic-gradient(#ddd 0 25%, #fff 0 50%) 0 0/16px 16px" }} />}
                    {!o.overlay && !o.illustration && o.diagnostic_frame && (
                      <img src={`${API}/api/tutorial/${job.id}/diagnostics/frame/${o.obj_id}?token=${encodeURIComponent(job.access_token)}`} alt={`Frame where “${o.label}” was first mentioned`} style={{ width: 160, borderRadius: 8 }} loading="lazy" />
                    )}
                    <div>
                      <h4 style={{ margin: "0 0 6px" }}>{o.label}</h4>
                      <p>
                        <span className={`tag ${o.status === "ok" ? "approved" : o.status === "needs_tap" ? "warn" : ""}`}>{o.status}</span>
                        {o.confidence != null && <span className="tag">{Math.round(o.confidence * 100)}% confidence</span>}
                        {o.prompt_used && <span className="tag">prompt: {o.prompt_used}</span>}
                        <button className="btn small secondary" onClick={() => seek(o.first_mentioned_at)}>First shown {fmt(o.first_mentioned_at)}</button>
                      </p>
                      {o.note && <p className="muted">{o.note}</p>}
                      {(o.best_frame != null || o.distinct_count != null || o.coverage != null) && (
                        <p className="muted small-text">
                          {o.best_frame != null && <>Best frame {o.best_frame}{o.best_time != null ? ` (${fmt(o.best_time)})` : ""} · </>}
                          {o.distinct_count != null && <>{o.distinct_count} candidate{o.distinct_count === 1 ? "" : "s"} on that frame{o.margin != null ? ` · margin ${Math.round(o.margin * 100)}%` : ""} · </>}
                          {o.coverage != null && <>track coverage {Math.round(o.coverage * 100)}%</>}
                        </p>
                      )}
                      {o.attempts && o.attempts.length > 0 && (
                        <p className="muted small-text">Tried: {o.attempts.map((a) => `“${a.prompt}” (${a.frames} frames${a.simulated ? ", simulated" : ""})`).join(" → ")}</p>
                      )}
                      {o.status === "needs_tap" && <button className="btn small" onClick={() => { seek(o.first_mentioned_at); setTapTarget(o.obj_id); }}>Tap which one you meant</button>}
                      {o.status === "processing" && <p role="status"><span className="spinner" aria-hidden="true" /> Re-tracking from your tap…</p>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "pipeline" && (
            <div>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h3 style={{ margin: 0 }}>Processing timeline {eventsTotal > 0 && <span className="muted">({eventsTotal})</span>}</h3>
                <button className="btn small secondary" onClick={() => void downloadDiagnostics()}>Download diagnostics (.json)</button>
              </div>
              <p className="muted small-text">Every AI/model stage is logged with its inputs, outputs and timing — this is what lets us explain a SAM miss instead of guessing.</p>
              {events.length === 0 && <div className="empty">No processing events recorded for this tutorial yet. Events appear as each stage runs.</div>}
              {events.map((e) => (
                <div key={e.id} className="list-row">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <strong>{e.stage}</strong>
                    <span className={`tag ${e.status === "succeeded" || e.status === "ok" ? "approved" : e.status === "failed" || e.status === "error" ? "error" : e.status === "no_match" || e.status === "needs_tap" ? "warn" : ""}`}>{e.status}</span>
                  </div>
                  <p className="muted small-text" style={{ margin: "4px 0" }}>
                    {e.operation}{e.model ? ` · ${e.model}` : ""}{e.duration_ms != null ? ` · ${e.duration_ms} ms` : ""} · {new Date(e.created_at).toLocaleTimeString()}
                    {e.correlation_id && <> · run <code>{e.correlation_id}</code></>}
                  </p>
                  <PipelineSummary summary={e.summary} />
                </div>
              ))}
              <h3 style={{ marginTop: 14 }}>Guide snapshots ({snaps.length})</h3>
              <p className="muted small-text">Every generated guide is kept, including refreshes — the live guide never overwrites history.</p>
              {snaps.length === 0 && <p className="muted">No snapshots yet — open the Guide tab to load them.</p>}
              {snaps.map((s) => (
                <p key={s.id} className="list-row">
                  <span className="tag">{s.trigger}</span> {new Date(s.created_at).toLocaleString()} · {s.markdown_chars} chars{s.simulated ? " · simulated" : ""}
                  {" "}<button className="btn small secondary" onClick={() => void openSnapshot(s.id)}>{snapId === s.id ? "Hide" : "View"}</button>
                </p>
              ))}
              {snapId && (
                <div className="card"><h4>Snapshot {snapId.slice(0, 8)}…</h4><Markdown text={snapMd} resolveImage={resolveMdImage} /></div>
              )}
            </div>
          )}

          {tab === "visuals" && job && (
            <div>
              <div className="card">
                <h3 style={{ marginTop: 0 }}>Visual sources</h3>
                <p className="muted small-text">Pick any source image to work on. Object overlays come from SAM segmentation; accepted visuals can be reused as sources. Nothing here overwrites the originals.</p>
                {job.objects.filter((o) => o.overlay || o.illustration).map((o) => (
                  <div key={o.obj_id} className="row" style={{ marginBottom: 6 }}>
                    {o.overlay && <img src={imgUrl(o.overlay)} alt={`${o.label} overlay`} style={{ width: 72, borderRadius: 8 }} />}
                    <div style={{ flex: "1 1 auto" }}>
                      <strong>{o.label}</strong> <span className={`tag ${o.status === "ok" ? "approved" : o.status === "needs_tap" ? "warn" : ""}`}>{o.status}</span>
                    </div>
                    {o.overlay && <button className="btn small secondary" aria-pressed={visualSource?.id === `obj-${o.obj_id}-overlay`} onClick={() => setVisualSource({ id: `obj-${o.obj_id}-overlay`, label: `${o.label} overlay`, imageUrl: imgUrl(o.overlay), kind: "segmentation", source: { kind: "illustration", name: o.overlay } })}>Use overlay</button>}
                    {o.illustration && <button className="btn small secondary" aria-pressed={visualSource?.id === `obj-${o.obj_id}-cutout`} onClick={() => setVisualSource({ id: `obj-${o.obj_id}-cutout`, label: `${o.label} cutout`, imageUrl: imgUrl(o.illustration), kind: "segmentation", source: { kind: "illustration", name: o.illustration } })}>Use cutout</button>}
                  </div>
                ))}
                {job.objects.every((o) => !o.overlay && !o.illustration) && <p className="muted">No segmented illustrations yet — they appear after processing finds objects.</p>}
              </div>
              <VisualStudio tutorialId={job.id} token={job.access_token} sourceAsset={visualSource}
                references={visuals.map((v) => ({ id: v.id, label: (v.instruction || v.kind).slice(0, 80) }))}
                onChanged={() => void loadVisuals()} />
              <div className="card">
                <h3 style={{ marginTop: 0 }}>Visual assets ({visuals.length})</h3>
                <p className="muted small-text">Every improve / alternative / annotation is a separate asset with provenance. Only accepted assets can attach to guide steps.</p>
                {visuals.length === 0 && <p className="muted">No visual assets yet — select a source above and create one.</p>}
                {visuals.map((a) => (
                  <div key={a.id} className="card" style={{ marginBottom: 8 }}>
                    <div className="row" style={{ alignItems: "flex-start" }}>
                      {a.mime_type === "image/svg+xml"
                        ? <div className="overlay-wrap" style={{ width: 120 }}><img src={visualFileUrl(a, job.access_token)} alt={a.instruction || "Annotation overlay"} style={{ width: "100%", borderRadius: 8 }} /></div>
                        : <img src={a.image_url ? visualFileUrl(a, job.access_token) : ""} alt={a.instruction || a.kind} style={{ width: 120, borderRadius: 8 }} />}
                      <div style={{ flex: "1 1 auto" }}>
                        <span className={`tag ${a.kind === "illustrative_alternative" ? "warn" : a.kind === "annotation" ? "ai" : ""}`}>{a.kind.replace(/_/g, " ")}</span>{" "}
                        <span className={`tag ${a.status === "accepted" ? "approved" : ""}`}>{a.status}</span>
                        {a.model && <span className="muted small-text"> · {a.model}</span>}
                        {a.instruction && <p className="small-text" style={{ margin: "4px 0" }}>{a.instruction}</p>}
                        {typeof (a.provenance as { warning?: unknown }).warning === "string" && <p className="muted small-text" style={{ margin: 0 }}>{String((a.provenance as { warning?: unknown }).warning)}</p>}
                        <div className="row" style={{ marginTop: 6 }}>
                          <button className="btn small secondary" aria-pressed={visualSource?.id === a.id} onClick={() => a.image_url && setVisualSource({ id: a.id, label: a.instruction || a.kind, imageUrl: visualFileUrl(a, job.access_token), kind: a.kind, source: { kind: "asset", id: a.id } })}>Use as source</button>
                          <button className="btn small" disabled={a.status === "accepted"} onClick={async () => { try { await acceptVisual(a.id, {}); setVisualSource((s) => s); void loadVisuals(); } catch (e) { setStatus(e instanceof Error ? e.message : "Accept failed"); } }}>{a.status === "accepted" ? "Accepted" : "Accept"}</button>
                          <button className="btn small secondary" disabled={a.status !== "review"} onClick={async () => { try { await rejectVisual(a.id); void loadVisuals(); } catch (e) { setStatus(e instanceof Error ? e.message : "Reject failed"); } }}>Reject</button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {status && <div className="notice warn" role="status" style={{ marginTop: 10 }}>{status}</div>}
    </div>
  );
}
