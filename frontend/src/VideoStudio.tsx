// Video Studio: scene-level editing for generated video guides.
// Every render creates a NEW persistent MP4 version — prior versions stay
// available. Captions are presentation text; the voiceover is always a cut
// of the user's own original recording (never synthesized).
import { useCallback, useEffect, useState } from "react";
import type { StudioScene, StudioVideoVersion } from "./studioApi";
import { fetchVideoVersions, renderScenePlan, saveScenePlan, sceneRange, sceneStep, videoVersionFileUrl } from "./studioApi";

function fmtT(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function VideoStudio({ tutorialId, token, durationSec, visuals, jobDone, onChanged }: {
  tutorialId: string;
  token: string;
  durationSec: number;
  visuals: { name: string; label: string }[];
  jobDone: boolean;
  onChanged: () => void;
}) {
  const [versions, setVersions] = useState<StudioVideoVersion[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<StudioScene[]>([]);
  const [baseVersionId, setBaseVersionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [selScene, setSelScene] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const vers = await fetchVideoVersions(tutorialId, token);
      setVersions(vers);
      const ready = vers.filter((v) => v.status === "ready");
      const latest = ready.length ? ready[ready.length - 1] : vers.length ? vers[vers.length - 1] : null;
      if (latest) {
        setSelectedId((cur) => cur || latest.id);
        if (!dirty) {
          setScenes((latest.scenes || []).map((s, i) => ({ ...s, include: s.include !== false, step: sceneStep(s, i + 1) })));
          setBaseVersionId(latest.id);
          setSelScene(0);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Video history unavailable");
    } finally {
      setLoading(false);
    }
  }, [tutorialId, token, dirty]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!versions.length) return;
    const t = window.setInterval(async () => {
      try {
        const vers = await fetchVideoVersions(tutorialId, token);
        setVersions(vers);
        if (vers.some((v) => v.status === "queued" || v.status === "rendering")) return;
        window.clearInterval(t);
        onChanged();
      } catch { window.clearInterval(t); }
    }, 3000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versions.some((v) => v.status === "queued" || v.status === "rendering")]);

  const selected = versions.find((v) => v.id === selectedId) || null;
  const working = versions.some((v) => v.status === "queued" || v.status === "rendering") || busy;

  function patchScene(i: number, patch: Partial<StudioScene>) {
    setScenes((cur) => cur.map((s, j) => (j === i ? { ...s, ...patch } : s)));
    setDirty(true);
  }

  function moveScene(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= scenes.length) return;
    setScenes((cur) => {
      const next = [...cur];
      [next[i], next[j]] = [next[j], next[i]];
      return next.map((s, k) => ({ ...s, step: k + 1 }));
    });
    setSelScene(j);
    setDirty(true);
  }

  function addScene() {
    const lastEnd = scenes.length ? Number(scenes[scenes.length - 1].audio_end ?? scenes[scenes.length - 1].end ?? 0) || 0 : 0;
    const end = durationSec > 0 ? Math.min(durationSec, lastEnd + 5) : lastEnd + 5;
    setScenes((cur) => [...cur, {
      step: cur.length + 1, title: `New scene ${cur.length + 1}`, caption: "",
      audio_start: Math.max(0, lastEnd), audio_end: Math.max(Math.max(0, lastEnd) + 1, end),
      visual: {}, include: true,
    }]);
    setSelScene(scenes.length);
    setDirty(true);
  }

  async function savePlan() {
    if (busy) return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const r = await saveScenePlan(tutorialId, token, scenes);
      setScenes(r.scenes);
      setDirty(false);
      setBaseVersionId(r.video_guide_id);
      setNote("Scene plan saved. Render to produce a new MP4 version — nothing rendered yet.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the scene plan");
    } finally {
      setBusy(false);
    }
  }

  async function render() {
    if (busy) return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const r = await renderScenePlan(tutorialId, token, dirty ? scenes : undefined);
      setSelectedId(r.video_guide.id);
      setDirty(false);
      setBaseVersionId(r.video_guide.id);
      setNote(r.duplicate ? "This exact plan already rendered — showing the existing version." : "Render queued. This tab polls every few seconds; you can leave — the video persists.");
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the render");
    } finally {
      setBusy(false);
    }
  }

  const active = scenes[selScene];
  const readyVersions = versions.filter((v) => v.status === "ready");

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Video</h3>
      <p className="muted small-text">
        Edit the scene plan, then render a <strong>new</strong> MP4 version. Earlier versions stay available below.
        The voiceover is always cut from your original recording — changing a caption never changes the narration.
      </p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {note && <div className="notice ok" role="status">{note}</div>}
      {loading && <div className="card" aria-label="Loading video history"><div className="skeleton" /><div className="skeleton" /></div>}

      {!loading && versions.length === 0 && scenes.length === 0 && (
        <div className="card"><div className="empty">
          <p><strong>No video version yet</strong></p>
          <p>{jobDone ? "Add scenes below and render the first MP4 version." : "Video editing unlocks once the tutorial finishes processing."}</p>
          {jobDone && <button className="btn" style={{ marginTop: 8 }} onClick={addScene}>Add first scene</button>}
        </div></div>
      )}

      {(scenes.length > 0 || jobDone) && (
        <div className="studio-grid">
          <div className="card" style={{ margin: 0 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>Scenes ({scenes.length})</strong>
              <button className="btn small secondary" onClick={addScene} disabled={!jobDone}>Add scene</button>
            </div>
            {scenes.length === 0 && <p className="muted small-text">No scenes yet — add the first one to describe the opening of the recording.</p>}
            <ol className="scene-list">
              {scenes.map((s, i) => {
                const { start, end } = sceneRange(s);
                return (
                  <li key={i}>
                    <button className="scene-row" aria-pressed={selScene === i} onClick={() => setSelScene(i)}>
                      <span className="scene-num num">{i + 1}</span>
                      <span className="scene-main">
                        <strong>{s.title || `Scene ${i + 1}`}</strong>
                        <span className="muted small-text num">{fmtT(start)}–{fmtT(end)}{s.include === false ? " · excluded" : ""}</span>
                      </span>
                      {s.include === false && <span className="tag warn">out</span>}
                    </button>
                  </li>
                );
              })}
            </ol>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn" onClick={() => void savePlan()} disabled={busy || !dirty || scenes.length === 0}>
                {busy ? "Working…" : "Save scene plan"}
              </button>
              <button className="btn secondary" onClick={() => void render()} disabled={busy || scenes.length === 0 || !jobDone}>
                Render new MP4
              </button>
            </div>
            {dirty && <p className="muted small-text" role="status">Unsaved scene changes{baseVersionId ? " — based on a saved plan" : ""}.</p>}
            {!dirty && baseVersionId && <p className="muted small-text">Plan matches the saved draft. Render produces version {readyVersions.length + 1}.</p>}
          </div>

          <div className="card" style={{ margin: 0 }}>
            {active ? (
              <div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <strong>Scene {selScene + 1}</strong>
                  <span className="row">
                    <button className="btn small secondary icon-only" aria-label="Move scene earlier" disabled={selScene === 0} onClick={() => moveScene(selScene, -1)}>↑</button>
                    <button className="btn small secondary icon-only" aria-label="Move scene later" disabled={selScene === scenes.length - 1} onClick={() => moveScene(selScene, 1)}>↓</button>
                  </span>
                </div>
                <label htmlFor="vs-title">Title<input id="vs-title" value={active.title} onChange={(e) => patchScene(selScene, { title: e.target.value })} maxLength={200} /></label>
                <label htmlFor="vs-caption">On-screen caption<textarea id="vs-caption" rows={2} value={active.caption} onChange={(e) => patchScene(selScene, { caption: e.target.value })} maxLength={2000} placeholder="Short caption shown on the step card. Does not change the spoken narration." /></label>
                <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <label htmlFor="vs-start">Audio in-point (sec)<input id="vs-start" type="number" min={0} max={durationSec || undefined} step={0.5} value={Number(active.audio_start ?? active.start ?? 0)} onChange={(e) => patchScene(selScene, { audio_start: Number(e.target.value) })} /></label>
                  <label htmlFor="vs-end">Audio out-point (sec)<input id="vs-end" type="number" min={0} max={durationSec || undefined} step={0.5} value={Number(active.audio_end ?? active.end ?? 0)} onChange={(e) => patchScene(selScene, { audio_end: Number(e.target.value) })} /></label>
                </div>
                <p className="muted small-text num">Source recording: {fmtT(durationSec || 0)} total. Ranges must stay inside it and end after they start.</p>
                <label htmlFor="vs-visual">Scene image
                  <select id="vs-visual" value={(active.visual || {}).name || ""} onChange={(e) => patchScene(selScene, { visual: e.target.value ? { name: e.target.value } : {} })}>
                    <option value="">Title-only scene (no image)</option>
                    {visuals.map((v) => <option key={v.name} value={v.name}>{v.label}</option>)}
                  </select>
                </label>
                <label className="check-row" htmlFor="vs-include">
                  <input id="vs-include" type="checkbox" checked={active.include !== false} onChange={(e) => patchScene(selScene, { include: e.target.checked })} />
                  Include this scene in the render
                </label>
                <button className="btn small secondary danger-ghost" onClick={() => {
                  setScenes((cur) => cur.filter((_, j) => j !== selScene).map((s, k) => ({ ...s, step: k + 1 })));
                  setSelScene((n) => Math.max(0, n - 1));
                  setDirty(true);
                }}>Remove scene</button>
              </div>
            ) : (
              <div className="empty">Select a scene to edit it.</div>
            )}
          </div>
        </div>
      )}

      {versions.length > 0 && (
        <div className="card">
          <h4 style={{ marginTop: 0 }}>Versions ({versions.length})</h4>
          {working && <p className="muted small-text" role="status"><span className="spinner" aria-hidden="true" /> A render is in progress — this list refreshes automatically.</p>}
          {versions.map((v) => (
            <div key={v.id} className="list-row">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>Version {v.version_number || "—"}</strong>{" "}
                  <span className={`tag ${v.status === "ready" ? "approved" : v.status === "error" ? "error" : ""}`}>{v.status}</span>
                  {v.simulated && <span className="tag warn">simulated plan</span>}
                  <span className="muted small-text"> · {new Date(v.created_at).toLocaleString()} · {(v.scenes || []).length} scenes</span>
                </div>
                <span className="row">
                  <button className="btn small secondary" aria-pressed={selectedId === v.id} onClick={() => setSelectedId(v.id)}>Preview</button>
                  {v.status === "ready" && (
                    <a className="btn small secondary" href={videoVersionFileUrl(tutorialId, v.id, token)} download={`tutorial-guide-v${v.version_number || ""}.mp4`}>Download</a>
                  )}
                </span>
              </div>
              {v.status === "error" && v.error && <p className="notice error" role="alert" style={{ marginBottom: 0 }}>Render failed: {v.error}</p>}
            </div>
          ))}
          {selected?.status === "ready" && (
            <div style={{ marginTop: 10 }}>
              <video key={selected.id} className="live-video" src={videoVersionFileUrl(tutorialId, selected.id, token)} controls playsInline preload="metadata" aria-label={`Video guide version ${selected.version_number}`} />
              <p className="muted small-text" style={{ marginTop: 6 }}>
                {(selected.scenes || []).length} scenes · original-voice cut · reproducible from its saved scene plan.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
