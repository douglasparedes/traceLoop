import { describe, expect, it, vi, beforeEach } from "vitest";
import { validateTutorialFile, queueTutorialUpload, listQueuedUploads, removeQueuedUpload, parseUploadResponse, MAX_TUTORIAL_BYTES } from "./uploadQueue";

vi.mock("./db", () => {
  const stores = new Map<string, Map<string, unknown>>();
  const table = (s: string) => {
    if (!stores.has(s)) stores.set(s, new Map());
    return stores.get(s)!;
  };
  return {
    idb: {
      put: async (store: string, key: string, value: unknown) => { table(store).set(key, { key, value }); },
      get: async <T,>(store: string, key: string): Promise<T | undefined> => {
        const row = table(store).get(key) as { value: T } | undefined;
        return row?.value;
      },
      all: async <T,>(store: string): Promise<T[]> => {
        return [...table(store).values()].map((r) => (r as { value: T }).value);
      },
      del: async (store: string, key: string) => { table(store).delete(key); },
      clear: async (store: string) => { table(store).clear(); },
    },
    uuid: () => `test-${Math.random().toString(36).slice(2)}`,
    __stores: stores,
  };
});

beforeEach(async () => {
  const { __stores } = (await import("./db")) as unknown as { __stores: Map<string, Map<string, unknown>> };
  __stores.clear();
  vi.restoreAllMocks();
});

function file(name: string, type: string, size: number): File {
  const blob = new Blob([new Uint8Array(size)], { type });
  return new File([blob], name, { type });
}

describe("validateTutorialFile", () => {
  it("accepts supported containers", () => {
    expect(validateTutorialFile(file("clip.mp4", "video/mp4", 1000))).toBeNull();
    expect(validateTutorialFile(file("clip.webm", "video/webm", 1000))).toBeNull();
    expect(validateTutorialFile(file("clip.mov", "video/quicktime", 1000))).toBeNull();
    expect(validateTutorialFile(file("clip.mkv", "video/x-matroska", 1000))).toBeNull();
  });

  it("rejects unsupported types with a helpful message", () => {
    const err = validateTutorialFile(file("notes.txt", "text/plain", 100));
    expect(err).toMatch(/MP4.*WebM.*MOV.*MKV/);
    expect(err).toMatch(/max 300 MB/);
  });

  it("rejects empty and oversized files", () => {
    expect(validateTutorialFile(file("empty.mp4", "video/mp4", 0))).toMatch(/empty/i);
    const big = validateTutorialFile(file("huge.mp4", "video/mp4", MAX_TUTORIAL_BYTES + 1));
    expect(big).toMatch(/300 MB/);
  });
});

describe("parseUploadResponse", () => {
  it("accepts valid JSON success bodies", () => {
    const body = { id: "t1", title: "T", status: "uploaded", progress: 2, access_token: "tok" };
    expect(parseUploadResponse(200, JSON.stringify(body), "application/json")).toEqual(body);
  });

  it("surfaces server JSON errors with their detail", () => {
    expect(() => parseUploadResponse(413, JSON.stringify({ detail: "Too large" }), "application/json"))
      .toThrow("Too large");
  });

  it("explains HTML 413 pages as proxy limits, not app errors", () => {
    const html = "<html><head><title>413 Request Entity Too Large</title></head><body>...</body></html>";
    expect(() => parseUploadResponse(413, html, "text/html")).toThrow(/proxy|mobile-network limit/i);
  });

  it("explains HTML 200 pages as a wrong-server API mismatch", () => {
    const html = "<html><head></head><body><h1>TraceLoop</h1></body></html>";
    expect(() => parseUploadResponse(200, html, "text/html")).toThrow(/wrong address|same server/i);
  });

  it("never throws the raw JSON SyntaxError for HTML bodies", () => {
    const html = "<html> <h1>oops</h1></html>";
    try {
      parseUploadResponse(502, html, "text/html");
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(Error);
      expect((e as Error).message).not.toMatch(/Unexpected token/);
      expect((e as Error).message).toMatch(/queued/);
    }
  });
});

describe("queued uploads persist across reload", () => {
  it("queues, lists, and removes without losing the blob", async () => {
    const blob = new Blob(["bytes"], { type: "video/mp4" });
    const entry = await queueTutorialUpload({ blob, filename: "clip.mp4", title: "T", mode: "auto", origin: "uploaded" });
    expect(entry.state).toBe("queued");
    const listed = await listQueuedUploads();
    expect(listed).toHaveLength(1);
    expect(listed[0].title).toBe("T");
    await removeQueuedUpload(entry.key);
    expect(await listQueuedUploads()).toHaveLength(0);
  });
});
