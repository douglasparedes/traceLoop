import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import type { LocalJob, Version } from "./types";

vi.mock("./db", () => {
  const stores = new Map<string, Map<string, unknown>>();
  const table = (s: string) => {
    if (!stores.has(s)) stores.set(s, new Map());
    return stores.get(s)!;
  };
  return {
    idb: {
      put: async (store: string, key: string, value: unknown) => { table(store).set(key, value); },
      get: async <T,>(store: string, key: string): Promise<T | undefined> =>
        table(store).get(key) as T | undefined,
      all: async <T,>(store: string): Promise<T[]> => [...table(store).values()] as T[],
      del: async (store: string, key: string) => { table(store).delete(key); },
      clear: async (store: string) => { table(store).clear(); },
    },
    uuid: (() => { let n = 0; return () => `uuid-${++n}`; })(),
    __stores: stores,
  };
});

const version = (over: Partial<Version> = {}): Version => ({
  id: "v1",
  procedure_id: "p1",
  version_number: 3,
  status: "approved",
  summary: "Reseat the harness",
  prerequisites: "",
  source_evidence: {},
  ai_model: null,
  ai_simulated: false,
  created_by: "demo-tech",
  reviewed_by: "demo-reviewer",
  review_comment: null,
  steps: [1, 2, 3].map((n) => ({
    id: `s${n}`,
    step_order: n,
    title: `Step ${n}`,
    instruction: `Do step ${n}.`,
    required_tools: [],
    evidence_refs: [],
    visual_refs: [],
  })),
  ...over,
});

const activeJob = (states: Record<string, "done" | "skipped" | "blocked"> = {}): LocalJob => ({
  id: "job-1",
  procedure_id: "p1",
  procedure_version_id: "v1",
  title: "Reseat the harness",
  current: 0,
  stepStates: states,
  started_at: new Date().toISOString(),
  finished: false,
});

let finalizeCalls = 0;
let postedEvents: { event_id: string; event_type: string; step_id: string | null }[] = [];

function mockApi(state: "pending" | "finished" = "pending") {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method || "GET").toUpperCase();
    let body: unknown = {};
    if (u.endsWith("/api/auth/status")) body = { auth_enabled: false };
    else if (u.endsWith("/api/procedures")) body = [];
    else if (u.endsWith("/api/jobs") && method === "GET") body = [];
    else if (u.includes("/api/procedure-versions/v1/offline-grant")) body = { offline_grant: "g" };
    else if (u.includes("/api/procedure-versions/v1")) body = version();
    else if (u.includes("/api/jobs/job-1/state")) {
      body = {
        job_id: "job-1", status: state === "finished" ? "finished" : "active", outcome: null,
        procedure_version_id: "v1", current: null, counts: { total: 3, completed: 0, skipped: 0, blocked: 0 },
        missing_step_orders: [1, 2, 3], events: 0, last_activity: null, finished: state === "finished",
        ended_at: null,
        steps: [1, 2, 3].map((n) => ({ step_id: `s${n}`, step_order: n, title: `Step ${n}`, state: "pending" })),
      };
    } else if (u.includes("/api/jobs/job-1/evidence")) body = { evidence: [] };
    else if (u.includes("/api/jobs/job-1/finalize") && method === "POST") {
      finalizeCalls++;
      body = { ok: true, outcome: "completed" };
    } else if (u.includes("/api/sync/events")) {
      const payload = JSON.parse(String(init?.body || '{"events":[]}')) as { events: typeof postedEvents };
      postedEvents.push(...payload.events);
      body = { acknowledged: payload.events.map((e) => e.event_id), duplicates: [], failed: [] };
    }
    return { ok: true, status: 200, json: async () => body };
  }) as unknown as typeof fetch);
}

async function seed(jobStates: Record<string, "done" | "skipped" | "blocked"> = {}) {
  const { idb } = (await import("./db")) as unknown as {
    idb: { put(s: string, k: string, v: unknown): Promise<void> };
  };
  await idb.put("jobs", "active", activeJob(jobStates));
  await idb.put("versions", "v1", version());
}

beforeEach(async () => {
  vi.restoreAllMocks();
  finalizeCalls = 0;
  postedEvents = [];
  const { __stores } = (await import("./db")) as unknown as { __stores: Map<string, Map<string, unknown>> };
  __stores.clear();
  try { localStorage.clear(); } catch { /* noop */ }
});

describe("guided execution primary action", () => {
  it("advances steps with one Next action and finishes on the last step", async () => {
    mockApi();
    await seed();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Resume step 1/ }));
    // Primary action advances the frontier step.
    expect(await screen.findByRole("button", { name: /Next step/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Next step/ }));
    expect(await screen.findByText("Step 2 of 3")).toBeInTheDocument();
    // Tracker reflects recorded state, not the view index.
    const track = document.querySelector(".seg-progress-track");
    expect(track?.children[0].className).toMatch(/on-done/);
    expect(track?.children[1].className).not.toMatch(/on/);
    await user.click(screen.getByRole("button", { name: /Next step/ }));
    // Final step offers Finish, not another Next.
    await user.click(screen.getByRole("button", { name: /Next step/ }));
    expect(await screen.findByRole("button", { name: /Finish job/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Next step/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Finish job/ }));
    expect(finalizeCalls).toBe(1);
    await vi.waitFor(() => expect(document.body.textContent).toMatch(/Job finished/));
    // Server-confirmed finalization settles the local queue immediately:
    // no stuck finish event, no duplicate finish on next sync.
    const { idb } = (await import("./db")) as unknown as {
      idb: { get<T>(s: string, k: string): Promise<T | undefined> };
    };
    const fin = await idb.get<{ sync_status: string }>("events", "evt:job-1:finish");
    expect(fin?.sync_status).toBe("synced");
    const pendingFin = await idb.get<unknown[]>("meta", "pending-finishes");
    expect(pendingFin === undefined || pendingFin.length === 0).toBe(true);
  });

  it("blocks double-submits: rapid double click records one event", async () => {
    mockApi();
    await seed();
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Resume step 1/ }));
    const next = await screen.findByRole("button", { name: /Next step/ });
    fireEvent.click(next);
    fireEvent.click(next);
    await screen.findByText("Step 2 of 3");
    const { idb } = (await import("./db")) as unknown as {
      idb: { all<T>(s: string): Promise<T[]> };
    };
    const evs = (await idb.all<{ event_id: string }>("events")).filter((e) => e.event_id.includes("s1"));
    expect(evs).toHaveLength(1);
  });

  it("blocks a step through the incident flow and resumes it", async () => {
    mockApi();
    await seed();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Resume step 1/ }));
    await user.click(await screen.findByRole("button", { name: /Report this step as blocked/ }));
    await user.type(await screen.findByLabelText(/Technician notes/), "Clip jammed");
    await user.click(await screen.findByRole("button", { name: /Log incident/ }));
    // Frontier advanced past the halted step; the summary records the block.
    expect(await screen.findByText(/1 blocked/)).toBeInTheDocument();
    // Previous navigates back without undoing: the recorded state shows.
    await user.click(await screen.findByRole("button", { name: /Previous/ }));
    expect(await screen.findByText((_, el) => el?.textContent === "Step 1: blocked")).toBeInTheDocument();
    // Resume returns the step to the workable set with history preserved.
    await user.click(await screen.findByRole("button", { name: /resume step/i }));
    expect(await screen.findByRole("button", { name: /Next step/ })).toBeInTheDocument();
  });

  it("counts skipped steps as exceptions, not completions", async () => {
    mockApi();
    await seed();
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Resume step 1/ }));
    await user.click(await screen.findByRole("button", { name: /Skip step/ }));
    expect(await screen.findByRole("button", { name: /Next step/ })).toBeInTheDocument();
    expect(screen.getByText(/1 skipped/)).toBeInTheDocument();
  });

  it("recovers an all-recorded job as Finish instead of re-recording", async () => {
    mockApi("pending");
    await seed({ s1: "done", s2: "done", s3: "skipped" });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Resume step 3/ }));
    expect(await screen.findByRole("button", { name: /Finish job/ })).toBeInTheDocument();
  });
});
