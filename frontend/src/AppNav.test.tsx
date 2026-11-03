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

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
    const u = String(url);
    let body: unknown = {};
    if (u.endsWith("/api/auth/status")) body = { auth_enabled: false };
    else if (u.endsWith("/api/procedures")) body = [];
    else if (u.endsWith("/api/jobs")) body = [];
    else if (u.includes("/api/tutorial?")) body = { total: 0, items: [] };
    return { ok: true, status: 200, json: async () => body };
  }) as typeof fetch);
}

beforeEach(() => {
  vi.restoreAllMocks();
  try { localStorage.clear(); } catch { /* noop */ }
});

describe("primary navigation", () => {
  it("shows four primary destinations and groups the rest as secondary", async () => {
    mockApi();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    const primary = ["Workbench", "Procedures", "Tutorials", "Activity"];
    for (const label of primary) {
      expect(within(nav).getByRole("button", { name: new RegExp(`^${label}`) })).toBeInTheDocument();
    }
    // Secondary destinations stay reachable but do not compete as primary.
    expect(within(nav).getByRole("button", { name: /^Review/ })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /^Manuals/ })).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: /^Settings/ })).toBeInTheDocument();
  });

  it("opens Tutorials as record-a-tutorial plus a persistent library", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await user.click(within(nav).getByRole("button", { name: /^Tutorials/ }));
    expect(await screen.findByRole("heading", { name: "Tutorials" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Record a tutorial" })).toBeInTheDocument();
    expect(screen.getByText(/Processing runs on the server after upload/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Hide recorder/ })).toBeInTheDocument();
  });

  it("has no Quick capture or Live mode switcher", async () => {
    mockApi();
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await user.click(within(nav).getByRole("button", { name: /^Tutorials/ }));
    await screen.findByRole("heading", { name: "Tutorials" });
    expect(screen.queryByRole("button", { name: /Quick capture/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Live$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Capture mode/ })).not.toBeInTheDocument();
  });

  it("workbench groups active work, attention, ready procedures, and completed jobs", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
      const u = String(url);
      let body: unknown = {};
      if (u.endsWith("/api/auth/status")) body = { auth_enabled: false };
      else if (u.endsWith("/api/procedures")) body = [{
        id: "p1", title: "Reseat the seal", favorite: false, updated_at: "2026-10-20T10:00:00",
        asset_type: "Pump", approved_version_id: "v1", has_pending_review: false,
        versions: [{ id: "v1", version_number: 2, status: "approved" }, { id: "v2", version_number: 3, status: "draft" }],
      }];
      else if (u.endsWith("/api/jobs")) body = [
        { id: "j1", procedure_title: "Reseat the seal", status: "finished", outcome: "completed", started_at: "2026-10-20T10:00:00", events: 5 },
      ];
      else if (u.includes("/api/tutorial?")) body = { total: 0, items: [] };
      return { ok: true, status: 200, json: async () => body };
    }) as typeof fetch);
    render(<App />);
    // Sectioned, predictable hierarchy with consistent status language.
    expect(await screen.findByRole("region", { name: "My active work" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Needs attention" })).toBeInTheDocument();
    expect(screen.getByText(/All clear/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Ready to start" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start job" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View procedure/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recently completed" })).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.queryByText("Pass")).not.toBeInTheDocument();
  });
});
