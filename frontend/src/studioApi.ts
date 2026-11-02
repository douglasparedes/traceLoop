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
  status: "draft" | "queued" | "rendering" | "ready" | "error";
  version_number: number;
  progress: number;
  error: string;
  asset_id: string | null;
  video_url: string | null;
  scenes: StudioScene[];
  simulated: boolean;
  provenance: Record<string, unknown>;
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

export async function saveScenePlan(tutorialId: string, token: string, scenes: StudioScene[]) {
  return api.put<{ ok: boolean; video_guide_id: string; scenes: StudioScene[] }>(
    `/api/tutorial/${tutorialId}/video-guide/scenes`, { scenes }, { "X-Tutorial-Token": token });
}

export async function renderScenePlan(tutorialId: string, token: string, scenes?: StudioScene[]) {
  return api.post<{ ok: boolean; video_guide: StudioVideoVersion; duplicate?: boolean }>(
    `/api/tutorial/${tutorialId}/video-guide/render`, scenes ? { scenes } : {}, { "X-Tutorial-Token": token });
}

export function videoVersionFileUrl(tutorialId: string, versionId: string, token: string): string {
  return `${API}/api/tutorial/${tutorialId}/video-guides/${versionId}/file?token=${encodeURIComponent(token)}`;
}
