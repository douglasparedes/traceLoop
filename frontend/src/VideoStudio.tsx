// Video Studio: one-click automatic video guide generation.
//
// One action — "Generate video guide". The server composes the video from
// the current guide (Muse Spark composition, deterministic fallback
// offline), cuts the voiceover from the user's own recording (silent
// tutorials render as captioned videos), renders with Remotion, validates
// the MP4, and persists it as a new immutable version. There is no scene
// editor here: scenes stay internal to the render pipeline (backend
// provenance + diagnostics), and every render creates a new version —
// prior MP4s are never overwritten.
import { useCallback, useEffect, useState } from "react";
import type { StudioVideoVersion } from "./studioApi";
import { fetchVideoLimits, fetchVideoVersions, startVideoGuide, videoVersionFileUrl } from "./studioApi";
import { fetchVisuals } from "./guideFormats";

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued — waiting for a render worker",
  rendering: "Rendering — composing scenes and cutting voiceover",
  validating: "Validating — checking the rendered MP4",
};

const FORMAT_NAMES: Record<string, string> = {
  work_instruction: "Illustrated Work Instruction",
  reference_manual: "Reference Manual",
  interactive: "Interactive Guided Execution",
};

function fmtClock(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function voiceLabel(v: StudioVideoVersion): string {
  return v.provenance?.voiceover === "silent-captions-only"
    ? "silent captioned video (no narration track)"
    : "original-voice cut";
}

export default function VideoStudio({ tutorialId, token, title, durationSec, jobDone, guide, onChanged }: {
  tutorialId: string;
  token: string;
  title: string;
  durationSec: number;
  jobDone: boolean;
  guide: { format: string; steps: number; hasTranscript: boolean; contentRevision: number };
  onChanged: () => void;
}) {
  const [versions, setVersions] = useState<StudioVideoVersion[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [acceptedCount, setAcceptedCount] = useState(0);
  const [maxGuideSec, setMaxGuideSec] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (selectLatest = false) => {
    setError("");
    try {
      const [vers, visuals, limits] = await Promise.all([
        fetchVideoVersions(tutorialId, token),
        fetchVisuals(tutorialId, token).catch(() => []),
        fetchVideoLimits(tutorialId, token).catch(() => null),
      ]);
      setVersions(vers);
      setAcceptedCount(visuals.filter((v) => v.status === "accepted").length);
      if (limits) setMaxGuideSec(limits.max_video_guide_sec);
      const ready = vers.filter((v) => v.status === "ready");
      const latest = ready.length ? ready[ready.length - 1] : vers.length ? vers[vers.length - 1] : null;
      if (latest && (selectLatest || !selectedId)) setSelectedId(latest.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Video history unavailable");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tutorialId, token]);

  useEffect(() => { void load(); }, [load]);

  const working = versions.some((v) => v.status === "queued" || v.status === "rendering" || v.status === "validating");

  useEffect(() => {
    if (!working) return;
    const t = window.setInterval(async () => {
      try {
        const vers = await fetchVideoVersions(tutorialId, token);
        setVersions(vers);
        if (!vers.some((v) => v.status === "queued" || v.status === "rendering" || v.status === "validating")) {
          window.clearInterval(t);
          setSelectedId((cur) => {
            if (cur) return cur;
            const ready = vers.filter((v) => v.status === "ready");
            return (ready.length ? ready[ready.length - 1] : vers[vers.length - 1])?.id || null;
          });
          onChanged();
        }
      } catch { window.clearInterval(t); }
    }, 3000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [working, tutorialId, token]);

  async function generate(regenerate = false) {
    if (busy || !jobDone) return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const r = await startVideoGuide(tutorialId, token, regenerate);
      setSelectedId(r.video_guide.id);
      setNote(r.duplicate
        ? "This exact guide revision already has a video — showing the existing version instead of rendering a duplicate."
        : "Render started. This tab polls every few seconds; you can leave — the video persists.");
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start video generation");
    } finally {
      setBusy(false);
    }
  }

  const selected = versions.find((v) => v.id === selectedId) || null;
  const readyVersions = versions.filter((v) => v.status === "ready");
  const overLimit = maxGuideSec != null && durationSec > maxGuideSec;

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Video</h3>
      <p className="muted small-text">
        One action: <strong>Generate video guide</strong>. The video is composed from your current guide,
        narrated with your original recording (silent tutorials render caption-led), and every render
        creates a new immutable version.
      </p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {note && <div className="notice ok" role="status">{note}</div>}
      {loading && <div className="card" aria-label="Loading video history"><div className="skeleton" /><div className="skeleton" /></div>}

      {!loading && (
        <div className="card">
          <h4 style={{ marginTop: 0 }}>What the next video is built from</h4>
          <ul className="small-text" style={{ margin: "6px 0", paddingLeft: 18 }}>
            <li>Guide: {guide.format ? FORMAT_NAMES[guide.format] || guide.format : "not generated yet"} · {guide.steps} step{guide.steps === 1 ? "" : "s"} · content rev {guide.contentRevision}</li>
            <li>Narration: {guide.hasTranscript ? "original recording available — voiceover cut from your audio" : "no narration — silent captioned video"}</li>
            <li>Accepted visuals available to the composition: {acceptedCount}</li>
            <li>Source recording: {fmtClock(durationSec || 0)} total{maxGuideSec != null && ` · videos support up to ${Math.round(maxGuideSec / 60)} min`}</li>
          </ul>
          {overLimit && (
            <p className="notice warn" role="status" style={{ marginBottom: 0 }}>
              This recording is longer than the supported video length ({Math.round((maxGuideSec || 0) / 60)} min).
              Generation will be refused — trim the source or split the tutorial first.
            </p>
          )}
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" onClick={() => void generate(readyVersions.length > 0)} disabled={busy || !jobDone || working || overLimit}>
              {busy ? "Starting…" : readyVersions.length ? "Generate new version" : "Generate video guide"}
            </button>
            {!jobDone && <span className="muted small-text" role="status">Generation unlocks once the tutorial finishes processing.</span>}
          </div>
        </div>
      )}

      {working && (
        <div className="card" role="status" aria-label="Render in progress">
          <p style={{ marginTop: 0 }}><span className="spinner" aria-hidden="true" /> {(() => {
            const active = versions.find((v) => v.status === "queued" || v.status === "rendering" || v.status === "validating");
            const label = active ? STATUS_LABEL[active.status] || active.status : "Working";
            return `${label}${active ? ` · ${active.progress}%` : ""}`;
          })()}</p>
          <div className="progress" role="progressbar"
            aria-valuenow={versions.find((v) => v.status === "queued" || v.status === "rendering" || v.status === "validating")?.progress || 0}
            aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${versions.find((v) => v.status === "queued" || v.status === "rendering" || v.status === "validating")?.progress || 0}%` }} />
          </div>
        </div>
      )}

      {versions.length > 0 && (
        <div className="card">
          <h4 style={{ marginTop: 0 }}>Versions ({versions.length})</h4>
          {versions.map((v) => (
            <div key={v.id} className="list-row">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>Version {v.version_number || "—"}</strong>{" "}
                  <span className={`tag ${v.status === "ready" ? "approved" : v.status === "error" ? "error" : ""}`}>{v.status}</span>
                  {v.simulated && <span className="tag warn">simulated plan</span>}
                  {v.status === "ready" && v.staleness?.stale && <span className="tag warn">guide changed</span>}
                  <span className="muted small-text"> · {new Date(v.created_at).toLocaleString()} · {(v.scenes || []).length} scenes · {voiceLabel(v)}</span>
                </div>
                <span className="row">
                  <button className="btn small secondary" aria-pressed={selectedId === v.id} onClick={() => setSelectedId(v.id)}>Preview</button>
                  {v.status === "ready" && (
                    <a className="btn small secondary"
                      href={videoVersionFileUrl(tutorialId, v.id, token)}
                      download={`${(title || "tutorial-guide").replace(/[^\w\- ]+/g, "").trim() || "tutorial-guide"}-v${v.version_number || ""}.mp4`}>Download</a>
                  )}
                </span>
              </div>
              {v.status === "error" && v.error && <p className="notice error" role="alert" style={{ marginBottom: 0 }}>Render failed: {v.error}</p>}
              {v.status === "ready" && v.staleness?.stale && (
                <p className="muted small-text" style={{ marginBottom: 0 }}>
                  The guide changed since this version ({v.staleness.changed.join(", ")}). Generate a new version for an up-to-date video — this one stays available.
                </p>
              )}
            </div>
          ))}
          {selected?.status === "ready" && (
            <div style={{ marginTop: 10 }}>
              <video key={selected.id} className="live-video" src={videoVersionFileUrl(tutorialId, selected.id, token)} controls playsInline preload="metadata" aria-label={`Video guide version ${selected.version_number}`} />
              <p className="muted small-text" style={{ marginTop: 6 }}>
                {(selected.scenes || []).length} scenes · {voiceLabel(selected)} ·{" "}
                {selected.simulated ? "deterministic fallback plan" : "Muse Spark plan"} · reproducible from the saved composition.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
