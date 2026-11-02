// Synchronization diagnostics: persistent per-item report with retry and
// explicit discard. Nothing is silently dropped — failures stay queued
// with their reason until they succeed or the user confirms removal.
import { useCallback, useEffect, useState } from "react";
import { idb } from "./db";
import { discardQueuedItem, loadReport, type SyncReportItem } from "./sync";
import { Icon } from "./icons";

const QUEUE_LABEL: Record<string, string> = {
  registration: "Job registration",
  photo: "Photo upload",
  event: "Step completion event",
  finish: "Job finish",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "never";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export default function SyncDiagnostics({ pending, syncing, onSync, onChanged, notify }: {
  pending: number;
  syncing: boolean;
  onSync: () => void;
  onChanged: () => void;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
}) {
  const [items, setItems] = useState<SyncReportItem[]>([]);
  const [lastOk, setLastOk] = useState<string | null>(null);
  const [queues, setQueues] = useState({ regs: 0, photos: 0, finishes: 0 });
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await loadReport();
      setItems(r.items);
      setLastOk(r.lastSuccessAt);
      const regs = (await idb.get<unknown[]>("meta", "pending-regs")) || [];
      const photos = (await idb.get<unknown[]>("meta", "pending-photos")) || [];
      const finishes = (await idb.get<unknown[]>("meta", "pending-finishes")) || [];
      setQueues({ regs: regs.length, photos: photos.length, finishes: finishes.length });
    } catch { /* diagnostics are best-effort; queues keep working */ }
  }, []);

  useEffect(() => { void load(); }, [load, pending]);

  async function discard(item: SyncReportItem) {
    const what = item.queue === "event"
      ? "Discard this queued event? The step outcome it records will be lost on this device."
      : item.queue === "photo"
        ? "Discard this queued photo? The image and its queue entry will be removed from this device."
        : item.queue === "registration"
          ? "Discard this offline job registration? The local job and its queued events stay on this device, but the job will never exist on the server."
          : "Discard this queued job-finish? The job will remain unfinished on the server.";
    if (!window.confirm(what)) return;
    setBusy(true);
    try {
      await discardQueuedItem(item.queue, item.itemId);
      await load();
      onChanged();
      notify("Queue entry discarded. The diagnostic record was removed with it.", "info");
    } catch (e) { notify(e instanceof Error ? e.message : "Discard failed", "error"); }
    finally { setBusy(false); }
  }

  return (
    <div className="card">
      <h2><Icon name="schedule" size={20} /> Sync status</h2>
      <p>
        {pending} event(s) pending synchronization · {queues.regs} job registration(s) · {queues.photos} photo(s) · {queues.finishes} finish(es) queued.
        Events are only marked synced after the server acknowledges them.
      </p>
      <p className="muted small-text">Last successful synchronization: <span className="num">{fmtTime(lastOk)}</span></p>
      <div className="row">
        <button className="btn" onClick={onSync} disabled={syncing}><Icon name="sync" size={18} /> {syncing ? "Syncing…" : "Retry synchronization"}</button>
        <button className="btn secondary" onClick={() => void (async () => { await load(); onChanged(); })()}><Icon name="flag" size={17} /> Refresh status</button>
      </div>
      {items.length === 0 ? (
        <div className="empty" style={{ padding: "16px 8px 4px" }}>No items need attention. Everything queued will sync automatically.</div>
      ) : (
        <div style={{ marginTop: 10 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{items.length} item{items.length === 1 ? "" : "s"} need{items.length === 1 ? "s" : ""} attention</strong>
          </div>
          {items.map((it) => (
            <div key={it.id} className="list-row">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{QUEUE_LABEL[it.queue] || it.queue}</strong>{" "}
                  <span className={`badge ${it.recoverable ? "warn" : "crit"}`}>{it.recoverable ? "Recoverable" : "Needs decision"}</span>
                  <div className="muted small-text">{it.op} · {it.error}</div>
                  <div className="muted small-text num">Attempts: {it.attempts} · first {fmtTime(it.firstFailedAt)} · last {fmtTime(it.lastAttemptAt)}{it.status ? ` · HTTP ${it.status}` : ""}</div>
                </div>
                <span className="row">
                  <button className="btn small secondary" aria-expanded={openId === it.id} onClick={() => setOpenId(openId === it.id ? null : it.id)}>{openId === it.id ? "Hide details" : "View details"}</button>
                </span>
              </div>
              {openId === it.id && (
                <div className="panel" style={{ marginTop: 8 }}>
                  <p className="small-text" style={{ margin: "0 0 4px" }}><strong>What happened:</strong> {it.error}</p>
                  <p className="small-text" style={{ margin: "0 0 4px" }}><strong>Classification:</strong> {it.classification}{it.status ? ` (HTTP ${it.status})` : ""}</p>
                  {it.jobId && <p className="small-text num" style={{ margin: "0 0 4px" }}><strong>Job:</strong> {it.jobId}</p>}
                  <p className="small-text" style={{ margin: "0 0 8px" }}><strong>Next action:</strong> {it.action}</p>
                  <div className="row">
                    <button className="btn small" onClick={onSync} disabled={syncing || busy}>Retry now</button>
                    {!it.recoverable && <button className="btn small danger" onClick={() => void discard(it)} disabled={busy}>Discard queue entry</button>}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
