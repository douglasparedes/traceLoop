import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
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

const proc = {
  id: "p1", title: "Pump seal check", favorite: false,
  updated_at: "2026-01-01T00:00:00Z", asset_type: "pump",
  versions: [{ id: "v1", version_number: 1, status: "approved" }],
  approved_version_id: "v1", has_pending_review: false,
};

function mockApi(jobs: unknown[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
    const u = String(url);
    let body: unknown = {};
    if (u.endsWith("/api/auth/status")) body = { auth_enabled: false };
    else if (u.endsWith("/api/procedures")) body = [proc];
    else if (u.endsWith("/api/jobs")) body = jobs;
    else if (u.includes("/api/procedure-versions/v1")) body = { id: "v1", procedure_id: "p1", version_number: 1, status: "approved", summary: "", prerequisites: "", source_evidence: {}, steps: [], created_by: "t" };
    else if (u.includes("/api/tutorial?")) body = { total: 0, items: [] };
    return { ok: true, status: 200, json: async () => body };
  }) as typeof fetch);
}

beforeEach(() => {
  vi.restoreAllMocks();
  try { localStorage.clear(); } catch { /* noop */ }
});

describe("procedure completion state", () => {
  it("shows Completed and Run again after a finished execution, not a bare available job", async () => {
    mockApi([{
      id: "j1", procedure_id: "p1", procedure_version_id: "v1",
      procedure_title: "Pump seal check", status: "finished", outcome: "completed",
      technician_id: "demo-tech", started_at: "2026-01-01T00:00:00Z",
      ended_at: "2026-01-02T00:00:00Z", events: 5,
    }]);
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await user.click(within(nav).getByRole("button", { name: /^Procedures/ }));
    expect(await screen.findByText(/Completed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run again/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Start job$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View last execution/ })).toBeInTheDocument();
  });

  it("shows Start job when no execution exists", async () => {
    mockApi([]);
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await user.click(within(nav).getByRole("button", { name: /^Procedures/ }));
    expect(await screen.findByRole("button", { name: /^Start job$/ })).toBeInTheDocument();
  });
});
