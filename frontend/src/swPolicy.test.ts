// Executes the REAL frontend/public/sw.js in a vm sandbox with stubbed
// platform APIs, proving the media-cache authorization policy:
// token-bound keys, no cross-token serving, no caching of failures,
// JSON bypass, and logout wipe (via clearMediaCache).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { clearMediaCache, MEDIA_CACHE_NAME } from "./mediaCache";

class FakeResponse {
  status: number;
  body: string;
  ok: boolean;
  headers = new Map();
  constructor(body: string, status = 200) {
    this.body = body;
    this.status = status;
    this.ok = status >= 200 && status < 300;
  }
  clone() {
    return new FakeResponse(this.body, this.status);
  }
  async text() {
    return this.body;
  }
}

function fakeRequest(url: string, method = "GET", mode = "cors") {
  return { url, method, mode };
}

interface Sandbox {
  listeners: Record<string, ((e: never) => unknown)[]>;
  store: Map<string, Map<string, FakeResponse>>;
  fetchCalls: { url: string }[];
  fetchImpl: (req: { url: string }) => Promise<FakeResponse>;
  self: Record<string, unknown>;
}

function loadSw(fetchImpl: Sandbox["fetchImpl"]): Sandbox {
  const sb: Sandbox = {
    listeners: {},
    store: new Map(),
    fetchCalls: [],
    fetchImpl,
    self: {},
  };
  const normKey = (k: unknown) => (typeof k === "string" ? k : (k as { url: string }).url);
  const cachesStub = {
    open: async (name: string) => {
      if (!sb.store.has(name)) sb.store.set(name, new Map());
      const inner = sb.store.get(name)!;
      return {
        match: async (k: unknown) => inner.get(normKey(k)) || undefined,
        put: async (k: unknown, v: FakeResponse) => { inner.set(normKey(k), v); },
        delete: async (k: unknown) => inner.delete(normKey(k)),
        keys: async () => [...inner.keys()].map((url) => ({ url })),
        addAll: async () => undefined,
      };
    },
    keys: async () => [...sb.store.keys()],
    delete: async (name: string) => sb.store.delete(name),
  };
  sb.self = {
    location: { origin: "https://app.test" },
    registration: { scope: "https://app.test/", navigationPreload: { enable: async () => undefined } },
    clients: { claim: async () => undefined },
    skipWaiting: () => undefined,
    addEventListener: (type: string, fn: (e: never) => unknown) => {
      (sb.listeners[type] = sb.listeners[type] || []).push(fn);
    },
  };
  const sandbox = {
    self: sb.self,
    caches: cachesStub,
    URL,
    fetch: async (req: { url: string }) => {
      sb.fetchCalls.push({ url: req.url });
      return sb.fetchImpl(req);
    },
  };
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "public", "sw.js"), "utf-8");
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: "sw.js" });
  // Run install/activate side effects.
  for (const fn of sb.listeners["install"] || []) fn({ waitUntil: (p: Promise<unknown>) => void p.catch(() => undefined) } as never);
  for (const fn of sb.listeners["activate"] || []) fn({ waitUntil: (p: Promise<unknown>) => void p.catch(() => undefined) } as never);
  return sb;
}

async function dispatchFetch(sb: Sandbox, url: string, method = "GET", mode = "cors") {
  let settled: Promise<unknown> | null = null;
  const req = fakeRequest(url, method, mode);
  for (const fn of sb.listeners["fetch"] || []) {
    fn({ request: req, respondWith: (p: Promise<unknown>) => { settled = p; }, mode } as never);
  }
  if (!settled) return { responded: false as const };
  return { responded: true as const, response: (await settled) as FakeResponse };
}

const VID = "https://app.test/api/tutorial/abc/video?token=tok-A";
const ILL = "https://app.test/api/tutorial/abc/illustrations/obj-1-overlay.png?token=tok-A";
const VIS = "https://app.test/api/visuals/v1/file?token=tok-A";

describe("sw media authorization policy (real sw.js)", () => {
  it("caches tutorial video under the full token-bound URL", async () => {
    const sb = loadSw(async () => new FakeResponse("bytes"));
    const r = await dispatchFetch(sb, VID);
    expect(r.responded).toBe(true);
    if (!r.responded) return;
    expect(r.response.body).toBe("bytes");
    const media = sb.store.get(MEDIA_CACHE_NAME)!;
    expect([...media.keys()].some((k) => k.includes("token=tok-A"))).toBe(true);
    expect(sb.fetchCalls).toHaveLength(1);
    // Second hit serves from cache without network.
    await dispatchFetch(sb, VID);
    expect(sb.fetchCalls).toHaveLength(1);
  });

  it("never serves cached media across different tokens", async () => {
    const sb = loadSw(async () => new FakeResponse("bytes"));
    await dispatchFetch(sb, VID);
    const other = "https://app.test/api/tutorial/abc/video?token=tok-B";
    const r = await dispatchFetch(sb, other);
    expect(r.responded).toBe(true);
    expect(sb.fetchCalls).toHaveLength(2);
  });

  it("does not cache failed (401/403) responses", async () => {
    const sb = loadSw(async () => new FakeResponse("denied", 401));
    const r = await dispatchFetch(sb, VID);
    expect(r.responded).toBe(true);
    if (!r.responded) return;
    expect(r.response.status).toBe(401);
    expect(sb.store.get(MEDIA_CACHE_NAME)?.size || 0).toBe(0);
  });

  it("covers illustrations, accepted visuals, and video guides", async () => {
    const sb = loadSw(async () => new FakeResponse("img"));
    const VG = "https://app.test/api/tutorial/abc/video-guide/file?token=tok-A";
    for (const u of [ILL, VIS, VG]) {
      const r = await dispatchFetch(sb, u);
      expect(r.responded).toBe(true);
    }
    const keys = [...(sb.store.get(MEDIA_CACHE_NAME) || new Map()).keys()];
    expect(keys.some((k) => k.includes("illustrations/obj-1-overlay.png?token=tok-A"))).toBe(true);
    expect(keys.some((k) => k.includes("visuals/v1/file?token=tok-A"))).toBe(true);
    expect(keys.some((k) => k.includes("video-guide/file?token=tok-A"))).toBe(true);
  });

  it("lets JSON API traffic bypass the service worker cache entirely", async () => {
    const sb = loadSw(async () => new FakeResponse("{}"));
    const r = await dispatchFetch(sb, "https://app.test/api/procedures");
    expect(r.responded).toBe(false);
  });
});

describe("clearMediaCache (logout wipe)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("deletes the media cache and leaves everything else", async () => {
    const deleted: string[] = [];
    const fakeCaches = {
      delete: vi.fn(async (name: string) => { deleted.push(name); return true; }),
    };
    vi.stubGlobal("caches", fakeCaches);
    expect(await clearMediaCache()).toBe(true);
    expect(deleted).toEqual([MEDIA_CACHE_NAME]);
  });

  it("returns false when the Cache API is unavailable", async () => {
    vi.stubGlobal("caches", undefined);
    expect(await clearMediaCache()).toBe(false);
  });
});
