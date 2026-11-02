// Optional upload of an existing tutorial video. Same endpoint, same
// pipeline, same TutorialJob as a fresh recording — recording stays fully
// functional. The file is queued in IndexedDB first, so an interrupted
// upload can be retried without re-selecting it.
import { useEffect, useRef, useState } from "react";
import { API, authHeaders, getIdentity } from "./api";
import { Icon } from "./icons";
import {
  ANALYSIS_MODES, validateTutorialFile, checkStorageFor, queueTutorialUpload,
  runQueuedUpload, listQueuedUploads, removeQueuedUpload, parseUploadResponse,
  type AnalysisMode, type QueuedTutorialUpload,
} from "./uploadQueue";
import type { LibraryItem } from "./TutorialLibrary";

const POLL_MS = 3000;

function fmtSize(bytes: number): string {
  if (bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ModeSelector({ mode, onModeChange }: { mode: AnalysisMode; onModeChange: (m: AnalysisMode) => void }) {
  return (
    <div>
      <div className="row" role="group" aria-label="Analysis mode" style={{ marginBottom: 4 }}>
        {ANALYSIS_MODES.map((m) => (
          <button key={m.id} className={`btn small ${mode === m.id ? "" : "secondary"}`} aria-pressed={mode === m.id}
            onClick={() => onModeChange(m.id)} title={m.blurb}>{m.label}</button>
        ))}
      </div>
      <p className="muted small-text" style={{ marginTop: 0 }}>
        {ANALYSIS_MODES.find((m) => m.id === mode)?.blurb} Files stay on this device until the server confirms the upload.
      </p>
    </div>
  );
}

export default function TutorialUpload({ mode, onModeChange, onOpenStudio, onUploaded }: {
  mode: AnalysisMode;
  onModeChange: (m: AnalysisMode) => void;
  onOpenStudio: (t: LibraryItem) => void;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [equipment, setEquipment] = useState("");
  const [task, setTask] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [pct, setPct] = useState<number | null>(null);
  const [job, setJob] = useState<{ id: string; access_token: string; title: string; status: string; progress: number; error?: string } | null>(null);
  const [queuedKey, setQueuedKey] = useState<string | null>(null);
  const cancelRef = useRef({ cancelled: false });
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const t = window.setInterval(async () => {
      try {
        const idn = getIdentity();
        const res = await fetch(`${API}/api/tutorial/${job.id}`, {
          headers: authHeaders({ "X-Tutorial-Token": job.access_token, "X-User": idn.user, "X-Role": idn.role }),
        });
        const text = await res.text();
        setJob(parseUploadResponse(res.status, text, res.headers.get("content-type")) as unknown as typeof job);
      } catch (e) {
        // Keep polling through transient failures; surface only a real error state.
        if (e instanceof Error && /wrong address|proxy|sign-in/i.test(e.message)) setError(e.message);
      }
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [job?.id, job?.status, job?.access_token]);

  function pick(f: File | undefined) {
    if (!f) return;
    const problem = validateTutorialFile(f);
    if (problem) { setError(problem); return; }
    setError("");
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(f));
    setFile(f);
    if (!title.trim()) {
      setTitle(f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || "Untitled tutorial");
    }
    setJob(null);
    setUploadFailed(false);
  }

  const [uploadFailed, setUploadFailed] = useState(false);

  async function start() {
    if (!file || uploading) return;
    if (!title.trim()) { setError("Give the tutorial a title first."); return; }
    setError("");
    setUploadFailed(false);
    cancelRef.current = { cancelled: false };
    const store = await checkStorageFor(file.size);
    if (!store.ok) { setError(store.message); return; }
    setUploading(true);
    setPct(0);
    try {
      // Queue first: the blob survives reloads until the server confirms.
      const entry = await queueTutorialUpload({
        blob: file, filename: file.name, title: title.trim(),
        equipment, task, notes, mode, origin: "uploaded",
      });
      setQueuedKey(entry.key);
      const j = await runQueuedUpload(entry, setPct, cancelRef.current);
      setPct(null);
      setJob({ id: j.id, access_token: j.access_token, title: j.title, status: j.status, progress: j.progress, error: j.error });
      onUploaded();
    } catch (e) {
      setUploadFailed(true);
      setPct(null);
      setError(e instanceof Error ? e.message : "Upload failed — your file is still queued on this device.");
    } finally {
      setUploading(false);
    }
  }

  function retry() {
    if (!file || uploading) return;
    cancelRef.current = { cancelled: false };
    void start();
  }

  return (
    <div>
      <ModeSelector mode={mode} onModeChange={onModeChange} />
      <label className="btn secondary" style={{ marginBottom: 8 }}>
        Choose video file (MP4, WebM, MOV, MKV · max 300 MB)
        <input ref={fileRef} className="visually-hidden" type="file" accept=".mp4,.webm,.mov,.mkv,video/mp4,video/webm,video/quicktime,video/x-matroska"
          aria-label="Choose an existing tutorial video" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {error && <div className="notice error" role="alert">{error}</div>}
      {file && (
        <div className="card" style={{ marginTop: 8 }}>
          <strong>{file.name}</strong> <span className="muted small-text num">{fmtSize(file.size)} · {file.type || "unknown type"}</span>
          {previewUrl && <video className="live-video" src={previewUrl} controls playsInline preload="metadata" aria-label="Selected tutorial video preview" style={{ marginTop: 8 }} />}
          <label htmlFor="up-title">Tutorial title<input id="up-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Reseat the pump seal" maxLength={200} disabled={uploading} /></label>
          <label htmlFor="up-equip">Equipment or asset (optional)<input id="up-equip" value={equipment} onChange={(e) => setEquipment(e.target.value)} placeholder="e.g. Pump P-104" maxLength={200} disabled={uploading} /></label>
          <label htmlFor="up-task">Task description (optional)<textarea id="up-task" rows={2} value={task} onChange={(e) => setTask(e.target.value)} placeholder="What does this tutorial teach?" maxLength={4000} disabled={uploading} /></label>
          <label htmlFor="up-notes">Context notes (optional)<textarea id="up-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Shift, site, or variant notes for reviewers." maxLength={8000} disabled={uploading} /></label>
          {error && <div className="notice error" role="alert">{error}</div>}
          <div className="row" style={{ marginTop: 10 }}>
            {pct !== null
              ? <button className="btn danger" onClick={() => { cancelRef.current.cancelled = true; }}>Cancel upload</button>
              : <button className="btn" onClick={() => void (uploadFailed ? retry() : start())} disabled={uploading || !file}>
                {uploading ? "Uploading…" : uploadFailed ? "Retry upload & generate guide" : "Upload & generate guide"}
              </button>}
            <button className="btn secondary" onClick={() => { setFile(null); setJob(null); setUploadFailed(false); setError(""); }} disabled={uploading}>Clear file</button>
          </div>
          {pct !== null && <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress" style={{ marginTop: 8 }}><div style={{ width: `${pct}%` }} /></div>}
          {queuedKey && pct === null && !job && (
            <p className="muted small-text" role="status">Queued on this device — safe to leave; retry resumes the same file.</p>
          )}
        </div>
      )}
      {job && job.status !== "done" && job.status !== "error" && (
        <div style={{ marginTop: 10 }}>
          <h3>Building your guide…</h3>
          <div className="progress" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${job.progress}%` }} /></div>
          <p className="muted">{job.progress}% — you can leave this screen; the tutorial keeps processing on the server and appears in the library.</p>
        </div>
      )}
      {job?.status === "error" && (
        <div className="notice error" role="alert" style={{ marginTop: 10 }}>
          <strong>Processing failed.</strong> {job.error || "Unknown error."}
        </div>
      )}
      {job?.status === "done" && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" onClick={() => onOpenStudio({ id: job.id, access_token: job.access_token, title: job.title } as LibraryItem)}>Open in Tutorial Studio</button>
          <span className="muted small-text">Processing complete — edit transcript, steps, guide, video, and visuals.</span>
        </div>
      )}
    </div>
  );
}

export function QueuedUploads({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<QueuedTutorialUpload[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function load() {
    try { setItems(await listQueuedUploads()); } catch { /* best-effort */ }
  }
  useEffect(() => { void load(); }, []);

  async function retry(key: string) {
    setBusy(key);
    setError("");
    try {
      const entry = (await listQueuedUploads()).find((e) => e.key === key);
      if (!entry) return;
      await runQueuedUpload(entry);
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Retry failed"); }
    finally { setBusy(null); await load(); }
  }

  async function discard(key: string) {
    if (!window.confirm("Discard this queued upload? The local file will be removed from this device.")) return;
    await removeQueuedUpload(key);
    await load();
    onChanged();
  }

  if (!items.length) return null;
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}><Icon name="schedule" size={18} /> Queued uploads ({items.length})</h3>
      <p className="muted small-text">Files saved on this device, waiting for a confirmed server upload. They survive reloads.</p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {items.map((it) => (
        <div key={it.key} className="list-row">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div style={{ minWidth: 0 }}>
              <strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>{it.title || it.filename}</strong>
              <span className="muted small-text num">{fmtSize(it.size)} · {it.mode.replace(/_/g, " ")} · {it.state}{it.attempts ? ` · ${it.attempts} attempt(s)` : ""}</span>
              {it.error && <div className="muted small-text">{it.error}</div>}
            </div>
            <span className="row">
              <button className="btn small" disabled={busy === it.key} onClick={() => void retry(it.key)}>Retry upload</button>
              <button className="btn small secondary" disabled={busy === it.key} onClick={() => void discard(it.key)}>Discard</button>
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
