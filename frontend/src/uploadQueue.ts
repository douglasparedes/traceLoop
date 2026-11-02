// Shared tutorial upload path: recordings and selected files create the
// same TutorialJob via POST /api/tutorial/start. Uploads are queued in
// IndexedDB first (blob + metadata), so a network interruption never loses
// the recording — the queue entry survives reload until the server confirms
// persistence, and only then is it removed.
import { API, getIdentity, getToken } from "./api";
import { idb, uuid } from "./db";

export type AnalysisMode = "auto" | "narrated" | "visual_first";
export const ANALYSIS_MODES: { id: AnalysisMode; label: string; blurb: string }[] = [
  { id: "auto", label: "Automatic", blurb: "TraceLoop chooses: narration-led when speech is sufficient, visual-first otherwise." },
  { id: "narrated", label: "Narrated", blurb: "Speech is the main source. Fails clearly if there is no usable narration." },
  { id: "visual_first", label: "Visual-First", blurb: "Analyzes the actions shown; narration is optional supplementary context." },
];

export const PENDING_TUTORIAL_UPLOADS = "pending-tutorial-uploads";
export const MAX_TUTORIAL_BYTES = 300 * 1024 * 1024;
export const ACCEPTED_EXTS = [".mp4", ".webm", ".mov", ".mkv"];
const ACCEPTED_MIME = ["video/mp4", "video/webm", "video/quicktime", "video/x-matroska"];

export interface QueuedTutorialUpload {
  key: string;
  filename: string;
  mime: string;
  size: number;
  title: string;
  equipment: string;
  task: string;
  notes: string;
  mode: AnalysisMode;
  origin: "recorded" | "uploaded";
  state: "queued" | "uploading" | "failed";
  progress: number | null;
  error: string;
  attempts: number;
  createdAt: string;
}

export function validateTutorialFile(f: File): string | null {
  const ext = `.${(f.name.split(".").pop() || "").toLowerCase()}`;
  const baseMime = (f.type || "").split(";")[0].trim().toLowerCase();
  const extOk = ACCEPTED_EXTS.includes(ext);
  const mimeOk = !baseMime || ACCEPTED_MIME.includes(baseMime);
  if (!extOk || !mimeOk) {
    return `Unsupported file “${f.name}”. Use MP4, WebM, MOV, or MKV (max 300 MB).`;
  }
  if (f.size <= 0) return "That file is empty — pick a different recording.";
  if (f.size > MAX_TUTORIAL_BYTES) {
    return `This file is ${(f.size / 1024 / 1024).toFixed(0)} MB — tutorials are limited to 300 MB. Trim or re-export it first.`;
  }
  return null;
}

export async function checkStorageFor(bytes: number): Promise<{ ok: boolean; message: string }> {
  try {
    if (!navigator.storage?.estimate) return { ok: true, message: "" };
    const est = await navigator.storage.estimate();
    const quota = est.quota || 0;
    const usage = est.usage || 0;
    if (quota > 0 && usage + bytes > quota * 0.9) {
      return { ok: false, message: "This device is almost out of site storage, so the file cannot be safely kept locally. Stay connected until the server confirms the upload." };
    }
    return { ok: true, message: "" };
  } catch {
    return { ok: true, message: "" };
  }
}

export async function requestPersistentStorage(): Promise<void> {
  try { await navigator.storage?.persist?.(); } catch { /* best-effort */ }
}

export async function queueTutorialUpload(input: {
  blob: Blob; filename: string; title: string; equipment?: string; task?: string;
  notes?: string; mode: AnalysisMode; origin: "recorded" | "uploaded";
}): Promise<QueuedTutorialUpload> {
  const key = `tut-upload:${uuid()}`;
  const entry: QueuedTutorialUpload = {
    key,
    filename: input.filename,
    mime: (input.blob.type || "video/mp4").split(";")[0].trim() || "video/mp4",
    size: input.blob.size,
    title: input.title,
    equipment: input.equipment || "",
    task: input.task || "",
    notes: input.notes || "",
    mode: input.mode,
    origin: input.origin,
    state: "queued",
    progress: null,
    error: "",
    attempts: 0,
    createdAt: new Date().toISOString(),
  };
  await idb.put("media", key, input.blob);
  const all = (await idb.get<QueuedTutorialUpload[]>("meta", PENDING_TUTORIAL_UPLOADS)) || [];
  await idb.put("meta", PENDING_TUTORIAL_UPLOADS, [...all, entry]);
  return entry;
}

export async function listQueuedUploads(): Promise<QueuedTutorialUpload[]> {
  return (await idb.get<QueuedTutorialUpload[]>("meta", PENDING_TUTORIAL_UPLOADS)) || [];
}

async function patchQueuedUpload(key: string, patch: Partial<QueuedTutorialUpload>): Promise<void> {
  const all = await listQueuedUploads();
  await idb.put("meta", PENDING_TUTORIAL_UPLOADS, all.map((e) => (e.key === key ? { ...e, ...patch } : e)));
}

export async function removeQueuedUpload(key: string): Promise<void> {
  await idb.del("media", key);
  const all = await listQueuedUploads();
  await idb.put("meta", PENDING_TUTORIAL_UPLOADS, all.filter((e) => e.key !== key));
}

export interface UploadedTutorialJob {
  id: string;
  title: string;
  status: string;
  progress: number;
  error?: string;
  access_token: string;
  [k: string]: unknown;
}

/** Stream the file to POST /api/tutorial/start with progress + cancel.
 * Resolves only after the server confirms persistence (it created the job). */
export function uploadTutorialFile(opts: {
  blob: Blob;
  filename: string;
  title: string;
  equipment?: string;
  task?: string;
  notes?: string;
  mode: AnalysisMode;
  origin: "recorded" | "uploaded";
  onProgress?: (pct: number) => void;
  signal?: { cancelled: boolean };
}): Promise<UploadedTutorialJob> {
  return new Promise((resolve, reject) => {
    const idn = getIdentity();
    const fd = new FormData();
    fd.append("file", new File([opts.blob], opts.filename, { type: (opts.blob.type || "video/mp4").split(";")[0] }));
    fd.append("title", opts.title);
    fd.append("mode", opts.mode);
    fd.append("origin", opts.origin);
    if (opts.equipment) fd.append("equipment_name", opts.equipment);
    if (opts.task) fd.append("task_description", opts.task);
    if (opts.notes) fd.append("context_notes", opts.notes);
    const xhr = new XMLHttpRequest();
    const cancelTick = window.setInterval(() => {
      if (opts.signal?.cancelled) { try { xhr.abort(); } catch { /* noop */ } }
    }, 200);
    xhr.open("POST", `${API}/api/tutorial/start`);
    xhr.setRequestHeader("X-User", idn.user);
    xhr.setRequestHeader("X-Role", idn.role);
    const tok = getToken();
    if (tok) xhr.setRequestHeader("X-Auth-Token", tok);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      window.clearInterval(cancelTick);
      try {
        const body = JSON.parse(xhr.responseText) as UploadedTutorialJob & { detail?: string };
        if (xhr.status >= 400) throw new Error(body.detail || `Upload failed (${xhr.status})`);
        resolve(body);
      } catch (e) { reject(e instanceof Error ? e : new Error("Upload failed")); }
    };
    xhr.onerror = () => { window.clearInterval(cancelTick); reject(new Error("Upload failed — check the connection and retry. Your file is still queued on this device.")); };
    xhr.onabort = () => { window.clearInterval(cancelTick); reject(new Error("Upload cancelled. Your file is still queued on this device — retry when ready.")); };
    xhr.send(fd);
  });
}

/** Upload one queued entry: marks uploading, cleans up on server confirm,
 * records attempts + error on failure so the entry can be retried. */
export async function runQueuedUpload(
  entry: QueuedTutorialUpload,
  onProgress?: (pct: number) => void,
  signal?: { cancelled: boolean },
): Promise<UploadedTutorialJob> {
  const blob = await idb.get<Blob>("media", entry.key);
  if (!blob) throw new Error("Queued file bytes are missing from this device. Re-select the file to upload it.");
  await patchQueuedUpload(entry.key, { state: "uploading", progress: 0, error: "", attempts: entry.attempts + 1 });
  try {
    const job = await uploadTutorialFile({
      blob, filename: entry.filename, title: entry.title, equipment: entry.equipment,
      task: entry.task, notes: entry.notes, mode: entry.mode, origin: entry.origin,
      onProgress: (p) => { onProgress?.(p); void patchQueuedUpload(entry.key, { progress: p }); },
      signal,
    });
    // Server confirmed persistence: only now is the local copy redundant.
    await removeQueuedUpload(entry.key);
    return job;
  } catch (e) {
    await patchQueuedUpload(entry.key, { state: "failed", progress: null, error: e instanceof Error ? e.message : "Upload failed" });
    throw e;
  }
}
