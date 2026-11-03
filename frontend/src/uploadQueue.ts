// Shared tutorial upload: recordings and selected files create the same
// TutorialJob via chunked, resumable uploads. Each video is split into
// small offset-addressed chunks so per-request proxy/CDN size caps stop
// mattering; the queue entry (IndexedDB) survives reloads and network drops,
// and the server confirms every byte before the job is created.
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
/** Chunk size for resumable uploads: small enough to pass per-request
 * proxy/CDN caps, large enough to keep request counts sane. */
export const CHUNK_BYTES = 4 * 1024 * 1024;
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
  /** Server upload session for resume across reloads/retries. */
  uploadId?: string;
  /** Bytes the server has confirmed (authoritative resume offset). */
  confirmedBytes?: number;
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

/** Refresh an existing queue entry's metadata in place (title, notes,
 *  mode, …) without creating a new entry, blob, or server session.
 *  Returns the updated entry, or null when the key is gone. */
export async function refreshQueuedUpload(key: string, fields: {
  title?: string; equipment?: string; task?: string; notes?: string; mode?: AnalysisMode;
}): Promise<QueuedTutorialUpload | null> {
  const all = await listQueuedUploads();
  const cur = all.find((e) => e.key === key);
  if (!cur) return null;
  const next = { ...cur, ...fields };
  await idb.put("meta", PENDING_TUTORIAL_UPLOADS, all.map((e) => (e.key === key ? next : e)));
  return next;
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
  /** True when the server returned a previously finished tutorial for
   *  byte-identical content instead of creating a new job. */
  cached?: boolean;
  [k: string]: unknown;
}

/** Parse a tutorial-API JSON response that may not be JSON.
 *
 * Proxies, CDNs, and mis-addressed API URLs answer with HTML error pages;
 * blind JSON.parse turns those into "Unexpected token '<'…" which tells the
 * technician nothing. This maps the outcome to an actionable message while
 * keeping the queued local copy intact (callers must NOT delete the queue
 * entry on these errors).
 */
export function parseUploadResponse(status: number, text: string, contentType: string | null): UploadedTutorialJob {
  return parseApiJson<UploadedTutorialJob>(status, text, contentType);
}

/** Generic version of parseUploadResponse for non-upload endpoints. */
export function parseApiJson<T>(status: number, text: string, contentType: string | null): T {
  let body: (T & { detail?: string; message?: string }) | null = null;
  try {
    body = JSON.parse(text) as T & { detail?: string; message?: string };
  } catch {
    body = null;
  }
  if (body && typeof body === "object") {
    if (status >= 400) throw new Error(body.detail || (body as { message?: string }).message || `Request failed (${status})`);
    return body as T;
  }
  const looksHtml = /<\s*(!doctype|html)/i.test((text || "").slice(0, 500)) || (contentType || "").includes("text/html");
  if (looksHtml) {
    if (status === 413) {
      throw new Error("The upload was rejected as too large before reaching TraceLoop (likely a proxy or mobile-network limit below the app's 300 MB cap). Try a shorter or lower-resolution video, or upload over Wi-Fi. Your file is still queued on this device.");
    }
    if (status >= 200 && status < 300) {
      throw new Error("The server answered with a web page instead of data. The app is probably talking to the wrong address — install/open the PWA from the same server that runs the API, reload, and retry. Your file is still queued on this device.");
    }
    if (status === 401 || status === 403) {
      throw new Error("The server refused the request (sign-in required or expired). Sign in again, then retry — your file is still queued on this device.");
    }
    throw new Error(`Request failed (HTTP ${status || "unknown"}): the server returned an unreadable error page instead of data. Your file is still queued on this device — check the connection and retry.`);
  }
  if (status >= 400) throw new Error(`Request failed (${status}). Your file is still queued on this device — retry when connected.`);
  throw new Error("The server returned an empty or unreadable response. Your file is still queued on this device.");
}

function authHeaders(): Record<string, string> {
  const idn = getIdentity();
  const h: Record<string, string> = { "X-User": idn.user, "X-Role": idn.role };
  const tok = getToken();
  if (tok) h["X-Auth-Token"] = tok;
  return h;
}

async function apiJson<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...authHeaders(), ...(init.headers || {}) } });
  const text = await res.text();
  let ct: string | null = null;
  try { ct = res.headers.get("Content-Type"); } catch { /* noop */ }
  return parseApiJson<T>(res.status, text, ct);
}

/** Find the queue entry a retry should resume: same key and same file
 *  size (guards against reusing a stale entry after picking a new file).
 *  Returns null when a fresh queue entry must be created. */
export function findReusableUpload(entries: QueuedTutorialUpload[], key: string | null, size: number): QueuedTutorialUpload | null {
  if (!key) return null;
  return entries.find((e) => e.key === key && e.size === size) || null;
}

/** Incremental SHA-256 over Blob slices, so even a 300 MB file is never
 * fully loaded into memory to compute its checksum. */
class Sha256Stream {
  private h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  private buf = new Uint8Array(64);
  private bufLen = 0;
  private totalLen = 0;
  private static K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  private static rotr(x: number, n: number) { return (x >>> n) | (x << (32 - n)); }

  private compress(block: Uint8Array) {
    const K = Sha256Stream.K;
    const rotr = Sha256Stream.rotr;
    const w = new Array<number>(64);
    for (let i = 0; i < 16; i++) {
      w[i] = (block[i * 4] << 24) | (block[i * 4 + 1] << 16) | (block[i * 4 + 2] << 8) | block[i * 4 + 3];
    }
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    const h = this.h;
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K[i] + w[i]) | 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;
      hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0; h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
  }

  update(bytes: Uint8Array) {
    this.totalLen += bytes.length;
    let off = 0;
    if (this.bufLen > 0) {
      const need = 64 - this.bufLen;
      const take = Math.min(need, bytes.length);
      this.buf.set(bytes.subarray(0, take), this.bufLen);
      this.bufLen += take;
      off = take;
      if (this.bufLen === 64) { this.compress(this.buf); this.bufLen = 0; }
    }
    while (off + 64 <= bytes.length) {
      this.compress(bytes.subarray(off, off + 64));
      off += 64;
    }
    if (off < bytes.length) {
      this.buf.set(bytes.subarray(off), 0);
      this.bufLen = bytes.length - off;
    }
  }

  digest(): string {
    const bitLen = this.totalLen * 8;
    const pad: number[] = [0x80];
    const tail = (this.bufLen + 1) % 64;
    const zeros = tail <= 56 ? 56 - tail : 64 + 56 - tail;
    for (let i = 0; i < zeros; i++) pad.push(0);
    // 64-bit length; high word is zero for any tutorial-sized file.
    const hi = Math.floor(bitLen / 0x100000000);
    const lo = bitLen >>> 0;
    pad.push((hi >>> 24) & 0xff, (hi >>> 16) & 0xff, (hi >>> 8) & 0xff, hi & 0xff,
             (lo >>> 24) & 0xff, (lo >>> 16) & 0xff, (lo >>> 8) & 0xff, lo & 0xff);
    this.update(new Uint8Array(pad));
    return this.h.map((x) => (x >>> 0).toString(16).padStart(8, "0")).join("");
  }
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const s = new Sha256Stream();
  const CH = 1024 * 1024;
  for (let off = 0; off < blob.size; off += CH) {
    s.update(new Uint8Array(await blob.slice(off, off + CH).arrayBuffer()));
  }
  return s.digest();
}

/** PUT one chunk with progress + cancellation. Resolves with the parsed body. */
function putChunk(url: string, blob: Blob, offset: number, onProgress?: (loaded: number) => void, signal?: { cancelled: boolean }): Promise<{ received_bytes: number; total_size: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const clearTick = () => { try { (globalThis as unknown as { clearInterval: typeof clearInterval }).clearInterval(tick); } catch { /* noop */ } };
    const tick = (globalThis as unknown as { setInterval: typeof setInterval }).setInterval(() => {
      if (signal?.cancelled) { try { xhr.abort(); } catch { /* noop */ } }
    }, 200);
    xhr.open("PUT", url);
    const h = authHeaders();
    for (const k of Object.keys(h)) xhr.setRequestHeader(k, h[k]);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(offset + e.loaded);
    };
    xhr.onload = () => {
      clearTick();
      try {
        resolve(parseApiJson<{ received_bytes: number; total_size: number }>(xhr.status, xhr.responseText, xhr.getResponseHeader("Content-Type")));
      } catch (e) { reject(e instanceof Error ? e : new Error("Chunk upload failed")); }
    };
    xhr.onerror = () => { clearTick(); reject(new Error("Chunk upload failed — check the connection. Confirmed bytes stay on the server; retry resumes automatically.")); };
    xhr.onabort = () => { clearTick(); reject(new Error("Upload cancelled. Confirmed bytes stay on the server — retry resumes where it stopped.")); };
    xhr.send(blob);
  });
}

/** Upload one queued tutorial in small resumable chunks.
 *
 * Flow: hash (streamed) → open/resume session → PUT chunks at
 * server-confirmed offsets → complete (server verifies size + hash, then
 * creates the job). Resolves only with the created TutorialJob; the queue
 * entry is removed only then. Any interruption leaves server-confirmed
 * bytes + the local file, so a retry resumes instead of restarting.
 */
export async function runQueuedUpload(
  entry: QueuedTutorialUpload,
  onProgress?: (pct: number) => void,
  signal?: { cancelled: boolean },
  opts?: { forceNew?: boolean },
): Promise<UploadedTutorialJob> {
  const blob = await idb.get<Blob>("media", entry.key);
  if (!blob) throw new Error("Queued file bytes are missing from this device. Re-select the file to upload it.");
  const report = (confirmed: number) => onProgress?.(blob.size ? Math.round((confirmed / blob.size) * 100) : 0);
  await patchQueuedUpload(entry.key, { state: "uploading", error: "", attempts: entry.attempts + 1 });
  const fail = async (e: unknown): Promise<never> => {
    const msg = e instanceof Error ? e.message : "Upload failed";
    const cancelled = /cancelled/i.test(msg);
    await patchQueuedUpload(entry.key, { state: cancelled ? "queued" : "failed", progress: null, error: cancelled ? "" : msg });
    throw e instanceof Error ? e : new Error(msg);
  };
  try {
    // 1) Open (or resume) the server session.
    let uploadId = entry.uploadId;
    let confirmed = entry.confirmedBytes || 0;
    if (uploadId) {
      try {
        const st = await apiJson<{ status: string; received_bytes: number; total_size: number }>(
          `/api/tutorial/uploads/${uploadId}`, { method: "GET" });
        if (st.status !== "open" || st.total_size !== blob.size) uploadId = undefined;
        else confirmed = st.received_bytes;
      } catch {
        uploadId = undefined; // session gone/expired: start over server-side
      }
    }
    if (!uploadId) {
      const hash = await sha256Hex(blob);
      const opened = await apiJson<{ ok: boolean; upload_id: string; chunk_size: number }>(
        "/api/tutorial/uploads",
        {
          method: "POST",
          body: JSON.stringify({
            filename: entry.filename, mime: entry.mime, total_size: blob.size, sha256: hash,
            title: entry.title, equipment_name: entry.equipment, task_description: entry.task,
            context_notes: entry.notes, mode: entry.mode, origin: entry.origin,
          }),
        });
      uploadId = opened.upload_id;
      confirmed = 0;
      await patchQueuedUpload(entry.key, { uploadId, confirmedBytes: 0, progress: 0 });
    } else {
      await patchQueuedUpload(entry.key, { confirmedBytes: confirmed, progress: blob.size ? Math.round((confirmed / blob.size) * 100) : 0 });
    }
    report(confirmed);
    // 2) Send missing chunks at server-confirmed offsets.
    while (confirmed < blob.size) {
      if (signal?.cancelled) {
        await patchQueuedUpload(entry.key, { state: "queued", progress: null, confirmedBytes: confirmed });
        throw new Error("Upload cancelled. Confirmed bytes stay on the server — retry resumes where it stopped.");
      }
      const chunk = blob.slice(confirmed, Math.min(confirmed + CHUNK_BYTES, blob.size));
      const res = await putChunk(
        `${API}/api/tutorial/uploads/${uploadId}/chunks?offset=${confirmed}`,
        chunk,
        confirmed,
        (loaded) => report(Math.min(blob.size, loaded)),
        signal,
      );
      confirmed = res.received_bytes;
      await patchQueuedUpload(entry.key, { confirmedBytes: confirmed, progress: Math.round((confirmed / blob.size) * 100) });
      if (confirmed >= blob.size) break;
      // Server advanced less than a full chunk: re-read its authoritative offset.
      const st = await apiJson<{ status: string; received_bytes: number; total_size: number }>(
        `/api/tutorial/uploads/${uploadId}`, { method: "GET" });
      confirmed = st.received_bytes;
    }
    // 3) Complete: server verifies size + hash, persists, creates the job.
    // forceNew bypasses the identical-bytes cache and always creates a job.
    const completePath = `/api/tutorial/uploads/${uploadId}/complete${opts?.forceNew ? "?force_new=1" : ""}`;
    const job = await apiJson<UploadedTutorialJob>(completePath, { method: "POST" });
    await removeQueuedUpload(entry.key);
    return job;
  } catch (e) {
    if (e instanceof Error && /cancelled/i.test(e.message)) {
      await patchQueuedUpload(entry.key, { state: "queued", progress: null, error: "" });
      throw e;
    }
    return fail(e);
  }
}
