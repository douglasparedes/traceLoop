// Persistent Tutorial Library: the tutorial collection lives here,
// independent of the recording phase. Stays visible while a tutorial is
// open in Studio (the Studio is a separate view, not a replacement).
import { useCallback, useEffect, useState } from "react";
import { API, authHeaders, getIdentity } from "./api";
import { Icon } from "./icons";

interface ImpactData {
  title: string; status: string; snapshots: number; content_revisions: number;
  video_guides: number; visual_assets: number; processing_events: number;
  tutorial_evidence_items: number; draft_procedure_id?: string | null;
  draft_version_id?: string | null;
}

export interface LibraryItem {
  id: string;
  title: string;
  status: string;
  progress?: number;
  access_token: string;
  actor: string;
  duration_sec: number;
  created_at: string;
  draft_version_id?: string | null;
  objects_total: number;
  objects_unresolved: number;
  has_guide: boolean;
  input_mode?: string;
  analysis_strategy?: string;
  origin?: string;
}

function fmtDur(sec: number): string {
  if (!sec || sec <= 0) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function statusBadge(status: string) {
  if (status === "done") return <span className="badge ok"><Icon name="check" size={13} /> Ready</span>;
  if (status === "error") return <span className="badge crit">Failed</span>;
  if (status === "archived") return <span className="badge neutral">Archived</span>;
  return <span className="badge info"><span className="spinner" aria-hidden="true" style={{ width: 12, height: 12, borderWidth: 2 }} /> {status}</span>;
}

export default function TutorialLibrary({ onOpen, refreshKey }: {
  onOpen: (t: LibraryItem) => void;
  refreshKey?: number;
}) {
  const PAGE = 20;
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<"recent" | "title">("recent");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [impact, setImpact] = useState<{ item: LibraryItem; data: ImpactData } | null>(null);
  const role = getIdentity().role;
  const canManage = role === "reviewer" || role === "admin" || role === "expert";

  const load = useCallback(async (opts?: { append?: boolean }) => {
    const append = !!opts?.append;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError("");
    try {
      const idn = getIdentity();
      const offset = append ? items.length : 0;
      const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      if (q.trim()) params.set("q", q.trim());
      if (status) params.set("status", status);
      if (status === "archived") params.set("include_archived", "true");
      const res = await fetch(`${API}/api/tutorial?${params}`, { headers: authHeaders({ "X-User": idn.user, "X-Role": idn.role }) });
      if (!res.ok) throw new Error(`Library unavailable (${res.status})`);
      const body = await res.json();
      const list: LibraryItem[] = Array.isArray(body) ? body : body.items || [];
      const nextTotal = Array.isArray(body) ? list.length : body.total ?? list.length;
      setTotal(nextTotal);
      setItems((prev) => {
        if (!append) return list;
        const seen = new Set(prev.map((t) => t.id));
        return [...prev, ...list.filter((t) => !seen.has(t.id))];
      });
    } catch (e) {
      setError(e instanceof Error ? `Tutorial library unavailable (${e.message}). Check the connection and retry.` : "Tutorial library unavailable.");
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  }, [q, status, items.length]);

  useEffect(() => { void load(); }, [q, status, refreshKey]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [refreshKey]);

  async function archive(item: LibraryItem) {
    if (!window.confirm(`Remove “${item.title}” from the active library? It stays restorable under Archived.`)) return;
    setBusy(item.id);
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${item.id}/archive`, {
        method: "POST",
        headers: authHeaders({ "X-Tutorial-Token": item.access_token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Remove failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Remove failed");
    } finally {
      setBusy(null);
    }
  }

  async function restore(item: LibraryItem) {
    setBusy(item.id);
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${item.id}/unarchive`, {
        method: "POST",
        headers: authHeaders({ "X-Tutorial-Token": item.access_token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Restore failed (${res.status})`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Restore failed");
    } finally {
      setBusy(null);
    }
  }

  async function askDelete(item: LibraryItem) {
    setBusy(item.id);
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${item.id}/deletion-impact`, {
        headers: authHeaders({ "X-Tutorial-Token": item.access_token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Cannot inspect dependencies (${res.status})`);
      setImpact({ item, data: await res.json() });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete inspection failed");
    } finally {
      setBusy(null);
    }
  }

  async function confirmDelete() {
    if (!impact) return;
    const { item } = impact;
    setBusy(item.id);
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${item.id}`, {
        method: "DELETE",
        headers: authHeaders({ "X-Tutorial-Token": item.access_token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Delete failed (${res.status}): ${(await res.text()).slice(0, 300)}`);
      const body = await res.json();
      setImpact(null);
      await load();
      if (body?.storage_warning) setError(`Deleted, but storage cleanup was incomplete: ${body.storage_warning}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(null);
    }
  }

  // Server returns newest-first; title sort applies to the loaded page.
  const visible = [...items]
    .sort((a, b) => (sort === "title" ? a.title.localeCompare(b.title) : (b.created_at || "").localeCompare(a.created_at || "")));

  return (
    <section aria-label="Tutorial library">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "end" }}>
        <div>
          <h3 style={{ margin: 0 }}>Library</h3>
          <p className="muted small-text" style={{ margin: "2px 0 0" }}>
            {total} tutorial{total === 1 ? "" : "s"} · recordings, guides, and video versions are kept per tutorial
          </p>
        </div>
        <button className="btn small secondary icon-only" aria-label={sort === "recent" ? "Sorted by most recent. Activate to sort by title." : "Sorted by title. Activate to sort by most recent."} onClick={() => setSort(sort === "recent" ? "title" : "recent")}>
          <Icon name="sort" size={18} /> {sort === "recent" ? "Recent" : "Title"}
        </button>
      </div>
      <div className="panel" style={{ display: "flex", alignItems: "center", gap: 8, margin: "10px 0" }}>
        <Icon name="search" size={20} />
        <label htmlFor="tutlib-search" className="visually-hidden">Search tutorials</label>
        <input id="tutlib-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search tutorials…" style={{ border: 0, background: "transparent", minHeight: 40, padding: "6px 0" }} />
        {q && <button className="btn small secondary icon-only" aria-label="Clear search" onClick={() => setQ("")}><Icon name="close" size={17} /></button>}
      </div>
      <div className="filter-tabs" role="group" aria-label="Status filter" style={{ marginBottom: 10 }}>
        {([["", "All"], ["done", "Ready"], ["processing", "Processing"], ["error", "Failed"], ["archived", "Archived"]] as const).map(([v, label]) => (
          <button key={v} className="filter-tab" aria-pressed={status === v} onClick={() => setStatus(v)}>{label}</button>
        ))}
        <button className="btn small secondary" onClick={() => void load()} disabled={loading} style={{ marginLeft: "auto" }}>
          <Icon name="sync" size={16} /> {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}
      {loading && items.length === 0 && (
        <div className="card" aria-label="Loading tutorials"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
      )}
      {!loading && visible.length === 0 && (
        <div className="card"><div className="empty">
          <p><strong>No tutorials match</strong></p>
          <p>{items.length === 0 ? "Record your first tutorial above — it will appear here once uploaded." : "Try a different search or status filter."}</p>
          {(q || status) && <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => { setQ(""); setStatus(""); }}>Clear filters</button>}
        </div></div>
      )}
      <ul className="tut-list">
        {visible.map((t) => (
          <li key={t.id} className="tut-row">
            <button className="tut-row-main" onClick={() => onOpen(t)} aria-label={`Open ${t.title} in Tutorial Studio`}>
              <span className="tut-row-title">{t.title || "Untitled tutorial"}</span>
              <span className="muted small-text num">
                {fmtDur(t.duration_sec)} · {t.created_at ? new Date(t.created_at).toLocaleDateString() : "—"}
                {t.has_guide ? " · guide" : ""}{t.draft_version_id ? " · draft linked" : ""}
              </span>
            </button>
            <span className="tut-row-meta">
              {statusBadge(t.status)}
              {t.objects_unresolved > 0 && <span className="tag warn">{t.objects_unresolved} need tap</span>}
              {t.analysis_strategy === "visual_first" && <span className="tag ai" title="Understood from visual evidence; narration was absent or insufficient">visual-first</span>}
              {t.origin === "uploaded" && <span className="tag" title="Created from an uploaded file rather than a fresh recording">upload</span>}
            </span>
            <span className="tut-row-actions">
              <button className="btn small" onClick={() => onOpen(t)}>Open</button>
              {canManage && t.status === "archived" && (
                <button className="btn small secondary" onClick={() => void restore(t)} disabled={busy === t.id}>Restore</button>
              )}
              {canManage && t.status !== "archived" && (
                <button className="btn small secondary" onClick={() => void archive(t)} disabled={busy === t.id}>Remove</button>
              )}
              {canManage && (
                <button className="btn small secondary danger-ghost" onClick={() => void askDelete(t)} disabled={busy === t.id} aria-label={`Delete ${t.title} permanently`}>
                  {busy === t.id ? "…" : <Icon name="trash" size={16} />}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {items.length < total && (
        <button className="btn small secondary" style={{ marginTop: 10 }} onClick={() => void load({ append: true })} disabled={loadingMore}>
          {loadingMore ? "Loading…" : `Load more (${total - items.length} remaining)`}
        </button>
      )}
      {impact && (
        <div className="scrim" onClick={(e) => { if (e.target === e.currentTarget) setImpact(null); }}>
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Confirm permanent deletion">
            <h3>Permanently delete “{impact.item.title}”?</h3>
            <p className="muted">This removes the tutorial from every library view and deletes its stored media. Approved procedures and completed execution history are preserved.</p>
            <ul className="small-text">
              <li>Source recording, transcript, {impact.data.snapshots} guide snapshot(s), {impact.data.content_revisions} content revision(s)</li>
              <li>{impact.data.visual_assets} visual asset(s), {impact.data.video_guides} video guide(s), {impact.data.processing_events} processing event(s), {impact.data.tutorial_evidence_items} tutorial evidence file(s)</li>
              {impact.data.draft_version_id && <li>Linked review draft {impact.data.draft_version_id.slice(0, 8)}… is kept (approved knowledge is immutable)</li>}
            </ul>
            <p className="notice warn">Cannot be undone. Removing from the library (Archive) is reversible — deletion is not.</p>
            <div className="row">
              <button className="btn secondary" style={{ flex: 1 }} onClick={() => setImpact(null)}>Cancel</button>
              <button className="btn danger" style={{ flex: 1 }} onClick={() => void confirmDelete()} disabled={busy === impact.item.id}>Delete permanently</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
