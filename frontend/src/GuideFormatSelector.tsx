import { useEffect, useState } from "react";
import type { GuideFormat, FormatRecommendation } from "./guideFormats";
import { fetchFormats, fetchRecommendation, generateGuideVersion, setGuideFormat } from "./guideFormats";

/** Three selectable guide presentations of one shared canonical guide. */
export default function GuideFormatSelector({ tutorialId, token, current, onGenerated, onChanged }: {
  tutorialId: string; token: string; current: string;
  onGenerated: (snapshotId: string) => void;
  onChanged?: () => void;
}) {
  const [formats, setFormats] = useState<GuideFormat[]>([]);
  const [rec, setRec] = useState<FormatRecommendation | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [f, r] = await Promise.all([fetchFormats(), fetchRecommendation(tutorialId, token)]);
        if (!alive) return;
        setFormats(f);
        setRec(r);
        setSelected(current || r.format);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Could not load formats — check connection.");
      }
    })();
    return () => { alive = false; };
  }, [tutorialId, token, current]);

  if (error && formats.length === 0) return <div className="notice error" role="alert">{error}</div>;
  if (!formats.length) return <div className="card"><div className="skeleton" /><div className="skeleton" /></div>;

  return (
    <div className="card" aria-label="Guide format selection">
      <h3>Choose a presentation</h3>
      <p className="muted small-text">Same verified content, three presentations. Changing format creates a new saved version — previous versions stay intact, and approved procedures are never altered.</p>
      <div className="grid" role="radiogroup" aria-label="Guide format">
        {formats.map((f) => {
          const isCurrent = current === f.id;
          const isRec = rec != null && rec.format === f.id && rec.source === "recommended";
          return (
            <button key={f.id} role="radio" aria-checked={selected === f.id}
              className={`card ${selected === f.id ? "primary-action" : ""}`} style={{ textAlign: "left", margin: 0, cursor: "pointer" }}
              onClick={() => setSelected(f.id)}>
              <span style={{ visibility: isCurrent ? "visible" : "hidden" }} aria-hidden={!isCurrent} className="badge ok">Current</span>{" "}
              {isRec && <span className="badge info">AI recommended</span>}
              <strong style={{ display: "block", marginTop: 6 }}>{f.name}</strong>
              <span className="small-text">{f.tagline}</span>
              <span className="muted small-text" style={{ display: "block", marginTop: 4 }}>{f.best_for}</span>
            </button>
          );
        })}
      </div>
      {rec != null && (
        <p className="muted small-text" role="status" style={{ marginTop: 8 }}>
          {rec.source === "recommended" ? rec.rationale : `You selected ${rec.format.replace(/_/g, " ")}. Recommendation remains available below.`}
          {rec.scores != null && Object.keys(rec.scores).length > 0 && (
            <> Scores — {Object.entries(rec.scores).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</>
          )}
        </p>
      )}
      {note && <div className="notice ok" role="status">{note}</div>}
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn" disabled={busy || !selected} onClick={async () => {
          setBusy(true); setError(""); setNote("");
          try {
            if (selected !== current) await setGuideFormat(tutorialId, token, selected);
            const r = await generateGuideVersion(tutorialId, token, selected);
            setNote(r.duplicate ? "Identical version already exists — opened the existing one instead of duplicating." : `New ${r.format.replace(/_/g, " ")} version saved.`);
            onGenerated(r.snapshot_id);
            onChanged?.();
          } catch (e) { setError(e instanceof Error ? e.message : "Generation failed — your previous versions are untouched."); }
          finally { setBusy(false); }
        }}>{busy ? "Generating…" : current ? "Generate new version" : "Generate guide"}</button>
      </div>
    </div>
  );
}
