// Video guide (MP4 cut from the user's own recorded narration) contracts + API.
import { api, authHeaders, API, getIdentity } from "./api";

export type VideoGuideStatus = "none" | "queued" | "rendering" | "ready" | "error";

export interface VideoGuide {
  id: string;
  tutorial_id: string;
  status: Exclude<VideoGuideStatus, "none">;
  progress: number;
  error: string;
  asset_id: string | null;
  video_url: string | null;
  scenes: { step: number; title: string; caption: string }[];
  simulated: boolean;
  provenance: Record<string, unknown>;
  created_at: string;
}

function tutHeaders(token: string, extra: Record<string, string> = {}) {
  return authHeaders({ "X-Tutorial-Token": token, ...extra });
}

export async function startVideoGuide(tutorialId: string, token: string, regenerate = false): Promise<VideoGuide> {
  const r = await api.post<{ ok: boolean; video_guide: VideoGuide; duplicate?: boolean }>(
    `/api/tutorial/${tutorialId}/video-guide`, regenerate ? { regenerate: true } : {}, { "X-Tutorial-Token": token });
  return r.video_guide;
}

export async function fetchVideoGuide(tutorialId: string, token: string): Promise<{ status: VideoGuideStatus; video_guide: VideoGuide | null }> {
  const idn = getIdentity();
  const res = await fetch(`${API}/api/tutorial/${tutorialId}/video-guide`, { headers: tutHeaders(token, { "X-User": idn.user, "X-Role": idn.role }) });
  if (!res.ok) throw new Error(`Video guide status failed (${res.status})`);
  return res.json();
}

export function videoGuideFileUrl(tutorialId: string, token: string): string {
  return `${API}/api/tutorial/${tutorialId}/video-guide/file?token=${encodeURIComponent(token)}`;
}
