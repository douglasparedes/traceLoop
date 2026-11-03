// Tutorial Studio contracts + API helpers: canonical content editing,
// content revisions, and versioned video-guide scene plans.
// Every save is explicit, validated server-side, and concurrency-checked
// via expected_revision — stale saves are rejected, never merged.
import { api, authHeaders, API, getIdentity } from "./api";

export interface StudioStep {
  step_number: number;
  title: string;
  summary: string;
  start: number;
  end: number;
  objects_used: number[];
  expected_result?: string;
  verification_notes?: string;
  required_tools?: string[];
  evidence_frames?: number[];
  confidence?: string;
  derivation?: string;
}

export interface StudioSegment {
  text: string;
  start: number;
  end: number;
}

export interface StudioContent {
  tutorial_id: string;
  content_revision: number;
  transcript_original: string;
  transcript_corrected: string;
  timed_segments: StudioSegment[];
  steps: StudioStep[];
  materials: string[];
  updated_at: string;
}

export interface ContentRevisionItem {
  id: string;
  revision_number: number;
  steps: number;
  transcript_chars: number;
  actor: string;
  note: string;
  created_at: string;
}

export interface StudioVideoVersion {
  id: string;
  tutorial_id: string;
  status: "draft" | "queued" | "rendering" | "validating" | "ready" | "error";
  version_number: number;
  progress: number;
  error: string;
  asset_id: string | null;
  video_url: string | null;
  scenes: StudioScene[];
  simulated: boolean;
  provenance: Record<string, unknown>;
  staleness?: {
    stale: boolean;
    changed: string[];
    video_guide_id: string;
    version_number: number;
  };
  created_at: string;
}

export interface StudioScene {
  step?: number;
  step_number?: number;
  title: string;
  caption?: string;
  audio_start?: number;
  audio_end?: number;
  start?: number;
  end?: number;
  visual?: { name?: string; kind?: string; label?: string };
  include?: boolean;
}

function tutHeaders(token: string, extra: Record<string, string> = {}) {
  return authHeaders({ "X-Tutorial-Token": token, ...extra });
}

export function sceneRange(s: StudioScene): { start: number; end: number } {
  const start = Number(s.audio_start ?? s.start ?? 0) || 0;
  const end = Number(s.audio_end ?? s.end ?? 0) || 0;
  return { start, end };
}

export function sceneStep(s: StudioScene, fallback: number): number {
  return Number(s.step ?? s.step_number ?? fallback) || fallback;
}

export async function fetchStudioContent(tutorialId: string, token: string): Promise<StudioContent> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/content`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Content load failed (${res.status})`);
  return res.json();
}

export async function saveStudioContent(tutorialId: string, token: string, body: {
  transcript_corrected?: string; timed_segments?: StudioSegment[]; steps?: StudioStep[];
  materials?: string[]; expected_revision: number; note?: string;
}): Promise<{ ok: boolean; content_revision: number; revision_number: number; touched: string[] }> {
  return api.put(`/api/tutorial/${tutorialId}/content`, body, { "X-Tutorial-Token": token });
}

export async function updateTutorialMeta(tutorialId: string, token: string, body: {
  title?: string; equipment_name?: string; task_description?: string; context_notes?: string;
  expected_revision?: number;
}): Promise<{ id: string; title: string; equipment_name: string; task_description: string; context_notes: string }> {
  return api.put(`/api/tutorial/${tutorialId}`, body, { "X-Tutorial-Token": token });
}

export async function fetchContentRevisions(tutorialId: string, token: string): Promise<{
  tutorial_id: string; current_revision: number; revisions: ContentRevisionItem[];
}> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/revisions`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Revisions load failed (${res.status})`);
  return res.json();
}

export async function restoreContentRevision(tutorialId: string, token: string, revisionId: string, expectedRevision: number) {
  return api.post<{ ok: boolean; content_revision: number; revision_number: number }>(
    `/api/tutorial/${tutorialId}/revisions/${revisionId}/restore`, { expected_revision: expectedRevision }, { "X-Tutorial-Token": token });
}

export async function fetchVideoVersions(tutorialId: string, token: string): Promise<StudioVideoVersion[]> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/video-guides`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Video history failed (${res.status})`);
  return ((await res.json()).versions || []) as StudioVideoVersion[];
}

export async function fetchVideoLimits(tutorialId: string, token: string): Promise<{ max_video_guide_sec: number } | null> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/video-guides`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) return null;
  const body = await res.json();
  return (body.limits as { max_video_guide_sec: number }) || null;
}

export interface SuggestedScenePlan {
  scenes: StudioScene[];
  simulated: boolean;
  model: string;
  note: string;
}

export async function fetchSuggestedScenes(tutorialId: string, token: string): Promise<SuggestedScenePlan> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/video-guide/suggest`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || `Scene suggestion failed (${res.status})`);
  }
  const body = await res.json();
  return { scenes: body.scenes || [], simulated: !!body.simulated, model: body.model || "", note: body.note || "" };
}

export async function saveScenePlan(tutorialId: string, token: string, scenes: StudioScene[]) {
  return api.put<{ ok: boolean; video_guide_id: string; scenes: StudioScene[] }>(
    `/api/tutorial/${tutorialId}/video-guide/scenes`, { scenes }, { "X-Tutorial-Token": token });
}

export async function renderScenePlan(tutorialId: string, token: string, scenes?: StudioScene[]) {
  return api.post<{ ok: boolean; video_guide: StudioVideoVersion; duplicate?: boolean }>(
    `/api/tutorial/${tutorialId}/video-guide/render`, scenes ? { scenes } : {}, { "X-Tutorial-Token": token });
}

/** One-click automatic generation: the server composes the video from the
 *  current guide (no scene editing required). Regenerate forces a fresh
 *  version; otherwise an in-flight or up-to-date render is reused. */
export async function startVideoGuide(tutorialId: string, token: string, regenerate = false) {
  return api.post<{ ok: boolean; video_guide: StudioVideoVersion; duplicate?: boolean }>(
    `/api/tutorial/${tutorialId}/video-guide`, regenerate ? { regenerate: true } : {}, { "X-Tutorial-Token": token });
}

export function videoVersionFileUrl(tutorialId: string, versionId: string, token: string): string {
  return `${API}/api/tutorial/${tutorialId}/video-guides/${versionId}/file?token=${encodeURIComponent(token)}`;
}

/** Validated MP4 download: fetches the exact version, refuses to save an
 *  error page as a video, then triggers a real file download.
 *
 *  A 401/403/404 JSON body must never become `tutorial-guide-v3.mp4` on
 *  the user's disk — the response is checked before anything is saved.
 */
export async function downloadVideoVersion(tutorialId: string, versionId: string, token: string, filename: string): Promise<void> {
  const res = await fetch(`${videoVersionFileUrl(tutorialId, versionId, token)}&download=1`);
  const ct = res.headers.get("content-type") || "";
  if (!res.ok || !ct.includes("video/mp4")) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = (body as { detail?: string; message?: string }).detail
        || (body as { message?: string }).message || detail;
    } catch { /* error page was not JSON — keep the status */ }
    throw new Error(`Download failed (${detail}). The video file was not served — check the connection and retry.`);
  }
  const blob = await res.blob();
  if (!blob.size) throw new Error("Download failed: the server returned an empty file.");
  const href = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(href), 5000);
  }
}
