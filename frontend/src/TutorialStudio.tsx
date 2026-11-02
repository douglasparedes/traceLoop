// Tutorial Studio: the editing workspace for one recorded tutorial and
// everything generated from it. Five focused tabs, one save model:
// every mutation is explicit, validated server-side, and revision-checked.
import { useCallback, useEffect, useRef, useState } from "react";
import { API, api, authHeaders, getIdentity } from "./api";
import { Icon } from "./icons";
import GuideFormatSelector from "./GuideFormatSelector";
import VisualStudio from "./VisualStudio";
import VideoStudio from "./VideoStudio";
import type { GuideSnapshotItem, VisualAsset } from "./guideFormats";
import { acceptVisual, fetchSnapshot, fetchSnapshots, fetchVisuals, generateGuideVersion, rejectVisual, visualFileUrl } from "./guideFormats";
import type { StudioContent, StudioSegment, StudioStep } from "./studioApi";
import { fetchContentRevisions, fetchStudioContent, restoreContentRevision, saveStudioContent, updateTutorialMeta } from "./studioApi";
import type { LibraryItem } from "./TutorialLibrary";
import { statusBadge } from "./TutorialLibrary";
import type { Version } from "./types";

interface TutObject {
  obj_id: number;
  label: string;
  status: string;
  illustration?: string;
  overlay?: string;
  diagnostic_frame?: string | null;
  first_mentioned_at?: number;
}

interface TutDetail extends LibraryItem {
  progress: number;
  error?: string;
  full_transcript: string;
  transcript_original: string;
  transcript_corrected: string;
  equipment_name: string;
  task_description: string;
  context_notes: string;
  content_revision: number;
  timed_segments: StudioSegment[];
  objects: TutObject[];
  steps: StudioStep[];
  materials: string[];
  guide_markdown: string;
  guide_format?: string;
  format_source?: string;
  format_rationale?: string;
  video_url: string;
  created_at: string;
  updated_at: string;
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "content", label: "Content" },
  { id: "guide", label: "Guide" },
  { id: "video", label: "Video" },
  { id: "visuals", label: "Visuals" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function TutorialStudio({ item, onBack, onOpenReview, notify }: {
  item: LibraryItem;
  onBack: () => void;
  onOpenReview: (versionId: string) => void;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
}) {
  const [tab, setTab] = useState<TabId>("overview");
  const [detail, setDetail] = useState<TutDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const idn = getIdentity();
      const res = await fetch(`${API}/api/tutorial/${item.id}`, {
        headers: authHeaders({ "X-Tutorial-Token": item.access_token, "X-User": idn.user, "X-Role": idn.role }),
      });
      if (!res.ok) throw new Error(`Tutorial unavailable (${res.status})`);
      setDetail(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tutorial unavailable");
    } finally {
      setLoading(false);
    }
  }, [item.id, item.access_token]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  function switchTab(t: TabId) {
    if (dirty && tab !== t && !window.confirm("You have unsaved changes in this tab. Switch anyway and lose them?")) return;
    setDirty(false);
    setTab(t);
  }

  if (loading && !detail) {
    return (
      <div>
        <button className="btn small secondary" onClick={onBack}><Icon name="back" size={17} /> Library</button>
        <div className="card" aria-label="Loading tutorial"><div className="skeleton" /><div className="skeleton" /></div>
      </div>
    );
  }
  if (error || !detail) {
    return (
      <div>
        <button className="btn small secondary" onClick={onBack}><Icon name="back" size={17} /> Library</button>
        <div className="notice error" role="alert">{error || "Tutorial unavailable."} <button className="btn small secondary" onClick={() => void load()}>Retry</button></div>
      </div>
    );
  }

  return (
    <div>
      <button className="btn small secondary" onClick={() => {
        if (dirty && !window.confirm("You have unsaved changes. Leave Studio and lose them?")) return;
        onBack();
      }}><Icon name="back" size={17} /> Library</button>
      <div className="studio-header">
        <div style={{ minWidth: 0 }}>
          <h2 className="studio-title">{detail.title || "Untitled tutorial"}</h2>
          <p className="muted small-text" style={{ margin: 0 }}>
            Tutorial Studio · rev {detail.content_revision}
            {dirty ? <span className="tag warn" style={{ marginLeft: 8 }}>unsaved changes</span> : <span className="tag approved" style={{ marginLeft: 8 }}>saved</span>}
          </p>
        </div>
        <span className="studio-status">{statusBadge(detail.status)}{detail.guide_format ? <span className="tag ai" style={{ marginLeft: 6 }}>{detail.guide_format.replace(/_/g, " ")}</span> : null}</span>
      </div>
      <div className="studio-tabs" role="tablist" aria-label="Tutorial Studio sections">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className="studio-tab" onClick={() => switchTab(t.id)}>{t.label}</button>
        ))}
      </div>
      {tab === "overview" && <OverviewEditor detail={detail} onSaved={(d) => { setDetail(d); setDirty(false); }} onDirty={() => setDirty(true)} notify={notify} onOpenReview={onOpenReview} />}
      {tab === "content" && <ContentEditor detail={detail} onSaved={(d) => { setDetail({ ...detail, ...d }); setDirty(false); void load(); }} onDirty={() => setDirty(true)} notify={notify} />}
      {tab === "guide" && <GuideEditor detail={detail} onChanged={() => void load()} onOpenReview={onOpenReview} notify={notify} />}
      {tab === "video" && <VideoStudio tutorialId={detail.id} token={item.access_token} durationSec={detail.duration_sec} jobDone={detail.status === "done"}
        visuals={(detail.objects || []).flatMap((o) => [
          ...(o.overlay ? [{ name: o.overlay, label: `${o.label} — overlay` }] : []),
          ...(o.illustration ? [{ name: o.illustration, label: `${o.label} — cutout` }] : []),
        ])}
        onChanged={() => void load()} />}
      {tab === "visuals" && <VisualsEditor detail={detail} token={item.access_token} notify={notify} />}
    </div>
  );
}

/* ---------------- Overview ---------------- */

function OverviewEditor({ detail, onSaved, onDirty, notify, onOpenReview }: {
  detail: TutDetail;
  onSaved: (d: TutDetail) => void;
  onDirty: () => void;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
  onOpenReview: (versionId: string) => void;
}) {
  const [title, setTitle] = useState(detail.title);
  const [equipment, setEquipment] = useState(detail.equipment_name || "");
  const [task, setTask] = useState(detail.task_description || "");
  const [notes, setNotes] = useState(detail.context_notes || "");
  const [state, setState] = useState<"clean" | "dirty" | "saving" | "error">("clean");
  const [error, setError] = useState("");
  const pristine = useRef(JSON.stringify([detail.title, detail.equipment_name, detail.task_description, detail.context_notes]));

  useEffect(() => {
    const cur = JSON.stringify([title, equipment, task, notes]);
    const isDirty = cur !== pristine.current;
    setState((s) => (s === "saving" ? s : isDirty ? "dirty" : "clean"));
    if (isDirty) onDirty();
  }, [title, equipment, task, notes, onDirty]);

  async function save() {
    if (!title.trim()) { setError("Title cannot be empty."); setState("error"); return; }
    setState("saving");
    setError("");
    try {
      const d = await updateTutorialMeta(detail.id, detail.access_token, {
        title: title.trim(), equipment_name: equipment, task_description: task, context_notes: notes,
      });
      notify("Tutorial overview saved. The original recording is untouched.", "ok");
      onSaved({ ...(detail as object), ...(d as object) } as TutDetail);
      pristine.current = JSON.stringify([title.trim(), equipment, task, notes]);
      setState("clean");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      setState("error");
    }
  }

  return (
    <div className="studio-grid">
      <div className="card" style={{ margin: 0 }}>
        <h3 style={{ marginTop: 0 }}>Tutorial details</h3>
        <label htmlFor="st-title">Title<input id="st-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="e.g. Reseat the pump seal" /></label>
        <label htmlFor="st-equip">Equipment or asset<input id="st-equip" value={equipment} onChange={(e) => setEquipment(e.target.value)} maxLength={200} placeholder="e.g. Pump P-104" /></label>
        <label htmlFor="st-task">Task description<textarea id="st-task" rows={2} value={task} onChange={(e) => setTask(e.target.value)} maxLength={4000} placeholder="What does this tutorial teach?" /></label>
        <label htmlFor="st-notes">Context notes<textarea id="st-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={8000} placeholder="Shift, site, or variant notes for reviewers." /></label>
        {error && <div className="notice error" role="alert">{error}</div>}
        <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
          <button className="btn" onClick={() => void save()} disabled={state === "saving" || state === "clean"}>
            {state === "saving" ? "Saving…" : "Save overview"}
          </button>
          <span className="muted small-text" role="status">
            {state === "clean" ? "Saved" : state === "dirty" ? "Unsaved changes" : state === "saving" ? "Saving…" : "Save failed — retry"}
          </span>
        </div>
      </div>
      <div>
        <div className="card" style={{ marginTop: 0 }}>
          <h3 style={{ marginTop: 0 }}>Source recording</h3>
          <video className="live-video" src={`${API}${detail.video_url}?token=${encodeURIComponent(detail.access_token)}`} controls playsInline preload="metadata" aria-label="Original tutorial recording (immutable)" />
          <p className="muted small-text num" style={{ marginBottom: 0 }}>
            Original video · immutable · {detail.duration_sec ? `${Math.round(detail.duration_sec)}s` : "duration unknown"}
            {detail.created_at ? ` · recorded ${new Date(detail.created_at).toLocaleString()}` : ""}
          </p>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Processing state</h3>
          <p style={{ margin: "0 0 6px" }}>{statusBadge(detail.status)} <span className="muted small-text num">{detail.progress}%</span></p>
          {detail.error ? <p className="notice error" role="alert" style={{ marginBottom: 0 }}>{detail.error}</p> : null}
          <p className="muted small-text" style={{ marginBottom: 0 }}>
            Guide: {detail.guide_format ? detail.guide_format.replace(/_/g, " ") : "not generated yet"}
            {detail.format_rationale ? ` — ${detail.format_rationale}` : ""}
          </p>
          {detail.draft_version_id ? (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn small" onClick={() => onOpenReview(detail.draft_version_id!)}>Open linked Review draft</button>
            </div>
          ) : (
            <p className="muted small-text" style={{ marginBottom: 0 }}>No Review draft linked yet — generate one from the Guide tab.</p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------------- Content ---------------- */

const blankStep = (n: number): StudioStep => ({
  step_number: n, title: "", summary: "", start: 0, end: 0,
  objects_used: [], expected_result: "", verification_notes: "", required_tools: [],
});

function ContentEditor({ detail, onSaved, onDirty, notify }: {
  detail: TutDetail;
  onSaved: (d: Partial<TutDetail>) => void;
  onDirty: () => void;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
}) {
  const token = detail.access_token;
  const [content, setContent] = useState<StudioContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [corrected, setCorrected] = useState("");
  const [segments, setSegments] = useState<StudioSegment[]>([]);
  const [steps, setSteps] = useState<StudioStep[]>([]);
  const [materials, setMaterials] = useState("");
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState<"none" | "transcript" | "steps" | "restore">("none");
  const [revList, setRevList] = useState<{ id: string; revision_number: number; steps: number; transcript_chars: number; actor: string; note: string; created_at: string }[]>([]);
  const [baseline, setBaseline] = useState("");

  const snapshot = useCallback((c: StudioContent, st: StudioStep[]) =>
    JSON.stringify([c.transcript_corrected, c.timed_segments, st, c.materials]), []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const c = await fetchStudioContent(detail.id, token);
      setContent(c);
      setCorrected(c.transcript_corrected || "");
      setSegments(c.timed_segments || []);
      const st = (c.steps || []).map((s, i) => ({ ...s, step_number: i + 1 }));
      setSteps(st.length ? st : [blankStep(1)]);
      setMaterials((c.materials || []).join(", "));
      setSel(0);
      setBaseline(snapshot(c, st.length ? st : [blankStep(1)]));
      const revs = await fetchContentRevisions(detail.id, token);
      setRevList(revs.revisions || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Content unavailable");
    } finally {
      setLoading(false);
    }
  }, [detail.id, token, snapshot]);

  useEffect(() => { void load(); }, [load]);

  const isDirty = !!content && JSON.stringify([corrected, segments, steps, materials.split(",").map((m) => m.trim()).filter(Boolean)]) !==
    JSON.stringify([content.transcript_corrected, content.timed_segments, content.steps, content.materials]);
  void baseline;

  useEffect(() => { if (isDirty) onDirty(); }, [isDirty, onDirty]);

  async function saveTranscript() {
    if (!content) return;
    setBusy("transcript");
    try {
      const r = await saveStudioContent(detail.id, token, {
        transcript_corrected: corrected, timed_segments: segments, expected_revision: content.content_revision,
      });
      notify("Transcript corrections saved as a new content revision. Original transcription preserved.", "ok");
      await load();
      onSaved({});
      void r;
    } catch (e) {
      notify(e instanceof Error ? e.message : "Transcript save failed", "error");
    } finally {
      setBusy("none");
    }
  }

  async function saveSteps() {
    if (!content) return;
    for (let i = 0; i < steps.length; i++) {
      if (!steps[i].title.trim()) { notify(`Step ${i + 1} needs a title before saving.`, "error"); return; }
      if (!steps[i].summary.trim()) { notify(`Step ${i + 1} needs an instruction before saving.`, "error"); return; }
    }
    setBusy("steps");
    try {
      await saveStudioContent(detail.id, token, {
        steps: steps.map((s, i) => ({ ...s, step_number: i + 1 })),
        materials: materials.split(",").map((m) => m.trim()).filter(Boolean),
        expected_revision: content.content_revision,
        note: "Step edit from Tutorial Studio",
      });
      notify("Canonical steps saved. Regenerate the guide to publish them into a new guide version.", "ok");
      await load();
      onSaved({});
    } catch (e) {
      notify(e instanceof Error ? e.message : "Step save failed", "error");
    } finally {
      setBusy("none");
    }
  }

  async function restoreOriginal() {
    if (!content) return;
    setCorrected(content.transcript_original || "");
    notify("Editing buffer restored to the original transcription. Save to persist.", "info");
  }

  async function restoreRevision(id: string) {
    if (!content) return;
    if (!window.confirm("Restore this revision as a new revision? Current content stays in history.")) return;
    setBusy("restore");
    try {
      await restoreContentRevision(detail.id, token, id, content.content_revision);
      notify("Revision restored as a new revision.", "ok");
      await load();
      onSaved({});
    } catch (e) {
      notify(e instanceof Error ? e.message : "Restore failed", "error");
    } finally {
      setBusy("none");
    }
  }

  function patchStep(i: number, patch: Partial<StudioStep>) {
    setSteps((cur) => cur.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  }

  if (loading) return <div className="card" aria-label="Loading content"><div className="skeleton" /><div className="skeleton" /></div>;
  if (error || !content) return <div className="notice error" role="alert">{error || "Content unavailable."} <button className="btn small secondary" onClick={() => void load()}>Retry</button></div>;

  const objects = detail.objects || [];
  const active = steps[sel];

  return (
    <div>
      <p className="muted small-text">
        Canonical content revision <strong className="num">{content.content_revision}</strong> · saves create new revisions — guides, drafts, and approvals update only when you regenerate.
      </p>
      <div className="studio-grid">
        <div className="card" style={{ margin: 0 }}>
          <h3 style={{ marginTop: 0 }}>Transcript</h3>
          <p className="muted small-text">Original AI transcription is preserved below. Correct wording here; timestamps are kept with their segments.</p>
          <label htmlFor="st-corrected">Corrected transcript<textarea id="st-corrected" rows={4} value={corrected} onChange={(e) => setCorrected(e.target.value)} placeholder={content.transcript_original || "Corrected narration text…"} /></label>
          <div className="row">
            <button className="btn small" onClick={() => void saveTranscript()} disabled={busy !== "none"}>{busy === "transcript" ? "Saving…" : "Save transcript"}</button>
            <button className="btn small secondary" onClick={() => void restoreOriginal()}>Restore original text</button>
          </div>
          <details style={{ marginTop: 10 }}>
            <summary className="small-text"><strong>Original transcription (immutable)</strong></summary>
            <p className="muted small-text" style={{ whiteSpace: "pre-wrap" }}>{content.transcript_original || "—"}</p>
          </details>
          <details style={{ marginTop: 6 }}>
            <summary className="small-text"><strong>Timed segments ({segments.length})</strong> — edit wording, timestamps stay attached</summary>
            {segments.length === 0 && <p className="muted small-text">No timed segments for this tutorial.</p>}
            {segments.map((s, i) => (
              <div key={i} className="list-row">
                <span className="muted small-text num">{Math.floor(s.start / 60)}:{String(Math.floor(s.start % 60)).padStart(2, "0")}–{Math.floor(s.end / 60)}:{String(Math.floor(s.end % 60)).padStart(2, "0")}</span>
                <label className="visually-hidden" htmlFor={`seg-${i}`}>Segment {i + 1} text</label>
                <textarea id={`seg-${i}`} rows={2} value={s.text} onChange={(e) => setSegments((cur) => cur.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
              </div>
            ))}
          </details>
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3 style={{ margin: 0 }}>Steps ({steps.length})</h3>
            <span className="row">
              <button className="btn small secondary" onClick={() => { setSteps((cur) => [...cur, blankStep(cur.length + 1)]); setSel(steps.length); }}>Add step</button>
              <button className="btn small" onClick={() => void saveSteps()} disabled={busy !== "none"}>{busy === "steps" ? "Saving…" : "Save steps"}</button>
            </span>
          </div>
          <ol className="scene-list">
            {steps.map((s, i) => (
              <li key={i}>
                <button className="scene-row" aria-pressed={sel === i} onClick={() => setSel(i)}>
                  <span className="scene-num num">{i + 1}</span>
                  <span className="scene-main"><strong>{s.title || `Untitled step ${i + 1}`}</strong>
                    <span className="muted small-text">{s.summary.slice(0, 80)}{s.summary.length > 80 ? "…" : ""}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {active && (
            <div style={{ marginTop: 10 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>Step {sel + 1}</strong>
                <span className="row">
                  <button className="btn small secondary icon-only" aria-label="Move step earlier" disabled={sel === 0} onClick={() => {
                    setSteps((cur) => { const n = [...cur]; [n[sel - 1], n[sel]] = [n[sel], n[sel - 1]]; return n.map((s, k) => ({ ...s, step_number: k + 1 })); });
                    setSel(sel - 1);
                  }}>↑</button>
                  <button className="btn small secondary icon-only" aria-label="Move step later" disabled={sel === steps.length - 1} onClick={() => {
                    setSteps((cur) => { const n = [...cur]; [n[sel + 1], n[sel]] = [n[sel], n[sel + 1]]; return n.map((s, k) => ({ ...s, step_number: k + 1 })); });
                    setSel(sel + 1);
                  }}>↓</button>
                  <button className="btn small secondary" onClick={() => {
                    setSteps((cur) => { const n = [...cur]; n.splice(sel + 1, 0, { ...cur[sel], step_number: sel + 2 }); return n.map((s, k) => ({ ...s, step_number: k + 1 })); });
                  }}>Duplicate</button>
                  <button className="btn small secondary danger-ghost" disabled={steps.length <= 1} onClick={() => {
                    if (!window.confirm(`Delete step ${sel + 1}?`)) return;
                    setSteps((cur) => cur.filter((_, j) => j !== sel).map((s, k) => ({ ...s, step_number: k + 1 })));
                    setSel((n) => Math.max(0, n - 1));
                  }}>Delete</button>
                </span>
              </div>
              <label>Title<input value={active.title} onChange={(e) => patchStep(sel, { title: e.target.value })} maxLength={200} placeholder="e.g. Power off the trainer" /></label>
              <label>Instruction<textarea rows={3} value={active.summary} onChange={(e) => patchStep(sel, { summary: e.target.value })} maxLength={8000} placeholder="Imperative instruction the technician follows." /></label>
              <label>Expected result<input value={active.expected_result || ""} onChange={(e) => patchStep(sel, { expected_result: e.target.value })} maxLength={2000} placeholder="What the technician should observe." /></label>
              <label>Verification notes<input value={active.verification_notes || ""} onChange={(e) => patchStep(sel, { verification_notes: e.target.value })} maxLength={2000} placeholder="How a reviewer verifies this step." /></label>
              <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <label>Source start (sec)<input type="number" min={0} step={0.5} value={active.start || 0} onChange={(e) => patchStep(sel, { start: Number(e.target.value) })} /></label>
                <label>Source end (sec)<input type="number" min={0} step={0.5} value={active.end || 0} onChange={(e) => patchStep(sel, { end: Number(e.target.value) })} /></label>
              </div>
              <label>Tools / materials (comma-separated)<input value={(active.required_tools || []).join(", ")} onChange={(e) => patchStep(sel, { required_tools: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })} placeholder="e.g. Torque driver, Lint-free cloth" /></label>
              {objects.length > 0 && (
                <fieldset style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 10, marginTop: 10 }}>
                  <legend className="small-text"><strong>Detected objects used</strong></legend>
                  {objects.map((o) => (
                    <label key={o.obj_id} className="check-row" htmlFor={`obj-${o.obj_id}-${sel}`}>
                      <input id={`obj-${o.obj_id}-${sel}`} type="checkbox" checked={(active.objects_used || []).includes(o.obj_id)}
                        onChange={(e) => patchStep(sel, { objects_used: e.target.checked ? [...(active.objects_used || []), o.obj_id] : (active.objects_used || []).filter((x) => x !== o.obj_id) })} />
                      {o.label} <span className="muted small-text">({o.status})</span>
                    </label>
                  ))}
                </fieldset>
              )}
              <label style={{ marginTop: 10 }}>Materials (comma-separated, tutorial-level)<input value={materials} onChange={(e) => setMaterials(e.target.value)} placeholder="e.g. Cable harness, Enclosure screws" /></label>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Content revisions ({revList.length})</h3>
        <p className="muted small-text">Every save is kept. Restoring creates a new revision — nothing is overwritten.</p>
        {revList.length === 0 && <p className="muted small-text">No Studio saves yet. The first save starts the history.</p>}
        {revList.map((r) => (
          <div key={r.id} className="list-row">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span><strong>Revision {r.revision_number}</strong> <span className="muted small-text">· {r.steps} steps · {r.transcript_chars} transcript chars · {r.actor} · {new Date(r.created_at).toLocaleString()}</span>
                {r.note ? <span className="muted small-text"> · {r.note}</span> : null}</span>
              <button className="btn small secondary" disabled={busy !== "none"} onClick={() => void restoreRevision(r.id)}>Restore as new</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- Guide ---------------- */

function GuideEditor({ detail, onChanged, onOpenReview, notify }: {
  detail: TutDetail;
  onChanged: () => void;
  onOpenReview: (versionId: string) => void;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
}) {
  const token = detail.access_token;
  const [snaps, setSnaps] = useState<GuideSnapshotItem[]>([]);
  const [viewId, setViewId] = useState<string | null>(null);
  const [viewMd, setViewMd] = useState("");
  const [compareId, setCompareId] = useState<string | null>(null);
  const [compareMd, setCompareMd] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);

  const loadSnaps = useCallback(async () => {
    try { setSnaps(await fetchSnapshots(detail.id, token)); } catch { /* offline keeps current */ }
  }, [detail.id, token]);

  useEffect(() => { void loadSnaps(); }, [loadSnaps]);

  const imgUrl = (name?: string) => (name ? `${API}/api/tutorial/${detail.id}/illustrations/${name}?token=${encodeURIComponent(token)}` : "");
  const resolveMdImage = (src: string) => {
    const m = /^illustrations\/(.+)$/.exec(src);
    return m ? imgUrl(m[1]) || src : src;
  };

  async function openSnap(id: string, cmp: boolean) {
    try {
      const s = await fetchSnapshot(detail.id, token, id);
      if (cmp) { setCompareId(id); setCompareMd(s.guide_markdown || ""); }
      else { setViewId(id); setViewMd(s.guide_markdown || ""); }
    } catch (e) { notify(e instanceof Error ? e.message : "Could not load that version", "error"); }
  }

  async function regenerate() {
    if (busy) return;
    setBusy(true);
    try {
      const r = await generateGuideVersion(detail.id, token);
      notify(r.duplicate ? "Identical version already exists — showing it instead of duplicating." : `New guide version generated (${r.markdown_chars} chars). Review draft ${r.draft_status}.`, "ok");
      await loadSnaps();
      onChanged();
    } catch (e) {
      notify(e instanceof Error ? e.message : "Regeneration failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function ensureDraft() {
    if (draftBusy) return;
    setDraftBusy(true);
    try {
      await api.post<{ version_id: string; created: boolean }>(`/api/tutorial/${detail.id}/draft`, {}, { "X-Tutorial-Token": token });
      notify("Review draft ready — find it in the Review queue.", "ok");
      onChanged();
    } catch (e) { notify(e instanceof Error ? e.message : "Draft creation failed", "error"); }
    finally { setDraftBusy(false); }
  }

  const unresolved = (detail.objects || []).filter((o) => o.status === "needs_tap" || o.status === "error");

  return (
    <div>
      <div className="card" style={{ marginTop: 0 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <span className="eyebrow">Guide format</span>
            <h3 style={{ margin: "2px 0" }}>
              {detail.guide_format ? ({ work_instruction: "Illustrated Work Instruction", reference_manual: "Reference Manual", interactive: "Interactive Guided Execution" } as Record<string, string>)[detail.guide_format] || detail.guide_format : "Not set yet"}
            </h3>
            {detail.format_rationale && <p className="muted small-text" style={{ margin: 0 }}>{detail.format_source === "user" ? "You selected this format. " : ""}{detail.format_rationale}</p>}
          </div>
          <span className="row">
            <button className="btn small secondary" onClick={() => setShowPicker((v) => !v)}>{showPicker ? "Close" : "Change format"}</button>
            <button className="btn small" onClick={() => void regenerate()} disabled={busy || detail.status !== "done"}>{busy ? "Working…" : "Regenerate guide"}</button>
          </span>
        </div>
        {detail.status !== "done" && <p className="muted small-text" role="status" style={{ marginBottom: 0 }}>Regeneration unlocks once processing finishes.</p>}
      </div>
      {showPicker && (
        <GuideFormatSelector tutorialId={detail.id} token={token} current={detail.guide_format || ""}
          onGenerated={() => { setShowPicker(false); void loadSnaps(); onChanged(); }}
          onChanged={() => onChanged()} />
      )}
      {unresolved.length > 0 && (
        <div className="notice warn" role="status">
          <strong>{unresolved.length} object{unresolved.length === 1 ? "" : "s"} unresolved</strong> ({unresolved.map((o) => o.label).join(", ")}).
          The guide marks them honestly; tap-correct them from the original tutorial view or accept the uncertainty before approval.
        </div>
      )}
      {detail.draft_version_id ? (
        <div className="notice ok" role="status">
          Linked Review draft is active.
          <div className="row" style={{ marginTop: 8 }}><button className="btn small" onClick={() => onOpenReview(detail.draft_version_id!)}>Open in Review</button></div>
        </div>
      ) : (
        <div className="notice warn" role="status">
          No Review draft linked yet.
          <div className="row" style={{ marginTop: 8 }}><button className="btn small" onClick={() => void ensureDraft()} disabled={draftBusy}>{draftBusy ? "Creating…" : "Send to Review as draft"}</button></div>
        </div>
      )}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Version history ({snaps.length})</h3>
        <p className="muted small-text">Every generation is kept and immutable. Content edits land here only when you regenerate.</p>
        {snaps.length === 0 && <p className="muted small-text">No guide versions yet.</p>}
        {snaps.map((s) => (
          <p key={s.id} className="list-row">
            <span className="tag">{s.trigger}</span>
            {s.guide_format && <span className="tag ai">{s.guide_format.replace(/_/g, " ")}</span>}
            {s.simulated && <span className="tag warn">simulated model</span>}
            <span className="muted small-text"> · {new Date(s.created_at).toLocaleString()} · {s.markdown_chars} chars</span>{" "}
            <button className="btn small secondary" onClick={() => void openSnap(s.id, false)}>View</button>{" "}
            <button className="btn small secondary" aria-pressed={compareId === s.id}
              onClick={() => { if (compareId === s.id) { setCompareId(null); setCompareMd(""); } else void openSnap(s.id, true); }}>
              {compareId === s.id ? "Hide compare" : "Compare"}
            </button>
          </p>
        ))}
        {viewId && (
          <div style={{ marginTop: 8 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>Selected version</strong>
              <button className="btn small secondary" onClick={() => { setViewId(null); setViewMd(""); }}>Close</button>
            </div>
            <MiniMarkdown text={viewMd} resolveImage={resolveMdImage} />
          </div>
        )}
        {compareId && (
          <div style={{ marginTop: 8 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>Comparing with current guide</strong>
              <button className="btn small secondary" onClick={() => { setCompareId(null); setCompareMd(""); }}>Close compare</button>
            </div>
            <div className="studio-grid">
              <div className="card" style={{ margin: 0 }}><h4>Selected version</h4><MiniMarkdown text={compareMd} resolveImage={resolveMdImage} /></div>
              <div className="card" style={{ margin: 0 }}><h4>Current guide</h4><MiniMarkdown text={detail.guide_markdown || ""} resolveImage={resolveMdImage} /></div>
            </div>
          </div>
        )}
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Current guide</h3>
        <MiniMarkdown text={detail.guide_markdown || "No guide generated yet."} resolveImage={resolveMdImage} />
      </div>
    </div>
  );
}

/* ---------------- Visuals ---------------- */

function VisualsEditor({ detail, token, notify }: {
  detail: TutDetail;
  token: string;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
}) {
  const [visuals, setVisuals] = useState<VisualAsset[]>([]);
  const [source, setSource] = useState<{ id: string; label: string; imageUrl: string; kind: string; source: Record<string, unknown> } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setVisuals(await fetchVisuals(detail.id, token)); } catch { /* offline */ }
  }, [detail.id, token]);

  useEffect(() => { void load(); }, [load]);

  const imgUrl = (name?: string) => (name ? `${API}/api/tutorial/${detail.id}/illustrations/${name}?token=${encodeURIComponent(token)}` : "");
  const sources = (detail.objects || []).flatMap((o) => [
    ...(o.overlay ? [{ id: `illustration:${o.overlay}`, label: `${o.label} — SAM overlay`, imageUrl: imgUrl(o.overlay), kind: "overlay", source: { kind: "illustration", name: o.overlay } }] : []),
    ...(o.illustration ? [{ id: `illustration:${o.illustration}`, label: `${o.label} — isolated cutout`, imageUrl: imgUrl(o.illustration), kind: "cutout", source: { kind: "illustration", name: o.illustration } }] : []),
    ...(!o.overlay && !o.illustration && o.diagnostic_frame ? [{ id: `diagnostic:${o.obj_id}`, label: `${o.label} — diagnostic frame`, imageUrl: `${API}/api/tutorial/${detail.id}/diagnostics/frame/${o.obj_id}?token=${encodeURIComponent(token)}`, kind: "diagnostic", source: { kind: "diagnostic", obj_id: o.obj_id } }] : []),
  ]);

  async function decide(a: VisualAsset, accept: boolean) {
    setBusy(true);
    try {
      if (accept) await acceptVisual(a.id);
      else await rejectVisual(a.id);
      notify(accept ? "Accepted. Attach it to a guide step from Review to use it in the guide." : "Rejected. Sources and prior versions are untouched.", accept ? "ok" : "info");
      await load();
    } catch (e) { notify(e instanceof Error ? e.message : "Decision failed", "error"); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Visuals</h3>
      <p className="muted small-text">
        Tutorial → step → source image → accepted asset. Sources are never modified; derivatives need acceptance.
        Accepted assets attach to guide steps from Review.
      </p>
      <div className="card">
        <h4 style={{ marginTop: 0 }}>Source images ({sources.length})</h4>
        {sources.length === 0 && <p className="muted small-text">No source images yet — they appear once segmentation produces illustrations.</p>}
        <div className="row">
          {sources.map((s) => (
            <button key={s.id} className={`btn small ${source?.id === s.id ? "" : "secondary"}`} aria-pressed={source?.id === s.id} onClick={() => setSource(s)}>
              {s.label}
            </button>
          ))}
        </div>
        {source && <p className="muted small-text" style={{ marginBottom: 0 }}>Selected: {source.label} <span className="tag">original preserved</span></p>}
      </div>
      <VisualStudio tutorialId={detail.id} token={token} sourceAsset={source}
        references={visuals.map((v) => ({ id: v.id, label: `${v.kind} — ${v.instruction.slice(0, 40) || v.id.slice(0, 8)}` }))}
        onChanged={() => void load()} />
      <div className="card">
        <h4 style={{ marginTop: 0 }}>Derivatives ({visuals.length})</h4>
        {visuals.length === 0 && <p className="muted small-text">No derivatives yet — improve, highlight, or annotate a source above.</p>}
        {visuals.map((v) => (
          <div key={v.id} className="list-row">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span><strong>{v.kind.replace(/_/g, " ")}</strong> <span className={`tag ${v.status === "accepted" ? "approved" : v.status === "rejected" ? "error" : ""}`}>{v.status}</span>
                <span className="muted small-text"> · {v.instruction.slice(0, 80)} · {new Date(v.created_at).toLocaleString()}</span></span>
              <span className="row">
                <a className="btn small secondary" href={visualFileUrl(v, token)} target="_blank" rel="noreferrer">Open</a>
                {v.status === "review" && (
                  <>
                    <button className="btn small" disabled={busy} onClick={() => void decide(v, true)}>Accept</button>
                    <button className="btn small secondary" disabled={busy} onClick={() => void decide(v, false)}>Reject</button>
                  </>
                )}
              </span>
            </div>
            {typeof (v.provenance as { warning?: unknown }).warning === "string" && (
              <p className="muted small-text" style={{ marginBottom: 0 }}>{String((v.provenance as { warning?: unknown }).warning)}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniMarkdown({ text, resolveImage }: { text: string; resolveImage: (src: string) => string }) {
  const lines = (text || "").split("\n");
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = (key: number) => {
    if (list.length) { out.push(<ul key={`l${key}`}>{list.map((li, i) => <li key={i}>{li}</li>)}</ul>); list = []; }
  };
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (/^<!--.*-->$/.test(line)) return;
    if (/^\s*[-*] /.test(line)) { list.push(line.replace(/^\s*[-*] /, "")); return; }
    flush(i);
    if (line.startsWith("### ")) out.push(<h4 key={i}>{line.slice(4)}</h4>);
    else if (line.startsWith("## ")) out.push(<h3 key={i}>{line.slice(3)}</h3>);
    else if (line.startsWith("# ")) out.push(<h2 key={i}>{line.slice(2)}</h2>);
    else if (line.trim()) {
      const m = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line.trim());
      if (m) out.push(<img key={i} src={resolveImage(m[2])} alt={m[1]} style={{ maxWidth: "100%", borderRadius: 8 }} loading="lazy" />);
      else out.push(<p key={i}>{line}</p>);
    }
  });
  flush(lines.length);
  return <div>{out}</div>;
}

export type { Version };
