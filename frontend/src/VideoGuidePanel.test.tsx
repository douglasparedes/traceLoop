import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VideoGuidePanel from "./VideoGuidePanel";

const readyGuide = {
  id: "vg1", tutorial_id: "t1", status: "ready", progress: 100, error: "",
  asset_id: "a1", video_url: "/api/tutorial/t1/video-guide/file",
  scenes: [{ step: 1, title: "Turn the knob", caption: "Do it now." }],
  simulated: true, provenance: {}, created_at: new Date().toISOString(),
};

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

describe("VideoGuidePanel", () => {
  it("starts generation and shows progress until ready", async () => {
    let calls = 0;
    let posted = false;
    mockFetch((url, init) => {
      const isPost = url.endsWith("/video-guide") && (init as RequestInit | undefined)?.method === "POST";
      if (isPost) {
        posted = true;
        calls = 0;
        return { ok: true, video_guide: { ...readyGuide, status: "rendering", progress: 40, video_url: null }, duplicate: false };
      }
      if (!posted) return { status: "none", video_guide: null };
      calls++;
      if (calls <= 3) return { status: "rendering", video_guide: { ...readyGuide, status: "rendering", progress: 40, video_url: null } };
      return { status: "ready", video_guide: readyGuide };
    });
    const user = userEvent.setup();
    render(<VideoGuidePanel tutorialId="t1" token="tok" jobDone={true} />);
    await screen.findByText(/never synthesized/i);
    await user.click(screen.getByRole("button", { name: /Generate video guide/ }));
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
  });

  it("plays the finished video with simulated labelling", async () => {
    mockFetch(() => ({ status: "ready", video_guide: readyGuide }));
    render(<VideoGuidePanel tutorialId="t1" token="tok" jobDone={true} />);
    const video = await screen.findByLabelText(/Generated video guide/i);
    expect(video.tagName).toBe("VIDEO");
    expect(video.getAttribute("src")).toContain("token=tok");
    expect(await screen.findByText(/simulated plan/i)).toBeInTheDocument();
  });

  it("blocks generation while the tutorial is still processing", async () => {
    mockFetch(() => ({ status: "none", video_guide: null }));
    render(<VideoGuidePanel tutorialId="t1" token="tok" jobDone={false} />);
    await screen.findByText(/never synthesized/i);
    expect(screen.getByRole("button", { name: /Generate video guide/ })).toBeDisabled();
  });

  it("reports generation failure honestly", async () => {
    mockFetch((url, init) => {
      if (url.endsWith("/video-guide") && init?.method === "POST") throw new Error("503 Service Unavailable");
      return { status: "none", video_guide: null };
    });
    const user = userEvent.setup();
    render(<VideoGuidePanel tutorialId="t1" token="tok" jobDone={true} />);
    await user.click(await screen.findByRole("button", { name: /Generate video guide/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/503/);
  });
});
