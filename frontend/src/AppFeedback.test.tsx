import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

vi.mock("./db", () => ({
  idb: {
    get: async () => undefined,
    all: async () => [],
    put: async () => undefined,
    del: async () => undefined,
    clear: async () => undefined,
  },
  uuid: () => "test-id",
}));

const steps = [
  { id: "s1", step_order: 1, title: "Isolate power", instruction: "Switch it off.", expected_result: null, required_tools: [], evidence_refs: [], visual_refs: [], verification_notes: null },
  { id: "s2", step_order: 2, title: "Inspect seal", instruction: "Look closely.", expected_result: null, required_tools: [], evidence_refs: [], visual_refs: [], verification_notes: null },
];

const posts: { url: string; body: unknown }[] = [];
let postedFeedback: { event_id: string; payload: Record<string, unknown> }[] = [];

function mockApi() {
  posts.length = 0;
  postedFeedback = [];
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: unknown) => {
    const u = String(url);
    const method = (init as RequestInit | undefined)?.method || "GET";
    let body: unknown = {};
    if (u.endsWith("/api/auth/status")) body = { auth_enabled: false };
    else if (u.endsWith("/api/procedures")) body = [];
    else if (u.endsWith("/api/jobs")) body = [{ id: "j1", procedure_title: "Seal check", status: "finished", outcome: "completed", technician_id: "tech", started_at: "2026-01-01T00:00:00", ended_at: "2026-01-01T00:05:00", events: 2 }];
    else if (u.includes("/api/jobs/j1/feedback")) {
      if (method === "POST") {
        const fb = JSON.parse(String((init as { body?: string }).body || "{}"));
        posts.push({ url: u, body: fb });
        postedFeedback = [{ event_id: "fb1", payload: { technician_id: "tech", procedure_version_id: "v1", ...fb } }];
        return { ok: true, status: 200, json: async () => ({ ok: true, event_id: "fb1", superseded: 0 }) };
      }
      body = { job_id: "j1", feedback: postedFeedback };
    } else if (u.includes("/api/jobs/j1/propose-improvement")) {
      posts.push({ url: u, body: {} });
      return {
        ok: true, status: 200,
        json: async () => ({
          ok: true, version_id: "v2",
          changes: [{ step_order: 2, field: "verification_notes", before: "", after: "Field report: Which screw?", reason: "marked confusing", confidence: "low" }],
          simulated: true, summary: "Simulated proposal",
        }),
      };
    } else if (u.includes("/api/jobs/j1")) {
      body = { id: "j1", status: "finished", outcome: "completed", procedure_version_id: "v1", started_at: "2026-01-01T00:00:00", ended_at: "2026-01-01T00:05:00", events: [], evidence: [] };
    } else if (u.includes("/api/procedure-versions/v2")) {
      body = {
        id: "v2", procedure_id: "p1", version_number: 2, status: "draft", summary: "Field-feedback proposal", prerequisites: "",
        source_evidence: {
          proposal: {
            job_id: "j1", base_version_id: "v1", base_version_number: 1, base_changed_since_job: false,
            feedback_event_id: "fb1",
            feedback_summary: { step_outcomes: [{ step_id: "s2", status: "confusing", note: "Which screw do you mean?" }], overall: "" },
            changes: [{ step_order: 2, field: "verification_notes", before: "", after: "Field report: Which screw?", reason: "marked confusing", confidence: "low" }],
            simulated: true, model: "muse-spark-1.3", note: "Simulated proposal",
          },
        },
        ai_model: "muse-spark-1.3", ai_simulated: true, created_by: "rev",
        steps,
      };
    } else if (u.includes("/api/procedure-versions/v1")) {
      body = { id: "v1", procedure_id: "p1", version_number: 1, status: "approved", summary: "s", prerequisites: "", source_evidence: {}, steps };
    }
    return { ok: true, status: 200, json: async () => body };
  }) as typeof fetch);
}

beforeEach(() => {
  vi.restoreAllMocks();
  try { localStorage.clear(); localStorage.setItem("fg-role", "reviewer"); } catch { /* noop */ }
});

describe("field feedback loop", () => {
  it("submits structured feedback then creates an improvement proposal draft", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await user.click(within(nav).getByRole("button", { name: /^Activity/ }));
    await user.click(await screen.findByRole("button", { name: /View details/ }));
    expect(await screen.findByText("How did each step go?")).toBeInTheDocument();
    // Mark step 2 confusing with a note.
    const group = screen.getByRole("group", { name: "Outcome for step 2" });
    await user.click(within(group).getByRole("button", { name: "confusing" }));
    await user.type(screen.getByLabelText(/What went wrong on step 2/), "Which screw do you mean?");
    await user.click(screen.getByRole("button", { name: "Submit feedback" }));
    await waitFor(() => expect(posts.some((p) => p.url.includes("/feedback"))).toBe(true));
    const fb = posts.find((p) => p.url.includes("/feedback"))!.body as { step_outcomes: { step_id: string; status: string; note: string }[] };
    expect(fb.step_outcomes.find((o) => o.step_id === "s2")).toMatchObject({ status: "confusing", note: "Which screw do you mean?" });
    expect(fb.step_outcomes.find((o) => o.step_id === "s1")!.status).toBe("ok");
    // Reviewer turns the recorded feedback into a draft proposal and lands in Review.
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(await screen.findByRole("button", { name: "Create improvement proposal" }));
    await waitFor(() => expect(posts.some((p) => p.url.includes("/propose-improvement"))).toBe(true));
    expect(await screen.findByText(/Field-feedback proposal/)).toBeInTheDocument();
    expect(screen.getByText(/Field report: Which screw/)).toBeInTheDocument();
    expect(screen.getByText(/simulated analysis/)).toBeInTheDocument();
  });
});
