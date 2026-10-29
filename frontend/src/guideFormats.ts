// Shared guide-format + visual-asset contracts and API helpers.
import { api, authHeaders, API, getIdentity } from "./api";

export type GuideFormatId = "work_instruction" | "reference_manual" | "interactive";

export interface GuideFormat {
  id: GuideFormatId;
  name: string;
  tagline: string;
  best_for: string;
}

export interface FormatRecommendation {
  format: GuideFormatId;
  source: "recommended" | "user";
  rationale: string;
  scores: Record<string, number>;
  recommendation?: { format: GuideFormatId; rationale: string };
  explicit?: boolean;
}

export interface GuideSnapshotItem {
  id: string;
  trigger: string;
  model: string;
  simulated: boolean;
  guide_hash: string;
  materials: string[];
  object_statuses: { obj_id?: number; label?: string; status?: string; confidence?: number | null }[];
  created_at: string;
  markdown_chars: number;
  guide_format?: string;
  format_source?: string;
  format_rationale?: string;
}

export interface VisualAsset {
  id: string;
  tutorial_id: string;
  parent_id: string;
  kind: string;
  status: "review" | "accepted" | "rejected";
  step_id?: string | null;
  version_id?: string | null;
  image_url: string | null;
  mime_type: string;
  width: number;
  height: number;
  instruction: string;
  model: string;
  simulated: boolean;
  provenance: Record<string, unknown>;
  created_at: string;
}

export interface AnnotShape {
  type: "point" | "circle" | "rect" | "arrow" | "label" | "dimension";
  points: [number, number][];
  text?: string;
  dimension?: { value: number; unit: string };
}

export const ANNOTATION_UNITS = ["mm", "cm", "m", "inch", "in", "px"] as const;

export function validateAnnotation(shapes: AnnotShape[]): string | null {
  if (!Array.isArray(shapes) || shapes.length === 0) return "Add at least one annotation shape.";
  if (shapes.length > 50) return "Too many shapes (max 50).";
  const kinds = ["point", "circle", "rect", "arrow", "label", "dimension"];
  for (let i = 0; i < shapes.length; i++) {
    const s = shapes[i] as AnnotShape;
    if (!s || !kinds.includes(s.type)) return `Shape ${i + 1}: unknown type.`;
    const need = s.type === "rect" || s.type === "arrow" ? 2 : 1;
    if (!Array.isArray(s.points) || s.points.length !== need || !s.points.every((p) => Array.isArray(p) && p.length === 2 && p.every((v) => typeof v === "number" && v >= 0 && v <= 1))) {
      return `Shape ${i + 1} (${s.type}): coordinates must be [x, y] in 0..1.`;
    }
    if (s.type === "dimension") {
      const d = s.dimension;
      if (!d || typeof d.value !== "number" || !(d.value > 0)) return `Shape ${i + 1}: dimension needs a positive number.`;
      if (!ANNOTATION_UNITS.includes(d.unit as (typeof ANNOTATION_UNITS)[number])) return `Shape ${i + 1}: unit must be one of ${ANNOTATION_UNITS.join(", ")}.`;
    } else if ((s as { dimension?: unknown }).dimension !== undefined) {
      return `Shape ${i + 1}: only dimension shapes carry a dimension.`;
    }
    if (s.text != null && s.text.length > 200) return `Shape ${i + 1}: label too long (max 200 chars).`;
  }
  return null;
}

/** Client-side dimension parsing: "3.5 mm" -> {value, unit} or an error string. Never invents a value. */
export function parseDimension(input: string): { value: number; unit: string } | { error: string } {
  const m = /^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s*$/.exec(input || "");
  if (!m) return { error: "Enter a dimension like “3.5 mm”." };
  const value = parseFloat(m[1]);
  const unit = m[2].toLowerCase() === "inch" ? "inch" : m[2].toLowerCase();
  const allowed = ["mm", "cm", "m", "inch", "in", "px"];
  if (!(value > 0)) return { error: "Dimension must be a positive number." };
  if (!allowed.includes(unit)) return { error: `Unit must be one of ${allowed.join(", ")}.` };
  return { value, unit };
}

function tutHeaders(token: string, extra: Record<string, string> = {}) {
  return authHeaders({ "X-Tutorial-Token": token, ...extra });
}

export async function fetchFormats(): Promise<GuideFormat[]> {
  const r = await api.get<{ formats: GuideFormat[] }>("/api/tutorial/formats");
  return r.formats || [];
}

export async function fetchRecommendation(tutorialId: string, token: string): Promise<FormatRecommendation> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/recommendation`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Recommendation failed (${res.status})`);
  return res.json();
}

export async function setGuideFormat(tutorialId: string, token: string, format: string) {
  return api.put<{ ok: boolean; format: string }>(`/api/tutorial/${tutorialId}/format`, { format }, { "X-Tutorial-Token": token });
}

export async function generateGuideVersion(tutorialId: string, token: string, format?: string) {
  return api.post<{ ok: boolean; snapshot_id: string; format: string; format_source: string; rationale: string; draft_version_id: string | null; draft_status: string | null; markdown_chars: number; duplicate?: boolean }>(
    `/api/tutorial/${tutorialId}/guide`, format ? { format } : {}, { "X-Tutorial-Token": token });
}

export async function fetchSnapshots(tutorialId: string, token: string): Promise<GuideSnapshotItem[]> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/snapshots`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Snapshots failed (${res.status})`);
  return (await res.json()).snapshots || [];
}

export async function fetchSnapshot(tutorialId: string, token: string, id: string): Promise<{ guide_markdown: string } & GuideSnapshotItem> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/snapshots/${id}`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Snapshot failed (${res.status})`);
  return res.json();
}

export async function fetchVisuals(tutorialId: string, token: string): Promise<VisualAsset[]> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/visuals`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Visuals failed (${res.status})`);
  return (await res.json()).items || [];
}

export async function improveVisual(tutorialId: string, token: string, body: Record<string, unknown>) {
  return api.post<{ ok: boolean; asset: VisualAsset; duplicate?: boolean }>(`/api/tutorial/${tutorialId}/visuals/improve`, body, { "X-Tutorial-Token": token });
}

export async function generateAlternative(tutorialId: string, token: string, body: Record<string, unknown>) {
  return api.post<{ ok: boolean; asset: VisualAsset; duplicate?: boolean }>(`/api/tutorial/${tutorialId}/visuals/alternative`, body, { "X-Tutorial-Token": token });
}

export async function annotateVisual(tutorialId: string, token: string, body: Record<string, unknown>) {
  return api.post<{ ok: boolean; asset: VisualAsset }>(`/api/tutorial/${tutorialId}/visuals/annotate`, body, { "X-Tutorial-Token": token });
}

export async function acceptVisual(id: string, opts: { step_id?: string; version_id?: string } = {}) {
  return api.post<{ ok: boolean; asset: VisualAsset; already?: boolean; evidence_id?: string | null }>(`/api/visuals/${id}/accept`, opts, {});
}

export async function rejectVisual(id: string) {
  return api.post<{ ok: boolean; asset: VisualAsset }>(`/api/visuals/${id}/reject`, {}, {});
}

export function visualFileUrl(a: VisualAsset, token: string): string {
  return `${API}/api/visuals/${a.id}/file?token=${encodeURIComponent(token)}`;
}
