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

const content = {
  tutorial_id: "t1", content_revision: 1,
  transcript_original: detail.transcript_original, transcript_corrected: "",
  timed_segments: detail.timed_segments, steps: detail.steps, materials: [],
  updated_at: detail.updated_at,
};

function mockStudio(putCalls: unknown[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: unknown) => {
    const u = String(url);
    const method = (init as RequestInit | undefined)?.method || "GET";
    if (method === "PUT" || method === "POST") {
      putCalls.push({ url: u, method, body: JSON.parse(String((init as { body?: string }).body || "{}")) });
      if (u.endsWith("/api/tutorial/t1")) return { ok: true, status: 200, json: async () => ({ ...detail, title: "x" }) };
      return { ok: true, status: 200, json: async () => ({ ok: true, content_revision: 2, revision_number: 2, touched: ["steps"] }) };
    }
    let body: unknown = {};
    if (u.endsWith("/api/tutorial/t1")) body = detail;
    else if (u.includes("/content")) body = content;
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

describe("TutorialStudio", () => {
  it("shows overview with save state and five editing tabs", async () => {
    mockStudio([]);
    const user = userEvent.setup();
    render(<TutorialStudio item={item} onBack={() => undefined} onOpenReview={() => undefined} notify={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Seal check" })).toBeInTheDocument();
    for (const tab of ["Overview", "Content", "Guide", "Video", "Visuals"]) {
      expect(screen.getByRole("tab", { name: tab })).toBeInTheDocument();
    }
    expect(screen.getByText(/original video · immutable/i)).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Content" }));
    expect(await screen.findByRole("heading", { name: "Transcript" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Steps \(1\)/ })).toBeInTheDocument();
  });

  it("saves overview metadata through the versioned endpoint", async () => {
    const puts: unknown[] = [];
    mockStudio(puts);
    const notify = vi.fn();
    const user = userEvent.setup();
    render(<TutorialStudio item={item} onBack={() => undefined} onOpenReview={() => undefined} notify={notify} />);
    await screen.findByRole("heading", { name: "Seal check" });
    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Seal check v2");
    await user.click(screen.getByRole("button", { name: /Save overview/ }));
    await waitFor(() => expect(puts.some((p) => String((p as { url: string }).url).endsWith("/api/tutorial/t1"))).toBe(true));
    expect(notify).toHaveBeenCalledWith(expect.stringMatching(/saved/i), "ok");
  });

  it("warns before abandoning unsaved changes", async () => {
    mockStudio([]);
    const onBack = vi.fn();
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TutorialStudio item={item} onBack={onBack} onOpenReview={() => undefined} notify={() => undefined} />);
    await screen.findByRole("heading", { name: "Seal check" });
    await user.type(screen.getByLabelText("Title"), "!");
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    await user.click(tabs[1]);
    expect(confirm).toHaveBeenCalled();
    expect(onBack).not.toHaveBeenCalled();
    // Still on Overview: transcript editor not shown.
    expect(screen.queryByRole("heading", { name: "Transcript" })).not.toBeInTheDocument();
  });
});
