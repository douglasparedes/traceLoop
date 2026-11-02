// Compact per-stage AI processing summary for Tutorial Studio.
// Aggregated server-side from ProcessingEvents: each stage shows an explicit
// state plus its execution mode, so live and simulated work are never confused.
import { useCallback, useEffect, useState } from "react";
import { API, authHeaders, getIdentity } from "./api";

export interface StageRow {
  stage: string;
  label: string;
  state: "pending" | "running" | "completed" | "failed" | "skipped" | "needs_review";
  mode: "live" | "simulated" | "mixed" | "unknown";
  model: string;
  duration_ms: number;
  attempts: number;
  note: string;
}

const STATE_BADGE: Record<StageRow["state"], string> = {
  completed: "ok",
  failed: "crit",
  needs_review: "warn",
  running: "info",
  pending: "neutral",
  skipped: "neutral",
};

const STATE_LABEL: Record<StageRow["state"], string> = {
  completed: "Completed",
  failed: "Failed",
  needs_review: "Needs review",
  running: "Running",
  pending: "Pending",
  skipped: "Skipped",
};

export const MODE_LABEL: Record<StageRow["mode"], string> = {
  live: "Live",
  simulated: "Simulated",
  mixed: "Live + simulated",
  unknown: "Not run",
};

function fmtDur(ms: number): string {
  if (!ms || ms <= 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function ProcessingSummary({ tutorialId, token }: { tutorialId: string; token: string }) {
  const [stages, setStages] = useState<StageRow[]>([]);
  const [jobStatus, setJobStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${tutorialId}/stages`, {
        headers: authHeaders({ "X-Tutorial-Token": token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Processing summary failed (${res.status})`);
      const body = await res.json();
      setStages(body.stages || []);
      setJobStatus(body.job_status || "");
    } catch (e) {
      setError(e instanceof Error ? `Processing summary unavailable (${e.message}). Check the connection and retry.` : "Processing summary unavailable.");
    } finally {
      setLoading(false);
    }
  }, [tutorialId, token]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="card" aria-label="Loading processing summary"><div className="skeleton" /></div>;
  if (error) return <div className="card"><p className="muted small-text">{error} <button className="btn small secondary" onClick={() => void load()}>Retry</button></p></div>;

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>AI processing</h3>
        <button className="btn small secondary" onClick={() => void load()} aria-label="Refresh processing summary">Refresh</button>
      </div>
      <p className="muted small-text">
        Each stage shows what ran and how — <strong>Live</strong> means a real Meta inference call,
        <strong> Simulated</strong> means a labelled deterministic fallback.
      </p>
      <ul className="tut-list" aria-label="Processing stages">
        {stages.map((s) => (
          <li key={s.stage} className="tut-row">
            <span className="tut-row-main">
              <strong className="tut-row-title">{s.label}</strong>
              <span className="muted small-text num">{fmtDur(s.duration_ms)}{s.attempts > 1 ? ` · ${s.attempts} attempts` : ""}{s.model ? ` · ${s.model}` : ""}</span>
            </span>
            <span className="tut-row-meta">
              <span className={`badge ${STATE_BADGE[s.state]}`}>{STATE_LABEL[s.state]}</span>
              <span className={`tag ${s.mode === "live" ? "approved" : s.mode === "simulated" ? "warn" : s.mode === "mixed" ? "ai" : ""}`}>{MODE_LABEL[s.mode]}</span>
            </span>
          </li>
        ))}
      </ul>
      {stages.some((s) => s.note) && (
        <details style={{ marginTop: 8 }}>
          <summary className="small-text"><strong>Stage details</strong> — models, attempts, and notes for a technical evaluator</summary>
          {stages.filter((s) => s.note || s.model).map((s) => (
            <p key={s.stage} className="list-row small-text">
              <strong>{s.label}</strong>
              {s.model ? <> · model: <span className="num">{s.model}</span></> : null}
              {s.attempts ? <> · attempts: <span className="num">{s.attempts}</span></> : null}
              {s.note ? <><br /><span className="muted">{s.note}</span></> : null}
            </p>
          ))}
        </details>
      )}
      {jobStatus === "error" && <p className="notice error" role="alert" style={{ marginBottom: 0 }}>Processing failed — completed stages are preserved. Fix the cause and retry from Tutorials.</p>}
    </div>
  );
}
