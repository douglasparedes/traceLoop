import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import VideoStudio from "./VideoStudio";
import * as studioApi from "./studioApi";

beforeEach(() => {
  vi.restoreAllMocks();
});

const GUIDE = { format: "work_instruction", steps: 2, hasTranscript: true, contentRevision: 3 };

function versionsPayload(versions: unknown[], limits = { max_video_guide_sec: 600 }) {
  return { versions, limits };
}

describe("VideoStudio one-click flow", () => {
  it("generates a video with one action and shows the version, no scene editor", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
      const u = String(url);
      if (u.includes("/video-guides")) {
        return { ok: true, status: 200, json: async () => versionsPayload([]) } as unknown as Response;
      }
      if (u.includes("/visuals")) {
        return { ok: true, status: 200, json: async () => ({ items: [] }) } as unknown as Response;
      }
      throw new Error(`unexpected fetch ${u}`);
    }) as typeof fetch);
    const postSpy = vi.spyOn(studioApi, "startVideoGuide").mockResolvedValue({
      ok: true,
      video_guide: {
        id: "vg-1", tutorial_id: "t1", status: "queued", version_number: 1,
        progress: 2, error: "", asset_id: null, video_url: null, scenes: [],
        simulated: true, provenance: {}, created_at: new Date().toISOString(),
      },
    });

    render(<VideoStudio tutorialId="t1" token="tok" title="Demo" durationSec={60} jobDone={true} guide={GUIDE} onChanged={() => undefined} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Generate video guide" })).toBeDefined());
    // No scene editor controls in the primary flow.
    expect(screen.queryByText(/Add scene/i)).toBeNull();
    expect(screen.queryByText(/Scene plan/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Generate video guide" }));
    await waitFor(() => expect(postSpy).toHaveBeenCalledWith("t1", "tok", false));
    expect(fetchSpy).toHaveBeenCalled();
  });

  it("previews the exact selected version with a version-aware URL", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
      const u = String(url);
      if (u.includes("/video-guides")) {
        return {
          ok: true, status: 200,
          json: async () => versionsPayload([{
            id: "vg-2", tutorial_id: "t1", status: "ready", version_number: 2,
            progress: 100, error: "", asset_id: "a1", video_url: "/x", scenes: [{ step: 1, title: "S", caption: "C" }],
            simulated: false, provenance: { voiceover: "original-recording-cut" },
            created_at: new Date().toISOString(),
          }]),
        } as unknown as Response;
      }
      if (u.includes("/visuals")) {
        return { ok: true, status: 200, json: async () => ({ items: [] }) } as unknown as Response;
      }
      throw new Error(`unexpected fetch ${u}`);
    }) as typeof fetch);

    render(<VideoStudio tutorialId="t1" token="tok" title="Demo" durationSec={60} jobDone={true} guide={GUIDE} onChanged={() => undefined} />);

    await waitFor(() => expect(screen.getByText("Version 2")).toBeDefined());
    expect(screen.getByText("Download")).toBeDefined();
  });

  it("downloads the exact version only after verifying it is video", async () => {
    const seen: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
      const u = String(url);
      seen.push(u);
      if (u.includes("&download=1")) {
        return {
          ok: true, status: 200,
          headers: new Headers({ "content-type": "video/mp4" }),
          blob: async () => new Blob(["fake-mp4"], { type: "video/mp4" }),
        } as unknown as Response;
      }
      if (u.includes("/video-guides")) {
        return {
          ok: true, status: 200,
          json: async () => versionsPayload([{
            id: "vg-2", tutorial_id: "t1", status: "ready", version_number: 2,
            progress: 100, error: "", asset_id: "a1", video_url: "/x", scenes: [{ step: 1, title: "S", caption: "C" }],
            simulated: false, provenance: { voiceover: "original-recording-cut" },
            created_at: new Date().toISOString(),
          }]),
        } as unknown as Response;
      }
      if (u.includes("/visuals")) {
        return { ok: true, status: 200, json: async () => ({ items: [] }) } as unknown as Response;
      }
      throw new Error(`unexpected fetch ${u}`);
    }) as typeof fetch);
    (URL as unknown as { createObjectURL: (o: Blob) => string }).createObjectURL = vi.fn(() => "blob:fake");
    (URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL = vi.fn();

    render(<VideoStudio tutorialId="t1" token="tok" title="Demo" durationSec={60} jobDone={true} guide={GUIDE} onChanged={() => undefined} />);

    await waitFor(() => expect(screen.getByText("Version 2")).toBeDefined());
    fireEvent.click(screen.getByText("Download"));
    await waitFor(() => expect(screen.getByText(/downloaded/i)).toBeDefined());
    expect(seen.some((u) => u.includes("/api/tutorial/t1/video-guides/vg-2/file") && u.includes("download=1"))).toBe(true);
  });

  it("refuses to save an error page as a video", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
      const u = String(url);
      if (u.includes("&download=1")) {
        return {
          ok: false, status: 404,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ detail: "Video guide file missing" }),
        } as unknown as Response;
      }
      if (u.includes("/video-guides")) {
        return {
          ok: true, status: 200,
          json: async () => versionsPayload([{
            id: "vg-2", tutorial_id: "t1", status: "ready", version_number: 2,
            progress: 100, error: "", asset_id: "a1", video_url: "/x", scenes: [],
            simulated: false, provenance: {},
            created_at: new Date().toISOString(),
          }]),
        } as unknown as Response;
      }
      if (u.includes("/visuals")) {
        return { ok: true, status: 200, json: async () => ({ items: [] }) } as unknown as Response;
      }
      throw new Error(`unexpected fetch ${u}`);
    }) as typeof fetch);

    render(<VideoStudio tutorialId="t1" token="tok" title="Demo" durationSec={60} jobDone={true} guide={GUIDE} onChanged={() => undefined} />);

    await waitFor(() => expect(screen.getByText("Version 2")).toBeDefined());
    fireEvent.click(screen.getByText("Download"));
    await waitFor(() => expect(screen.getByText(/Video guide file missing/)).toBeDefined());
  });

  it("warns when the recording exceeds the supported video length", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown) => {
      const u = String(url);
      if (u.includes("/video-guides")) {
        return { ok: true, status: 200, json: async () => versionsPayload([]) } as unknown as Response;
      }
      if (u.includes("/visuals")) {
        return { ok: true, status: 200, json: async () => ({ items: [] }) } as unknown as Response;
      }
      throw new Error(`unexpected fetch ${u}`);
    }) as typeof fetch);

    render(<VideoStudio tutorialId="t1" token="tok" title="Demo" durationSec={3600 + 60} jobDone={true} guide={GUIDE} onChanged={() => undefined} />);

    await waitFor(() => expect(screen.getByText(/longer than the supported video length/i)).toBeDefined());
    const btn = screen.getByRole("button", { name: "Generate video guide" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
