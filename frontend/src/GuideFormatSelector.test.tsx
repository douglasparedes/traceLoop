import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GuideFormatSelector from "./GuideFormatSelector";

const FORMATS = [
  { id: "work_instruction", name: "Illustrated Work Instruction", tagline: "Visual, numbered instructions.", best_for: "Technicians in a hurry." },
  { id: "reference_manual", name: "Reference Manual", tagline: "Structured reference.", best_for: "Deep dives." },
  { id: "interactive", name: "Interactive Guided Execution", tagline: "Step-by-step workflow.", best_for: "Field execution." },
];

function mockFetch(handler: (url: string, init?: RequestInit) => unknown) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: unknown) => ({
    ok: true,
    status: 200,
    json: async () => handler(String(url), (init || {}) as RequestInit),
  })) as typeof fetch);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("GuideFormatSelector", () => {
  it("shows the AI recommendation with rationale and scores", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/tutorial/formats")) return { formats: FORMATS };
      return { format: "work_instruction", source: "recommended", rationale: "Recommended because 3 distinct steps.", scores: { work_instruction: 4, reference_manual: 2, interactive: 3 } };
    });
    render(<GuideFormatSelector tutorialId="t1" token="tok" current="" onGenerated={() => {}} />);
    expect(await screen.findByText("Illustrated Work Instruction")).toBeInTheDocument();
    expect(await screen.findByText("AI recommended")).toBeInTheDocument();
    expect(await screen.findByText(/Recommended because 3 distinct steps/)).toBeInTheDocument();
    expect(await screen.findByText(/work instruction: 4/)).toBeInTheDocument();
  });

  it("lets an explicit user choice win and persists it before generating", async () => {
    const calls: string[] = [];
    mockFetch((url, init) => {
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.endsWith("/api/tutorial/formats")) return { formats: FORMATS };
      if (url.endsWith("/recommendation")) return { format: "work_instruction", source: "recommended", rationale: "Recommended because steps.", scores: {} };
      if (url.endsWith("/guide")) return { ok: true, snapshot_id: "s1", format: "interactive", format_source: "user", rationale: "x", draft_version_id: null, draft_status: null, markdown_chars: 10 };
      if (url.endsWith("/format")) return { ok: true, format: "interactive" };
      return {};
    });
    const onGenerated = vi.fn();
    const user = userEvent.setup();
    render(<GuideFormatSelector tutorialId="t1" token="tok" current="" onGenerated={onGenerated} />);
    await screen.findByText("Interactive Guided Execution");
    await user.click(screen.getByRole("radio", { name: /Interactive Guided Execution/ }));
    await user.click(screen.getByRole("button", { name: /Generate guide/ }));
    await waitFor(() => expect(onGenerated).toHaveBeenCalledWith("s1"));
    expect(calls.some((c) => c.includes("PUT") && c.endsWith("/api/tutorial/t1/format"))).toBe(true);
    expect(calls.some((c) => c.includes("POST") && c.endsWith("/api/tutorial/t1/guide"))).toBe(true);
    expect(await screen.findByText(/New interactive version saved/)).toBeInTheDocument();
  });

  it("reports generation failure honestly without claiming success", async () => {
    mockFetch((url) => {
      if (url.endsWith("/api/tutorial/formats")) return { formats: FORMATS };
      if (url.endsWith("/recommendation")) return { format: "work_instruction", source: "recommended", rationale: "r", scores: {} };
      throw new Error("503 Service Unavailable");
    });
    const user = userEvent.setup();
    render(<GuideFormatSelector tutorialId="t1" token="tok" current="" onGenerated={() => {}} />);
    await screen.findByText("Illustrated Work Instruction");
    await user.click(screen.getByRole("button", { name: /Generate guide/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/503 Service Unavailable/);
  });

  it("marks the current format and skips re-selecting it", async () => {
    const calls: string[] = [];
    mockFetch((url, init) => {
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.endsWith("/api/tutorial/formats")) return { formats: FORMATS };
      if (url.endsWith("/recommendation")) return { format: "reference_manual", source: "user", rationale: "You selected it.", scores: {} };
      if (url.endsWith("/guide")) return { ok: true, snapshot_id: "s9", format: "reference_manual", format_source: "user", rationale: "x", draft_version_id: null, draft_status: null, markdown_chars: 5, duplicate: true };
      return {};
    });
    const user = userEvent.setup();
    render(<GuideFormatSelector tutorialId="t1" token="tok" current="reference_manual" onGenerated={() => {}} />);
    const currentRadio = await screen.findByRole("radio", {
      name: (name) => name.includes("Reference Manual") && name.includes("Current"),
    });
    expect(currentRadio).toHaveAttribute("aria-checked", "true");
    expect(within(currentRadio as HTMLElement).getByText("Current")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Reference Manual/ }));
    await user.click(screen.getByRole("button", { name: /Generate new version/ }));
    expect(await screen.findByText(/already exists.*instead of duplicating/i)).toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("PUT"))).toBe(false);
  });
});
