import { describe, expect, it, vi, beforeEach } from "vitest";
import { validateTutorialFile, queueTutorialUpload, listQueuedUploads, removeQueuedUpload, parseUploadResponse, parseApiJson, sha256Hex, runQueuedUpload, CHUNK_BYTES, MAX_TUTORIAL_BYTES } from "./uploadQueue";

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

describe("sha256Hex", () => {
  it("matches known vectors without loading the whole file at once", async () => {
    const enc = new TextEncoder();
    expect(await sha256Hex(new Blob([enc.encode("abc")]))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(await sha256Hex(new Blob([]))).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  });
});

describe("parseApiJson", () => {
  it("passes through valid JSON and server error details", () => {
    expect(parseApiJson(200, JSON.stringify({ ok: true }), "application/json")).toEqual({ ok: true });
    expect(() => parseApiJson(422, JSON.stringify({ detail: "Nope" }), "application/json")).toThrow("Nope");
  });

  it("explains HTML error pages instead of leaking SyntaxError", () => {
    const html = "<html><body><h1>Too big</h1></body></html>";
    expect(() => parseApiJson(200, html, "text/html")).toThrow(/wrong address/);
    expect(() => parseApiJson(413, html, "text/html")).toThrow(/before reaching TraceLoop/);
    expect(() => parseApiJson(500, html, "text/html")).toThrow(/unreadable error page/);
    try {
      parseApiJson(500, html, "text/html");
      expect.unreachable();
    } catch (e) {
      expect((e as Error).message).not.toMatch(/Unexpected token/);
    }
  });
});

describe("chunked resume", () => {
  const server = { received: 0, bytes: new Uint8Array(0), failAtChunk: -1, chunks: 0, total: 0 };

  class FakeXHR {
    static DONE = 4;
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    responseText = "";
    readyState = 0;
    private url = "";
    private hdrs: Record<string, string> = {};
    open(_m: string, url: string) { this.url = url; }
    setRequestHeader(k: string, v: string) { this.hdrs[k] = v; }
    getResponseHeader(n: string) { return n.toLowerCase() === "content-type" ? "application/json" : null; }
    abort() { this.readyState = 4; if (this.onabort) this.onabort(); }
    async send(blob: Blob) {
      const m = /offset=(\d+)/.exec(this.url);
      const offset = m ? Number(m[1]) : 0;
      const buf = new Uint8Array(await (blob as Blob).arrayBuffer());
      await new Promise((r) => setTimeout(r, 0));
      server.chunks += 1;
      if (server.chunks === server.failAtChunk) { if (this.onerror) this.onerror(); return; }
      if (offset !== server.received) {
        this.status = 422;
        this.responseText = JSON.stringify({ detail: `Gap: expected ${server.received}` });
      } else {
        const grown = new Uint8Array(server.bytes.length + buf.length);
        grown.set(server.bytes);
        grown.set(buf, server.bytes.length);
        server.bytes = grown;
        server.received += buf.length;
        this.status = 200;
        this.responseText = JSON.stringify({ received_bytes: server.received, total_size: server.total });
      }
      this.readyState = 4;
      if (this.upload.onprogress) this.upload.onprogress({ lengthComputable: true, loaded: buf.length, total: buf.length });
      if (this.onload) this.onload();
    }
  }

  beforeEach(() => {
    server.received = 0;
    server.bytes = new Uint8Array(0);
    server.failAtChunk = -1;
    server.chunks = 0;
    server.total = 0;
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    vi.spyOn(globalThis, "fetch").mockImplementation((async (url: unknown, init?: unknown) => {
      const u = String(url);
      const method = ((init as RequestInit | undefined)?.method || "GET").toUpperCase();
      const json = (v: unknown, status = 200) => ({ ok: status < 400, status, headers: new Headers({ "Content-Type": "application/json" }), json: async () => v, text: async () => JSON.stringify(v) }) as unknown as Response;
      if (u.endsWith("/api/tutorial/uploads") && method === "POST") {
        const body = JSON.parse(String((init as { body?: string }).body || "{}"));
        server.total = body.total_size;
        server.received = 0;
        server.bytes = new Uint8Array(0);
        return json({ ok: true, upload_id: "up-1", chunk_size: 4 * 1024 * 1024 });
      }
      if (u.includes("/api/tutorial/uploads/up-1") && method === "GET") {
        return json({ status: "open", received_bytes: server.received, total_size: server.total });
      }
      if (u.endsWith("/complete") && method === "POST") {
        return json({ id: "job-1", title: "Big", status: "uploaded", progress: 2, access_token: "tok", upload_id: "up-1" });
      }
      return json({}, 404);
    }) as typeof fetch);
  });

  it("uploads in chunks, resumes after a network drop, and verifies bytes", { timeout: 60000 }, async () => {
    const size = 10 * 1024 * 1024;
    const raw = new Uint8Array(size);
    for (let i = 0; i < size; i++) raw[i] = i % 251;
    const blob = new Blob([raw], { type: "video/mp4" });
    const entry = await queueTutorialUpload({ blob, filename: "big.mp4", title: "Big", mode: "auto", origin: "uploaded" });
    server.failAtChunk = 2; // second chunk's XHR fails after one chunk confirmed
    await expect(runQueuedUpload(entry, () => undefined)).rejects.toThrow(/check the connection/);
    expect(server.received).toBe(4 * 1024 * 1024);
    expect((await listQueuedUploads()).find((e) => e.key === entry.key)).toBeTruthy();
    server.failAtChunk = -1;
    const job = await runQueuedUpload({ ...(await listQueuedUploads()).find((e) => e.key === entry.key)! }, () => undefined);
    expect(job.id).toBe("job-1");
    expect(server.bytes.length).toBe(size);
    expect(Array.from(server.bytes)).toEqual(Array.from(raw));
    expect(await listQueuedUploads()).toHaveLength(0); // removed only after server confirm
  });

  it("cancels without losing the queue entry", async () => {
    const blob = new Blob([new Uint8Array(1024)], { type: "video/mp4" });
    const entry = await queueTutorialUpload({ blob, filename: "c.mp4", title: "C", mode: "auto", origin: "recorded" });
    await expect(runQueuedUpload(entry, () => undefined, { cancelled: true })).rejects.toThrow(/cancelled/i);
    expect(await listQueuedUploads()).toHaveLength(1);
  });
});
