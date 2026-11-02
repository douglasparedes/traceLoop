import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TutorialLibrary from "./TutorialLibrary";

const items = [
  { id: "t1", title: "Reseat the pump seal", status: "done", access_token: "tok1", actor: "tech", duration_sec: 125, created_at: "2026-10-20T10:00:00", draft_version_id: "v1", objects_total: 2, objects_unresolved: 0, has_guide: true },
  { id: "t2", title: "Failed upload demo", status: "error", access_token: "tok2", actor: "tech", duration_sec: 0, created_at: "2026-10-21T10:00:00", draft_version_id: null, objects_total: 0, objects_unresolved: 0, has_guide: false },
];

function mockList() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
    const u = String(url);
    const params = new URL(u, "http://localhost").searchParams;
    const q = (params.get("q") || "").toLowerCase();
    const status = params.get("status") || "";
    let list = items;
    if (q) list = list.filter((t) => t.title.toLowerCase().includes(q));
    if (status) list = list.filter((t) => (status === "done" ? t.status === "done" : t.status !== "done"));
    return {
      ok: true,
      status: 200,
      json: async () => (u.includes("/api/tutorial?") ? { total: list.length, items: list } : {}),
    };
  }) as typeof fetch);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("TutorialLibrary", () => {
  it("lists tutorials as compact rows with status and actions", async () => {
    mockList();
    const onOpen = vi.fn();
    render(<TutorialLibrary onOpen={onOpen} />);
    expect(await screen.findByText("Reseat the pump seal")).toBeInTheDocument();
    expect(screen.getByText("Failed upload demo")).toBeInTheDocument();
    expect(document.querySelector(".tut-row .badge.ok")).toHaveTextContent("Ready");
    const rows = screen.getAllByRole("button", { name: /Open .*Tutorial Studio/ });
    expect(rows).toHaveLength(2);
    const user = userEvent.setup();
    const row = screen.getByRole("button", { name: /Open Reseat the pump seal/ }).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "Open" }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "t1" }));
  });

  it("filters by search and status", async () => {
    mockList();
    render(<TutorialLibrary onOpen={() => undefined} />);
    await screen.findByText("Reseat the pump seal");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Failed" }));
    await waitFor(() => expect(screen.queryByText("Reseat the pump seal")).not.toBeInTheDocument());
    expect(screen.getByText("Failed upload demo")).toBeInTheDocument();
  });

  it("confirms before deleting and calls the API", async () => {
    const seen: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: unknown) => {
      const u = String(url);
      if ((init as RequestInit | undefined)?.method === "DELETE") seen.push(u);
      return {
        ok: true,
        status: 200,
        json: async () => (u.includes("/api/tutorial?") ? { total: 2, items } : {}),
      };
    }) as typeof fetch);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<TutorialLibrary onOpen={() => undefined} />);
    await screen.findByText("Reseat the pump seal");
    const user = userEvent.setup();
    const row = screen.getByRole("button", { name: /Open Reseat the pump seal/ }).closest("li")!;
    await user.click(within(row).getByRole("button", { name: /Delete Reseat/ }));
    await waitFor(() => expect(seen.some((u) => u.includes("/api/tutorial/t1"))).toBe(true));
  });

  it("shows an honest error when the library is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async () => {
      throw new Error("offline");
    }) as typeof fetch);
    render(<TutorialLibrary onOpen={() => undefined} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/i);
  });
});
