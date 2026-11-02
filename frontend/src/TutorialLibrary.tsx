// Persistent Tutorial Library: the tutorial collection lives here,
// independent of the recording phase. Stays visible while a tutorial is
// open in Studio (the Studio is a separate view, not a replacement).
import { useCallback, useEffect, useState } from "react";
import { API, authHeaders, getIdentity } from "./api";
import { Icon } from "./icons";

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
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState<"recent" | "title">("recent");
  const [shown, setShown] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const idn = getIdentity();
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      if (q.trim()) params.set("q", q.trim());
      if (status) params.set("status", status);
      const res = await fetch(`${API}/api/tutorial?${params}`, { headers: authHeaders({ "X-User": idn.user, "X-Role": idn.role }) });
      if (!res.ok) throw new Error(`Library unavailable (${res.status})`);
      const body = await res.json();
      const list: LibraryItem[] = Array.isArray(body) ? body : body.items || [];
      setItems(list);
      setTotal(Array.isArray(body) ? list.length : body.total ?? list.length);
      setShown((n) => Math.min(Math.max(n, 20), Math.max(list.length, 20)));
    } catch (e) {
      setError(e instanceof Error ? `Tutorial library unavailable (${e.message}). Check the connection and retry.` : "Tutorial library unavailable.");
    } finally {
      setLoading(false);
    }
  }, [q, status]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  async function remove(item: LibraryItem) {
    if (!window.confirm(`Delete “${item.title}” and its videos and illustrations? This cannot be undone.`)) return;
    setDeleting(item.id);
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${item.id}`, {
        method: "DELETE",
        headers: authHeaders({ "X-Tutorial-Token": item.access_token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

  const visible = [...items]
    .sort((a, b) => (sort === "title" ? a.title.localeCompare(b.title) : (b.created_at || "").localeCompare(a.created_at || "")))
    .slice(0, shown);

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
        {([["", "All"], ["done", "Ready"], ["transcribing", "Processing"], ["error", "Failed"]] as const).map(([v, label]) => (
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
            </span>
            <span className="tut-row-actions">
              <button className="btn small" onClick={() => onOpen(t)}>Open</button>
              <button className="btn small secondary danger-ghost" onClick={() => void remove(t)} disabled={deleting === t.id} aria-label={`Delete ${t.title}`}>
                {deleting === t.id ? "…" : <Icon name="trash" size={16} />}
              </button>
            </span>
          </li>
        ))}
      </ul>
      {shown < items.length && (
        <button className="btn small secondary" style={{ marginTop: 10 }} onClick={() => setShown((n) => n + 20)}>
          Show more ({items.length - shown} remaining)
        </button>
      )}
    </section>
  );
}
