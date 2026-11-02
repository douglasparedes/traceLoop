import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TutorialStudio from "./TutorialStudio";

const detail = {
  id: "t1", title: "Seal check", status: "done", progress: 100,
  duration_sec: 30, access_token: "tok", video_url: "/api/tutorial/t1/video",
  full_transcript: "Power off. Inspect the seal.",
  transcript_original: "Power off. Inspect the seal.", transcript_corrected: "",
  equipment_name: "", task_description: "", context_notes: "", content_revision: 1,
  timed_segments: [{ text: "Power off.", start: 0, end: 3 }],
  objects: [{ obj_id: 1, label: "seal", status: "ok" }],
  steps: [{ step_number: 1, title: "Power off", summary: "Switch it off.", start: 0, end: 3, objects_used: [] }],
  materials: [], guide_markdown: "# Seal check", guide_format: "work_instruction",
  format_source: "recommended", format_rationale: "Clear steps.", has_guide: true,
  draft_version_id: null, created_at: "2026-10-20T10:00:00", updated_at: "2026-10-20T10:00:00",
};

const stages = [
  { stage: "transcribe", label: "Voice transcription", state: "completed", mode: "simulated", model: "muse-voice-transcribe-1.0", duration_ms: 20, attempts: 1, note: "" },
  { stage: "segment", label: "Component segmentation", state: "needs_review", mode: "live", model: "sam-3.1", duration_ms: 30, attempts: 2, note: "" },
];

function mockAll() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
    const u = String(url);
    let body: unknown = {};
    if (u.endsWith("/api/tutorial/t1")) body = detail;
    else if (u.includes("/stages")) body = { tutorial_id: "t1", job_status: "done", stages };
    else if (u.includes("/content")) body = { tutorial_id: "t1", content_revision: 1, transcript_original: detail.transcript_original, transcript_corrected: "", timed_segments: detail.timed_segments, steps: detail.steps, materials: [], updated_at: detail.updated_at };
    else if (u.includes("/revisions")) body = { tutorial_id: "t1", current_revision: 1, revisions: [] };
    else if (u.includes("/snapshots")) body = { snapshots: [] };
    else if (u.includes("/visuals")) body = { items: [] };
    else if (u.includes("/video-guides")) body = { versions: [] };
    return { ok: true, status: 200, json: async () => body };
  }) as typeof fetch);
}

const item = { id: "t1", title: "Seal check", status: "done", access_token: "tok" } as never;

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Studio processing summary", () => {
  it("renders in Overview alongside aggregate state", async () => {
    mockAll();
    render(<TutorialStudio item={item} onBack={() => undefined} onOpenReview={() => undefined} notify={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Seal check" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "AI processing" })).toBeInTheDocument();
    expect(await screen.findByText("Voice transcription")).toBeInTheDocument();
    const scope = within((await screen.findByText("Voice transcription")).closest("li")!);
    expect(scope.getByText("Simulated")).toBeInTheDocument();
    const seg = within((await screen.findByText("Component segmentation")).closest("li")!);
    expect(seg.getByText("Live")).toBeInTheDocument();
    expect(seg.getByText("Needs review")).toBeInTheDocument();
  });
});
