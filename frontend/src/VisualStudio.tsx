import { useMemo, useRef, useState } from "react";
import type { AnnotShape, VisualAsset } from "./guideFormats";
import { acceptVisual, annotateVisual, generateAlternative, improveVisual, parseDimension, rejectVisual, validateAnnotation, visualFileUrl } from "./guideFormats";

function OverlaySvg({ shapes, w, h }: { shapes: AnnotShape[]; w: number; h: number }) {
  const X = (x: number) => (x * w);
  const Y = (y: number) => (y * h);
  const fmt = (v: number) => v.toFixed(1);
  return (
    <svg className="mask-svg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      {shapes.map((s, i) => {
        if (s.type === "circle" || s.type === "point") {
          const [x, y] = s.points[0];
          const r = s.type === "circle" ? 26 : 6;
          return <g key={i}><circle cx={fmt(X(x))} cy={fmt(Y(y))} r={r} fill={s.type === "circle" ? "rgba(255,176,32,.15)" : "#ffb020"} stroke="#ffb020" strokeWidth={4 / Math.max(w / 200, 1)} /></g>;
        }
        if (s.type === "rect" || s.type === "arrow") {
          const [x1, y1] = s.points[0]; const [x2, y2] = s.points[1];
          const rx = Math.min(X(x1), X(x2)); const ry = Math.min(Y(y1), Y(y2));
          const rw = Math.abs(X(x1) - X(x2)); const rh = Math.abs(Y(y1) - Y(y2));
          return s.type === "rect"
            ? <g key={i}><rect x={fmt(rx)} y={fmt(ry)} width={fmt(rw)} height={fmt(rh)} fill="rgba(255,176,32,.12)" stroke="#ffb020" strokeWidth="4" rx="6" /></g>
            : <g key={i}><line x1={fmt(X(x1))} y1={fmt(Y(y1))} x2={fmt(X(x2))} y2={fmt(Y(y2))} stroke="#ffb020" strokeWidth="5" /></g>;
        }
        return null;
      })}
      {shapes.filter((s) => s.text || s.dimension).map((s, i) => {
        const last = s.points[s.points.length - 1];
        const label = s.dimension ? `${s.dimension.value} ${s.dimension.unit} (unverified)` : (s.text || "");
        const lx = X(last[0]); const ly = Y(last[1]);
        return <g key={`t${i}`}><rect x={fmt(lx - 6)} y={fmt(ly - 30)} width={Math.max(60, label.length * 8.5)} height={26} rx={6} fill="#201600" /><text x={fmt(lx)} y={fmt(ly - 10)} fontSize="17" fontFamily="sans-serif" fill="#ffb020">{label}</text></g>;
      })}
    </svg>
  );
}

/** Image + SAM mask + accepted annotation overlays. Never edits the source. */
export function TechnicalImageViewer({ src, alt, bbox, maskSvg, annotations, onTap }: {
  src: string; alt: string;
  bbox?: [number, number, number, number] | null;
  maskSvg?: { svg_path: string; width: number; height: number } | null;
  annotations?: { shapes: AnnotShape[] }[];
  onTap?: (nx: number, ny: number) => void;
}) {
  return (
    <div className="overlay-wrap" role={onTap ? "button" : "img"} aria-label={onTap ? `${alt}. Activate, then click the part you mean.` : alt}
      onClick={onTap ? (e) => { const r = e.currentTarget.getBoundingClientRect(); onTap((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height); } : undefined}
      style={onTap ? { cursor: "crosshair" } : undefined}>
      <img src={src} alt="" />
      {bbox && (
        <div className="bbox" style={{ left: `${bbox[0] * 100}%`, top: `${bbox[1] * 100}%`, width: `${(bbox[2] - bbox[0]) * 100}%`, height: `${(bbox[3] - bbox[1]) * 100}%` }} />
      )}
      {maskSvg?.svg_path && (
        <svg className="mask-svg" viewBox={`0 0 ${maskSvg.width} ${maskSvg.height}`} preserveAspectRatio="none" aria-hidden="true">
          <path d={maskSvg.svg_path} />
        </svg>
      )}
      {(annotations || []).map((a, i) => <OverlaySvg key={i} shapes={a.shapes} w={1000} h={1000} />)}
    </div>
  );
}

function Provenance({ asset }: { asset: VisualAsset }) {
  const kindLabel: Record<string, string> = {
    source_frame: "Original source", photo: "Original photo", segmentation: "SAM segmentation",
    enhanced: "AI-enhanced derivative", annotation: "Deterministic annotation",
    illustrative_alternative: "AI-generated illustration", user_reference: "User-supplied reference",
    guide_visual: "Accepted guide visual",
  };
  return (
    <div className="muted small-text" style={{ marginTop: 6 }}>
      <span className={`tag ${asset.kind === "illustrative_alternative" ? "warn" : asset.kind === "annotation" ? "ai" : ""}`}>
        {kindLabel[asset.kind] || asset.kind}
      </span>
      {asset.model && <span> · model: {asset.model}</span>}
      {Array.isArray((asset.provenance as { attempts?: unknown[] }).attempts) && <span> · attempts: {(asset.provenance as { attempts?: unknown[] }).attempts!.length}</span>}
      {typeof (asset.provenance as { warning?: unknown }).warning === "string" && (
        <span className="tag warn" style={{ marginLeft: 6 }}>{String((asset.provenance as { warning?: unknown }).warning)}</span>
      )}
      {asset.status !== "accepted" && <span> · status: {asset.status} (not authoritative until accepted and reviewed)</span>}
    </div>
  );
}

function dimText(v: string): string {
  const p = parseDimension(v);
  return "error" in p ? p.error : `${p.value} ${p.unit}`;
}

/** Draw-on-image annotation composer with validated shapes and dimensions. */
export function AnnotationComposer({ imageUrl, imageLabel, onDone }: {
  imageUrl: string; imageLabel: string; onDone: (shapes: AnnotShape[], label: string) => void;
}) {
  const [tool, setTool] = useState<AnnotShape["type"]>("point");
  const [draft, setDraft] = useState<AnnotShape[]>([]);
  const [cur, setCur] = useState<[number, number][]>([]);
  const [label, setLabel] = useState("");
  const [dim, setDim] = useState("");
  const [dimError, setDimError] = useState("");
  const [labelText, setLabelText] = useState("");

  function tap(nx: number, ny: number) {
    const p: [number, number] = [Math.min(1, Math.max(0, nx)), Math.min(1, Math.max(0, ny))];
    if (tool === "point" || tool === "circle" || tool === "label") {
      commit([p]);
    } else {
      const next = [...cur, p];
      if (next.length === 2) { commit(next); setCur([]); }
      else setCur(next);
    }
  }

  function commit(pts: [number, number][]) {
    let shape: AnnotShape = { type: tool === "label" ? "label" : tool, points: pts };
    if (tool === "label") shape = { ...shape, text: labelText.trim().slice(0, 200) };
    if (tool === "dimension") {
      const parsed = parseDimension(dim);
      if ("error" in parsed) { setDimError(parsed.error); return; }
      setDimError("");
      shape = { ...shape, text: "", dimension: { value: parsed.value, unit: parsed.unit } };
    }
    setDraft((d) => [...d, shape]);
  }

  const err = validateAnnotation(draft.length ? draft : [{ type: "point", points: [[0.5, 0.5]] }]);
  void err;

  return (
    <div>
      <p className="muted small-text">Click the image to place the {tool}. Coordinates stay in 0–1 space, so annotations survive resizes. Dimensions you type are stored verbatim as <em>your requirement</em> — never measured.</p>
      <div className="row" role="group" aria-label="Annotation tool">
        {(["point", "circle", "rect", "arrow", "label", "dimension"] as const).map((t) => (
          <button key={t} className={`btn small ${tool === t ? "" : "secondary"}`} aria-pressed={tool === t} onClick={() => { setTool(t); setCur([]); }}>{t}</button>
        ))}
      </div>
      {tool === "label" && (
        <label>Label text<input value={labelText} onChange={(e) => setLabelText(e.target.value)} placeholder="e.g. upper retaining clip" maxLength={200} /></label>
      )}
      {tool === "dimension" && (
        <label>Required dimension (verbatim, e.g. “3.5 mm”)
          <input value={dim} onChange={(e) => setDim(e.target.value)} placeholder="3.5 mm" aria-describedby="dim-hint" />
          <span id="dim-hint" className="muted small-text">Stored exactly as you write it and labelled unverified. {dim ? dimText(dim) : ""}</span>
        </label>
      )}
      {dimError && <div className="notice error" role="alert">{dimError}</div>}
      {cur.length === 1 && <p className="muted small-text" role="status">First point set — click again to finish the shape. <button className="btn small secondary" onClick={() => setCur([])}>Cancel</button></p>}
      <TechnicalImageViewer src={imageUrl} alt={imageLabel} onTap={tap}
        annotations={draft.length ? [{ shapes: draft }] : cur.length ? [{ shapes: [{ type: tool === "label" ? "label" : tool, points: cur.length === 2 ? cur : [...cur, cur[0]] } as AnnotShape] }] : []} />
      {draft.length > 0 && (
        <ul className="small-text">
          {draft.map((s, i) => (
            <li key={i}>{s.type}{s.text ? ` — “${s.text}”` : ""}{s.dimension ? ` — ${s.dimension.value} ${s.dimension.unit} (unverified)` : ""}{" "}
              <button className="btn small secondary" onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        <label style={{ flex: "1 1 200px" }}>Annotation set label (optional)<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. clip highlight for step 3" maxLength={200} /></label>
        <button className="btn" disabled={draft.length === 0} onClick={() => { const v = validateAnnotation(draft); if (v) { setDimError(v); return; } onDone(draft, label.trim()); }}>Save annotation</button>
        {draft.length > 0 && <button className="btn secondary" onClick={() => { setDraft([]); setCur([]); }}>Clear</button>}
      </div>
    </div>
  );
}

/** Full image-workbench: improve, highlight, alternative, annotate. */
export default function VisualStudio({ tutorialId, token, sourceAsset, references, onChanged }: {
  tutorialId: string; token: string;
  sourceAsset: { id: string; label: string; imageUrl: string; kind: string; source: Record<string, unknown> } | null;
  references: { id: string; label: string }[];
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<"improve" | "highlight" | "alternative" | "annotate">("improve");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [intent, setIntent] = useState("similar");
  const [altDesc, setAltDesc] = useState("");
  const [altRefs, setAltRefs] = useState<string[]>([]);
  const [altResult, setAltResult] = useState<VisualAsset | null>(null);
  const [impResult, setImpResult] = useState<VisualAsset | null>(null);

  async function runImprove() {
    if (!sourceAsset || busy) return;
    if (!prompt.trim()) { setError("Describe what to clarify (e.g. “the tip of this screw”)."); return; }
    setBusy(true); setError(""); setNote("");
    try {
      const r = await improveVisual(tutorialId, token, {
        source: sourceAsset.source, prompt: prompt.trim(),
        idempotency_key: `${sourceAsset.id}:${prompt.trim().slice(0, 120)}`,
      });
      setImpResult(r.asset);
      setNote(r.duplicate ? "Identical request already processed — showing the existing result (no new generation)." : "Review the proposal below. The original is unchanged.");
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Improvement failed — the original is untouched."); }
    finally { setBusy(false); }
  }

  async function runAlternative() {
    if (busy) return;
    if (!altDesc.trim()) { setError("Describe the illustrative object you want (e.g. “same clamp on a Toyota 4x4”)."); return; }
    setBusy(true); setError(""); setNote(""); setAltResult(null);
    try {
      const r = await generateAlternative(tutorialId, token, {
        prompt: altDesc.trim(), intent,
        references: altRefs.map((id) => ({ kind: "asset", id })),
        idempotency_key: `${intent}:${altDesc.trim().slice(0, 120)}:${altRefs.join(",")}`,
      });
      setAltResult(r.asset);
      setNote("AI-generated illustrative alternative. It is not evidence — applicability must be verified by a human.");
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Generation failed."); }
    finally { setBusy(false); }
  }

  async function saveAnnotation(shapes: AnnotShape[], label: string) {
    if (!sourceAsset) return;
    setBusy(true); setError(""); setNote("");
    try {
      const r = await annotateVisual(tutorialId, token, { source: sourceAsset.source, shapes, label });
      setNote("Annotation saved as a separate overlay — the source image is unchanged. Accept it below to attach it to a guide step.");
      setAltResult(r.asset);
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Annotation failed."); }
    finally { setBusy(false); }
  }

  async function decide(a: VisualAsset, accept: boolean, stepId?: string, versionId?: string) {
    setBusy(true); setError("");
    try {
      const r = accept
        ? await acceptVisual(a.id, stepId && versionId ? { step_id: stepId, version_id: versionId } : {})
        : await rejectVisual(a.id);
      setImpResult((cur) => (cur && cur.id === a.id ? r.asset : cur));
      setAltResult((cur) => (cur && cur.id === a.id ? r.asset : cur));
      setNote(accept ? (r as { evidence_id?: string }).evidence_id ? "Accepted and linked as guide visual evidence." : "Accepted. Attach it to a guide step to use it." : "Rejected. The original and all prior versions are untouched.");
      onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Decision failed."); }
    finally { setBusy(false); }
  }

  function ResultCard({ a, extra }: { a: VisualAsset; extra?: React.ReactNode }) {
    return (
      <div className="card" style={{ marginTop: 10 }}>
        <h4 style={{ marginTop: 0 }}>{a.kind === "illustrative_alternative" ? "AI-generated illustrative alternative" : a.kind === "annotation" ? "Annotation overlay" : "Proposed improvement"}</h4>
        {a.kind === "annotation"
          ? <div className="overlay-wrap"><img src={visualFileUrl(a, token)} alt="Annotation overlay" style={{ maxWidth: "100%" }} /></div>
          : <img src={visualFileUrl(a, token)} alt={a.instruction || "Generated visual"} style={{ maxWidth: "100%", borderRadius: 8 }} />}
        <Provenance asset={a} />
        {extra}
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn small" disabled={busy || a.status === "accepted"} onClick={() => void decide(a, true)}>{a.status === "accepted" ? "Accepted" : "Accept"}</button>
          <button className="btn small secondary" disabled={busy || a.status !== "review"} onClick={() => void decide(a, false)}>Reject</button>
        </div>
      </div>
    );
  }

  return (
    <div className="card" aria-label="Visual studio">
      <h3>Image studio</h3>
      {!sourceAsset && <p className="muted">Select a source image first (from an object or step above).</p>}
      {sourceAsset && <p className="muted small-text">Source: {sourceAsset.label} <span className="tag">original preserved</span></p>}
      <div className="row" role="group" aria-label="Image actions">
        {(["improve", "highlight", "alternative", "annotate"] as const).map((t) => (
          <button key={t} className={`btn small ${tab === t ? "" : "secondary"}`} aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t === "improve" ? "Improve image" : t === "highlight" ? "Highlight part" : t === "alternative" ? "Illustrative alternative" : "Annotate"}
          </button>
        ))}
      </div>
      {note && <div className="notice ok" role="status" style={{ marginTop: 8 }}>{note}</div>}
      {error && <div className="notice error" role="alert" style={{ marginTop: 8 }}>{error}</div>}

      {tab === "improve" && (
        <div style={{ marginTop: 8 }}>
          <p className="muted small-text">Muse Image edits the <strong>copy</strong>, never the source. Best for: incomplete crops, unclear subjects, low resolution. The output is labelled as AI-derived and needs review.</p>
          <label>What should be clearer?<input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. the tip of this screw — make it easier to see" maxLength={500} disabled={!sourceAsset} /></label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy || !sourceAsset || !prompt.trim()} onClick={() => void runImprove()}>{busy ? "Working…" : "Generate improvement"}</button>
          </div>
          <p className="muted small-text">Requires network. Offline: write the prompt here and submit when reconnected — the source image is already on this device.</p>
          {impResult && <ResultCard a={impResult} />}
        </div>
      )}

      {tab === "highlight" && (
        <div style={{ marginTop: 8 }}>
          <p className="muted small-text">Precise callouts are drawn <strong>deterministically</strong> as SVG overlays — pixel-exact, no AI involved. Use this for pointers, outlines, labels and required dimensions.</p>
          {!sourceAsset ? <p className="muted">Select a source image first.</p> : (
            <AnnotationComposer imageUrl={sourceAsset.imageUrl} imageLabel={sourceAsset.label}
              onDone={(shapes, label) => void (async () => {
                setBusy(true); setError(""); setNote("");
                try {
                  const r = await annotateVisual(tutorialId, token, { source: sourceAsset.source, shapes, label });
                  setImpResult(r.asset);
                  setNote("Annotation saved as a separate overlay — the source image is unchanged.");
                  onChanged();
                } catch (e) { setError(e instanceof Error ? e.message : "Annotation failed."); }
                finally { setBusy(false); }
              })()} />
          )}
          {impResult && impResult.kind === "annotation" && <ResultCard a={impResult} />}
        </div>
      )}

      {tab === "alternative" && (
        <div style={{ marginTop: 8 }}>
          <p className="muted small-text">Generate a <strong>new illustration</strong> (e.g. a newer model) from your description. It is always labelled illustrative and can never become evidence.</p>
          <div className="row" role="group" aria-label="Intent">
            {([["similar", "Similar illustrative object"], ["newer", "Newer model"], ["reference", "Use supplied reference"]] as const).map(([v, label]) => (
              <button key={v} className={`btn small ${intent === v ? "" : "secondary"}`} aria-pressed={intent === v} onClick={() => setIntent(v)}>{label}</button>
            ))}
          </div>
          <label style={{ marginTop: 8 }}>Describe the illustration
            <textarea rows={2} value={altDesc} onChange={(e) => setAltDesc(e.target.value)} placeholder="e.g. same clamp on a Toyota 4x4 engine bay, orientation reference only" maxLength={500} />
          </label>
          <label>Reference visuals (optional, from this tutorial)
            <select multiple value={altRefs} aria-label="Reference visuals" onChange={(e) => setAltRefs(Array.from(e.target.selectedOptions).map((o) => o.value))} style={{ minHeight: 44 }}>
              {references.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy || !altDesc.trim()} onClick={() => void runAlternative()}>{busy ? "Generating…" : "Generate alternative"}</button>
          </div>
          {altResult && <ResultCard a={altResult} />}
        </div>
      )}

      {tab === "annotate" && (
        <div style={{ marginTop: 8 }}>
          <p className="muted small-text">Same deterministic overlays as “Highlight”, kept here for the annotation workflow.</p>
          {!sourceAsset ? <p className="muted">Select a source image first.</p> : (
            <AnnotationComposer imageUrl={sourceAsset.imageUrl} imageLabel={sourceAsset.label}
              onDone={(shapes, label) => void saveAnnotation(shapes, label)} />
          )}
        </div>
      )}
    </div>
  );
}
