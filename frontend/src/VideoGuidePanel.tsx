import { useEffect, useRef, useState } from "react";
import type { VideoGuide } from "./videoGuide";
import { fetchVideoGuide, startVideoGuide, videoGuideVersionFileUrl } from "./videoGuide";
import { downloadVideoVersion } from "./studioApi";

/** Optional video guide: user-triggered MP4 cut from their own recorded narration. */
export default function VideoGuidePanel({ tutorialId, token, title, jobDone }: {
  tutorialId: string; token: string; title?: string; jobDone: boolean;
}) {
  const [guide, setGuide] = useState<VideoGuide | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [mediaError, setMediaError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const timer = useRef<number | null>(null);

  async function refresh() {
    try {
      const r = await fetchVideoGuide(tutorialId, token);
      setGuide(r.video_guide);
      return r.video_guide;
    } catch (e) {
      if (!guide) setError(e instanceof Error ? e.message : "Could not load video guide status.");
      return null;
    }
  }

  useEffect(() => {
    void refresh();
    return () => { if (timer.current !== null) window.clearInterval(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tutorialId]);

  useEffect(() => {
    if (guide && (guide.status === "queued" || guide.status === "rendering" || guide.status === "validating")) {
      if (timer.current === null) {
        timer.current = window.setInterval(() => { void refresh(); }, 3000);
      }
    } else if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
    return () => { if (timer.current !== null) { window.clearInterval(timer.current); timer.current = null; } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guide?.status]);

  async function generate(regen = false) {
    if (busy) return;
    setBusy(true); setError(""); setNote("");
    try {
      const g = await startVideoGuide(tutorialId, token, regen);
      setGuide(g);
      setNote(g.status === "ready" ? "Video guide is ready." : "Render queued — this tab polls every few seconds. You can leave; the video persists.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start video generation.");
    } finally {
      setBusy(false);
    }
  }

  const working = guide?.status === "queued" || guide?.status === "rendering" || guide?.status === "validating" || busy;

  async function download() {
    if (!guide || downloading) return;
    setDownloading(true);
    setError("");
    try {
      const fname = `${(title || "tutorial-guide").replace(/[^\w\- ]+/g, "").trim() || "tutorial-guide"}-v${guide.version_number || ""}.mp4`;
      await downloadVideoVersion(tutorialId, guide.id, token, fname);
      setNote("Download saved. The file was verified as video before saving.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="card" aria-label="Video guide" style={{ marginTop: 10 }}>
      <h3 style={{ marginTop: 0 }}>Video guide</h3>
      <p className="muted small-text">
        An optional MP4 cut from <strong>your own recorded narration</strong> — never synthesized.
        Step cards and captions come from the canonical procedure; the voiceover is the original audio, sliced per step.
      </p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {note && <div className="notice ok" role="status">{note}</div>}
      {guide?.status === "error" && (
        <div className="notice error" role="alert">Render failed: {guide.error || "unknown error"}. Fix the cause and generate again.</div>
      )}
      {(!guide || guide.status === "error") && (
        <button className="btn" disabled={busy || !jobDone} onClick={() => void generate()}>
          {busy ? "Starting…" : "Generate video guide"}
        </button>
      )}
      {guide && (guide.status === "queued" || guide.status === "rendering" || guide.status === "validating") && (
        <div role="status" aria-label={`Render ${guide.status}`}>
          <p className="muted">Rendering… {guide.progress}% — {guide.status}.</p>
          <div className="progress" role="progressbar" aria-valuenow={guide.progress} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${guide.progress}%` }} />
          </div>
        </div>
      )}
      {guide?.status === "ready" && (
        <div>
          <video className="live-video" src={videoGuideVersionFileUrl(tutorialId, guide.id, token)} controls playsInline preload="metadata" aria-label="Generated video guide"
            onError={() => setMediaError("Preview failed to load (the file may be missing or the session expired). Use Download — it validates the file before saving.")}
            onPlay={() => setMediaError("")} />
          {mediaError && <div className="notice error" role="alert" style={{ marginTop: 6 }}>{mediaError}</div>}
          <p className="muted small-text" style={{ marginTop: 6 }}>
            {guide.scenes.length} scene{guide.scenes.length === 1 ? "" : "s"} ·{" "}
            {guide.simulated ? <span className="tag warn">simulated plan (no Meta key)</span> : <span className="tag ai">Muse Spark plan</span>}{" "}
            {guide.provenance?.voiceover === "silent-captions-only"
              ? <span className="tag">silent captioned video (no narration track)</span>
              : <span className="tag">original-voice cut</span>}
            {typeof guide.provenance?.note === "string" && guide.provenance.note ? ` · ${guide.provenance.note}` : ""}
          </p>
          {guide.staleness?.stale && (
            <p className="notice warn" role="status">The guide changed since this video was rendered ({guide.staleness.changed.join(", ")}). Regenerate for an up-to-date video — this version stays available.</p>
          )}
          <div className="row">
            <button className="btn small secondary" disabled={busy} onClick={() => void generate(true)}>Regenerate</button>
            <button className="btn small secondary" disabled={downloading} onClick={() => void download()}>{downloading ? "Downloading…" : "Download .mp4"}</button>
          </div>
          <p className="muted small-text">Cached for offline viewing once played. Goes stale if the tutorial is re-recorded — regenerate to refresh.</p>
        </div>
      )}
    </div>
  );
}
