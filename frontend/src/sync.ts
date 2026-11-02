// Reliable offline synchronization engine.
//
// Replaces the old generic problems-count with per-item diagnostics that
// persist in IndexedDB, dependency-aware ordering (events/photos/finishes
// wait for their job registration), stable evidence-event IDs, and a
// concurrency guard. Nothing is silently discarded: every failure stays
// queued with its reason until it succeeds or the user explicitly
// discards it after a confirmation.
import { api, HttpError } from "./api";
import { idb, uuid } from "./db";
import type { JobEventRec } from "./types";

export interface PendingReg { job_id: string; procedure_id: string; procedure_version_id: string; grant?: string }
export interface PendingFinish { job_id: string; outcome: string }
export interface PendingPhoto { key: string; job_id: string; step_id: string | null; description: string }

export type SyncQueue = "registration" | "photo" | "event" | "finish";
export type SyncClassification =
  | "network" | "auth" | "registration" | "revision" | "unknown-session"
  | "photo" | "media-missing" | "validation" | "finish" | "server" | "unknown";

export interface SyncReportItem {
  id: string;
  queue: SyncQueue;
  itemId: string;
  jobId?: string;
  op: string;
  error: string;
  status?: number;
  classification: SyncClassification;
  firstFailedAt: string;
  lastAttemptAt: string;
  attempts: number;
  recoverable: boolean;
  action: string;
}

export interface SyncReport {
  items: SyncReportItem[];
  lastSuccessAt: string | null;
}

export interface SyncResult {
  ran: boolean;
  aborted: boolean;
  problems: number;
  syncedEvents: number;
  syncedPhotos: number;
  syncedRegs: number;
  syncedFinishes: number;
  message: string;
}

const REPORT_KEY = "sync-report";
const LAST_OK_KEY = "last-sync-ok";
const GRANTS_KEY = "offline-grants";

let running = false;

function nowIso(): string {
  return new Date().toISOString();
}

export function isNetworkError(e: unknown): boolean {
  if (e instanceof TypeError) return true;
  const m = e instanceof Error ? e.message : String(e);
  return /failed to fetch|networkerror|load failed|network request failed|offline/i.test(m);
}

export function classifyError(e: unknown, queue: SyncQueue): {
  classification: SyncClassification; recoverable: boolean; action: string; status?: number;
} {
  if (isNetworkError(e)) {
    return { classification: "network", recoverable: true, action: "Reconnect and retry — nothing was marked synced." };
  }
  const status = e instanceof HttpError ? e.status : undefined;
  const msg = e instanceof Error ? e.message : String(e);
  if (status === 401) {
    return { classification: "auth", recoverable: true, status, action: "Sign in again, then retry synchronization." };
  }
  if (/approved|superseded/i.test(msg)) {
    return { classification: "revision", recoverable: false, status, action: "This procedure revision can no longer accept jobs. Start a new job from the current approved revision; the queued work stays on this device for reference." };
  }
  if (/unknown session/i.test(msg)) {
    return { classification: "unknown-session", recoverable: true, status, action: "The server has no record of this job session. If its registration is still queued it will sync first; otherwise verify the job exists on the server." };
  }
  if (queue === "photo" || /415|413|photo|evidence|too large|only JPEG|image/i.test(msg)) {
    const tooBig = /413|too large/i.test(msg);
    return { classification: "photo", recoverable: !tooBig, status, action: tooBig ? "This photo exceeds the 8 MB server limit — attach a smaller photo." : "Retry the upload; the photo stays queued on this device." };
  }
  if (status === 422 || /validation|invalid|missing|must be/i.test(msg)) {
    return { classification: "validation", recoverable: false, status, action: "The server rejected this item as invalid. It cannot sync as-is — discard it or fix the underlying data." };
  }
  if (queue === "finish") {
    if (status === 404) {
      return { classification: "finish", recoverable: false, status, action: "The job record is missing on the server, so its finish state cannot be confirmed." };
    }
    return { classification: "finish", recoverable: true, status, action: "Retry synchronization to confirm the finished state." };
  }
  if (queue === "registration" && status === 409) {
    return { classification: "registration", recoverable: false, status, action: "Job registration was rejected (conflicting id or revision). Check the message, then discard or re-create the job." };
  }
  if (status !== undefined && status >= 500) {
    return { classification: "server", recoverable: true, status, action: "The server errored — your work stays queued. Retry later." };
  }
  return { classification: "unknown", recoverable: true, status, action: "Retry synchronization; the item stays queued on this device." };
}

export async function loadReport(): Promise<SyncReport> {
  const items = (await idb.get<SyncReportItem[]>("meta", REPORT_KEY)) || [];
  const lastSuccessAt = (await idb.get<string>("meta", LAST_OK_KEY)) || null;
  return { items, lastSuccessAt };
}

async function saveReport(items: SyncReportItem[]): Promise<void> {
  await idb.put("meta", REPORT_KEY, items);
}

function upsert(items: SyncReportItem[], entry: Omit<SyncReportItem, "id" | "firstFailedAt" | "attempts" | "lastAttemptAt">): SyncReportItem[] {
  const id = `${entry.queue}:${entry.itemId}`;
  const at = nowIso();
  const prev = items.find((i) => i.id === id);
  const next: SyncReportItem = prev
    ? { ...prev, ...entry, id, lastAttemptAt: at, attempts: prev.attempts + 1 }
    : { ...entry, id, firstFailedAt: at, lastAttemptAt: at, attempts: 1 };
  return [...items.filter((i) => i.id !== id), next];
}

function drop(items: SyncReportItem[], queue: SyncQueue, itemId: string): SyncReportItem[] {
  return items.filter((i) => !(i.queue === queue && i.itemId === itemId));
}

async function loadPending<T>(key: string): Promise<T[]> {
  return (await idb.get<T[]>("meta", key)) || [];
}
async function savePending<T>(key: string, items: T[]): Promise<void> {
  await idb.put("meta", key, items);
}

export async function getStoredGrant(versionId: string): Promise<string | undefined> {
  const grants = (await idb.get<Record<string, string>>("meta", GRANTS_KEY)) || {};
  return grants[versionId];
}

export async function storeGrant(versionId: string, grant: string): Promise<void> {
  const grants = (await idb.get<Record<string, string>>("meta", GRANTS_KEY)) || {};
  grants[versionId] = grant;
  await idb.put("meta", GRANTS_KEY, grants);
}

/** Discard one queued item plus its diagnostic entry. Caller must confirm first. */
export async function discardQueuedItem(queue: SyncQueue, itemId: string): Promise<void> {
  if (queue === "registration") {
    await savePending("pending-regs", (await loadPending<PendingReg>("pending-regs")).filter((r) => r.job_id !== itemId));
  } else if (queue === "photo") {
    const photos = await loadPending<PendingPhoto>("pending-photos");
    const hit = photos.find((p) => p.key === itemId);
    await savePending("pending-photos", photos.filter((p) => p.key !== itemId));
    if (hit) await idb.del("media", hit.key);
  } else if (queue === "event") {
    const row = await idb.get<JobEventRec>("events", itemId);
    if (row && row.sync_status === "pending") await idb.del("events", itemId);
  } else {
    await savePending("pending-finishes", (await loadPending<PendingFinish>("pending-finishes")).filter((f) => f.job_id !== itemId));
  }
  await saveReport(drop((await loadReport()).items, queue, itemId));
}

export async function runSync(): Promise<SyncResult> {
  if (running) {
    return { ran: false, aborted: false, problems: 0, syncedEvents: 0, syncedPhotos: 0, syncedRegs: 0, syncedFinishes: 0, message: "A synchronization is already running." };
  }
  running = true;
  let report = (await loadReport()).items;
  const counts = { regs: 0, photos: 0, events: 0, finishes: 0 };
  try {
    try {
      await api.get("/api/health");
    } catch (e) {
      // Only a network failure aborts the run: an HTTP error means the
      // server is reachable, so per-item attempts still run and classify.
      if (isNetworkError(e)) {
        return { ran: true, aborted: true, problems: 0, syncedEvents: 0, syncedPhotos: 0, syncedRegs: 0, syncedFinishes: 0, message: "Server unreachable. Your work stays queued on this device — nothing is marked synced." };
      }
    }

    // 1) Register offline jobs under their stable local ids first.
    const regs = await loadPending<PendingReg>("pending-regs");
    const seenRegs = new Set(regs.map((r) => r.job_id));
    const remainingRegs: PendingReg[] = [];
    const unregistered = new Set<string>();
    for (const reg of regs) {
      try {
        const body: Record<string, string> = { id: reg.job_id, procedure_id: reg.procedure_id, procedure_version_id: reg.procedure_version_id };
        if (reg.grant) body.offline_grant = reg.grant;
        await api.post("/api/jobs", body);
        counts.regs++;
        report = drop(report, "registration", reg.job_id);
      } catch (e) {
        if (isNetworkError(e)) {
          const freshRegs = (await loadPending<PendingReg>("pending-regs")).filter((r) => !seenRegs.has(r.job_id));
          await savePending("pending-regs", [...regs, ...freshRegs]);
          await saveReport(report);
          return { ran: true, aborted: true, problems: 0, syncedEvents: 0, syncedPhotos: 0, syncedRegs: counts.regs, syncedFinishes: 0, message: "Connection dropped mid-sync. Everything stays queued — retry when connected." };
        }
        const c = classifyError(e, "registration");
        remainingRegs.push(reg);
        unregistered.add(reg.job_id);
        report = upsert(report, {
          queue: "registration", itemId: reg.job_id, jobId: reg.job_id, op: "register job",
          error: e instanceof Error ? e.message : String(e), ...c,
        });
      }
    }
    // Registrations never attempted before (e.g. from an older app
    // version) still block their dependents this run.
    for (const reg of regs) {
      if (!remainingRegs.some((r) => r.job_id === reg.job_id)) continue;
      unregistered.add(reg.job_id);
    }
    await savePending("pending-regs", [...remainingRegs,
      ...(await loadPending<PendingReg>("pending-regs")).filter((r) => !seenRegs.has(r.job_id))]);

    // 2) Upload job photos queued while offline. Dependents of failed
    // registrations wait — they become eligible automatically on retry.
    const pendingPhotos = await loadPending<PendingPhoto>("pending-photos");
    if (pendingPhotos.length) {
      const seen = new Set(pendingPhotos.map((p) => p.key));
      const remainingPhotos: PendingPhoto[] = [];
      for (const ph of pendingPhotos) {
        if (unregistered.has(ph.job_id)) {
          report = upsert(report, {
            queue: "photo", itemId: ph.key, jobId: ph.job_id, op: "upload photo",
            error: "Waiting for the job registration to succeed first.", classification: "registration",
            recoverable: true, action: "No action needed — this photo syncs automatically once its job registers.",
          });
          remainingPhotos.push(ph);
          continue;
        }
        try {
          const blob = await idb.get<Blob>("media", ph.key);
          if (!blob) {
            // Orphaned queue record: the bytes are gone and unrecoverable.
            // Record the loss honestly instead of silently dropping it.
            report = upsert(report, {
              queue: "photo", itemId: ph.key, jobId: ph.job_id, op: "upload photo",
              error: "Local photo bytes are missing from this device (storage evicted or cleared).",
              classification: "media-missing", recoverable: false,
              action: "This photo cannot be recovered. Re-attach it in the job, or discard this queue entry.",
            });
            continue;
          }
          const fd = new FormData();
          fd.append("file", blob, "job-photo.jpg");
          fd.append("description", ph.description);
          if (ph.step_id) fd.append("step_id", ph.step_id);
          const up = await api.upload<{ id: string }>(`/api/jobs/${ph.job_id}/evidence`, fd);
          await idb.del("media", ph.key);
          // Stable id derived from the queue key: photo retries must not
          // mint duplicate evidence_attached events.
          const evid = `evidence:${ph.key}`;
          await idb.put("events", evid, { event_id: evid, session_id: ph.job_id, step_id: ph.step_id, event_type: "evidence_attached", payload: { evidence_id: up.id, description: ph.description }, occurred_at: nowIso(), sync_status: "pending" });
          counts.photos++;
          report = drop(report, "photo", ph.key);
        } catch (e) {
          if (isNetworkError(e)) {
            remainingPhotos.push(ph);
            // Keep anything queued concurrently during this run.
            const fresh = (await loadPending<PendingPhoto>("pending-photos")).filter((p) => !seen.has(p.key));
            await savePending("pending-photos", [...remainingPhotos, ...pendingPhotos.slice(pendingPhotos.indexOf(ph) + 1).filter((p) => !remainingPhotos.some((r) => r.key === p.key)), ...fresh]);
            await saveReport(report);
            return { ran: true, aborted: true, problems: report.length, syncedEvents: counts.events, syncedPhotos: counts.photos, syncedRegs: counts.regs, syncedFinishes: counts.finishes, message: "Connection dropped mid-sync. Everything stays queued — retry when connected." };
          }
          const c = classifyError(e, "photo");
          remainingPhotos.push(ph);
          report = upsert(report, {
            queue: "photo", itemId: ph.key, jobId: ph.job_id, op: "upload photo",
            error: e instanceof Error ? e.message : String(e), ...c,
          });
        }
      }
      const fresh = (await loadPending<PendingPhoto>("pending-photos")).filter((p) => !seen.has(p.key));
      await savePending("pending-photos", [...remainingPhotos, ...fresh]);
    }

    // 3) Sync queued events — only for sessions whose registration is settled.
    const allEvs = (await idb.all<JobEventRec>("events")).filter((e) => e.sync_status === "pending");
    const eligible = allEvs.filter((e) => !unregistered.has(e.session_id));
    const waiting = allEvs.filter((e) => unregistered.has(e.session_id));
    for (const w of waiting) {
      report = upsert(report, {
        queue: "event", itemId: w.event_id, jobId: w.session_id, op: `sync ${w.event_type}`,
        error: "Waiting for the job registration to succeed first.", classification: "registration",
        recoverable: true, action: "No action needed — these events sync automatically once the job registers.",
      });
    }
    if (eligible.length) {
      try {
        const res = await api.post<{ acknowledged: string[]; duplicates?: string[]; failed?: { event_id: string; error: string }[] }>("/api/sync/events", { events: eligible });
        const doneIds = new Set([...(res.acknowledged || []), ...(res.duplicates || [])]);
        for (const id of doneIds) {
          const row = eligible.find((e) => e.event_id === id);
          if (row) await idb.put("events", id, { ...row, sync_status: "synced" });
          report = drop(report, "event", id);
        }
        counts.events = doneIds.size;
        for (const f of res.failed || []) {
          const row = eligible.find((e) => e.event_id === f.event_id);
          const c = classifyError(new Error(f.error), "event");
          report = upsert(report, {
            queue: "event", itemId: f.event_id, jobId: row?.session_id, op: `sync ${row?.event_type || "event"}`,
            error: f.error, ...c,
          });
        }
      } catch (e) {
        if (isNetworkError(e)) {
          await saveReport(report);
          return { ran: true, aborted: true, problems: report.length, syncedEvents: counts.events, syncedPhotos: counts.photos, syncedRegs: counts.regs, syncedFinishes: counts.finishes, message: "Connection dropped mid-sync. Everything stays queued — retry when connected." };
        }
        throw e;
      }
    }

    // 4) Push locally-finished states; the server finish is idempotent.
    const finishes = await loadPending<PendingFinish>("pending-finishes");
    const seenFinishes = new Set(finishes.map((f) => f.job_id));
    if (finishes.length) {
      const remaining: PendingFinish[] = [];
      for (const f of finishes) {
        if (unregistered.has(f.job_id)) {
          report = upsert(report, {
            queue: "finish", itemId: f.job_id, jobId: f.job_id, op: "finish job",
            error: "Waiting for the job registration to succeed first.", classification: "registration",
            recoverable: true, action: "No action needed — the finish state syncs automatically once the job registers.",
          });
          remaining.push(f);
          continue;
        }
        try {
          await api.post(`/api/jobs/${f.job_id}/finish`, { outcome: f.outcome, reason: "", summary: "" });
          counts.finishes++;
          report = drop(report, "finish", f.job_id);
        } catch (e) {
          if (isNetworkError(e)) {
            remaining.push(f);
            const freshFin = (await loadPending<PendingFinish>("pending-finishes")).filter((x) => !seenFinishes.has(x.job_id));
            await savePending("pending-finishes", [...remaining, ...finishes.slice(finishes.indexOf(f) + 1).filter((x) => !remaining.some((r) => r.job_id === x.job_id)), ...freshFin]);
            await saveReport(report);
            return { ran: true, aborted: true, problems: report.length, syncedEvents: counts.events, syncedPhotos: counts.photos, syncedRegs: counts.regs, syncedFinishes: counts.finishes, message: "Connection dropped mid-sync. Everything stays queued — retry when connected." };
          }
          const c = classifyError(e, "finish");
          remaining.push(f);
          report = upsert(report, {
            queue: "finish", itemId: f.job_id, jobId: f.job_id, op: "finish job",
            error: e instanceof Error ? e.message : String(e), ...c,
          });
        }
      }
      await savePending("pending-finishes", [...remaining,
        ...(await loadPending<PendingFinish>("pending-finishes")).filter((f) => !seenFinishes.has(f.job_id))]);
    }

    await saveReport(report);
    const problems = report.length;
    if (problems === 0) {
      await idb.put("meta", LAST_OK_KEY, nowIso());
    }
    const did = counts.regs + counts.photos + counts.events + counts.finishes;
    return {
      ran: true, aborted: false, problems,
      syncedEvents: counts.events, syncedPhotos: counts.photos, syncedRegs: counts.regs, syncedFinishes: counts.finishes,
      message: problems ? `Synchronization incomplete: ${problems} item(s) need attention — see Activity for details. Everything stays queued on this device.`
        : did ? "Synchronization complete — the server confirmed your work."
        : "Nothing pending to synchronize.",
    };
  } finally {
    running = false;
  }
}
