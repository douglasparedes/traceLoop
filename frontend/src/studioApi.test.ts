import { describe, expect, it, vi, beforeEach } from "vitest";
import { sceneRange, sceneStep, videoVersionFileUrl, fetchVideoVersions, saveScenePlan } from "./studioApi";

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

describe("studioApi", () => {
  it("reads scene ranges with legacy step/start/end keys", () => {
    expect(sceneRange({ title: "A", audio_start: 1.5, audio_end: 4 })).toEqual({ start: 1.5, end: 4 });
    expect(sceneRange({ title: "B", start: 2, end: 6 })).toEqual({ start: 2, end: 6 });
    expect(sceneRange({ title: "C" })).toEqual({ start: 0, end: 0 });
    expect(sceneStep({ title: "A", step_number: 3 }, 1)).toBe(3);
    expect(sceneStep({ title: "B", step: 2 }, 1)).toBe(2);
    expect(sceneStep({ title: "C" }, 7)).toBe(7);
  });

  it("builds a token-bound per-version file URL", () => {
    const url = videoVersionFileUrl("tut-1", "vg-9", "tok+en/secret");
    expect(url).toContain("/api/tutorial/tut-1/video-guides/vg-9/file");
    expect(url).toContain("token=tok%2Ben%2Fsecret");
  });

  it("fetches video version history for the studio", async () => {
    mockFetch((url) => {
      expect(url).toContain("/api/tutorial/t1/video-guides");
      return { versions: [{ id: "v1", version_number: 1, status: "ready", scenes: [] }] };
    });
    const vers = await fetchVideoVersions("t1", "tok");
    expect(vers).toHaveLength(1);
    expect(vers[0].version_number).toBe(1);
  });

  it("saves a scene plan through the versioned endpoint", async () => {
    let seen: unknown = null;
    mockFetch((url) => {
      expect(url).toContain("/video-guide/scenes");
      return { ok: true, video_guide_id: "draft-1", scenes: [] };
    });
    const scenes = [{ title: "Open", caption: "Begin.", audio_start: 0, audio_end: 4, include: true }];
    const r = await saveScenePlan("t1", "tok", scenes);
    void seen;
    expect(r.video_guide_id).toBe("draft-1");
    expect(r.scenes).toEqual([]);
  });
});
