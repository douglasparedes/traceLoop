import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import ProcessingSummary from "./ProcessingSummary";

const stages = [
  { stage: "ingest", label: "Source ingestion", state: "completed", mode: "live", model: "", duration_ms: 15, attempts: 2, note: "" },
  { stage: "transcribe", label: "Voice transcription", state: "completed", mode: "simulated", model: "muse-voice-transcribe-1.0", duration_ms: 20, attempts: 1, note: "no key" },
  { stage: "segment", label: "Component segmentation", state: "needs_review", mode: "live", model: "sam-3.1", duration_ms: 30, attempts: 3, note: "tap to correct" },
  { stage: "draft", label: "Review draft", state: "pending", mode: "unknown", model: "", duration_ms: 0, attempts: 0, note: "" },
];

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("ProcessingSummary", () => {
  it("shows per-stage state and live/simulated mode distinctly", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: unknown) => ({
      ok: true,
      status: 200,
      json: async () => ({ tutorial_id: "t1", job_status: "done", stages }),
    })) as typeof fetch);
    render(<ProcessingSummary tutorialId="t1" token="tok" />);
    expect(await screen.findByText("Source ingestion")).toBeInTheDocument();
    expect(await screen.findAllByText("Voice transcription")).toHaveLength(2); // row + technical details
    const rows = screen.getAllByRole("listitem");
    const rowText = (label: string) => rows.find((li) => li.textContent?.includes(label))!.textContent!;
    expect(rowText("Voice transcription")).toMatch(/Simulated/);
    expect(rowText("Component segmentation")).toMatch(/Live/);
    expect(rowText("Component segmentation")).toMatch(/Needs review/);
    expect(rowText("Review draft")).toMatch(/Pending/);
    // Technical details hidden behind a collapsed expander, not dumped on technicians.
    const details = screen.getByText("Stage details").closest("details")!;
    expect(details).not.toHaveAttribute("open");
  });

  it("reports load failure honestly with retry", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async () => {
      throw new Error("offline");
    }) as typeof fetch);
    render(<ProcessingSummary tutorialId="t1" token="tok" />);
    expect(await screen.findByText(/Processing summary unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
  });
});
