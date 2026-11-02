import { describe, expect, it, vi, beforeEach } from "vitest";
import { HttpError } from "./api";
import {
  runSync, loadReport, discardQueuedItem, classifyError, isNetworkError,
  type PendingReg, type PendingFinish, type PendingPhoto,
} from "./sync";
import type { JobEventRec } from "./types";

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
    uuid: () => `uuid-${Math.random().toString(36).slice(2)}`,
    __stores: stores,
  };
});

type Handler = (path: string, body?: unknown) => unknown;
let handler: Handler = () => ({});
vi.mock("./api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("./api")>();
  return {
    ...orig,
    api: {
      get: async (p: string) => handler(`GET ${p}`),
      post: async (p: string, body?: unknown) => handler(`POST ${p}`, body),
      put: async (p: string, body?: unknown) => handler(`PUT ${p}`, body),
      upload: async (p: string) => handler(`UPLOAD ${p}`),
    },
  };
});

import { idb } from "./db";

async function seedMeta(key: string, value: unknown) {
  await idb.put("meta", key, value);
}

function ev(id: string, session: string, type = "step_completed"): JobEventRec {
  return { event_id: id, session_id: session, step_id: null, event_type: type, payload: {}, occurred_at: new Date().toISOString(), sync_status: "pending" };
}

beforeEach(async () => {
  const { __stores } = (await import("./db")) as unknown as { __stores: Map<string, Map<string, unknown>> };
  __stores.clear();
  handler = () => ({});
});

describe("classifyError", () => {
  it("detects network failures", () => {
    expect(isNetworkError(new TypeError("Failed to fetch"))).toBe(true);
    expect(isNetworkError(new Error("Load failed"))).toBe(true);
    expect(isNetworkError(new HttpError("x", 500))).toBe(false);
    expect(classifyError(new TypeError("x"), "event").classification).toBe("network");
  });
  it("classifies auth, revision, unknown-session, validation", () => {
    expect(classifyError(new HttpError("nope", 401), "event").classification).toBe("auth");
    expect(classifyError(new HttpError("Jobs can only start from an approved procedure version", 409), "registration").classification).toBe("revision");
    expect(classifyError(new Error("Unknown session_id"), "event").classification).toBe("unknown-session");
    expect(classifyError(new HttpError("bad", 422), "event").classification).toBe("validation");
    expect(classifyError(new HttpError("err", 500), "event").classification).toBe("server");
  });
});

describe("runSync", () => {
  it("syncs everything and records last success", async () => {
    await seedMeta("pending-regs", [{ job_id: "j1", procedure_id: "p", procedure_version_id: "v" } as PendingReg]);
    await idb.put("media", "ph1", new Blob(["x"]));
    await seedMeta("pending-photos", [{ key: "ph1", job_id: "j1", step_id: null, description: "d" } as PendingPhoto]);
    await idb.put("events", "e1", ev("e1", "j1"));
    await seedMeta("pending-finishes", [{ job_id: "j1", outcome: "completed" } as PendingFinish]);
    const posted: string[] = [];
    handler = (path, body) => {
      posted.push(path);
      if (path === "POST /api/jobs") {
        expect((body as { id?: string }).id).toBe("j1");
        return { id: "j1" };
      }
      if (path.startsWith("UPLOAD")) return { id: "img1" };
      if (path === "POST /api/sync/events") return { acknowledged: (body as { events: { event_id: string }[] }).events.map((e) => e.event_id), duplicates: [], failed: [] };
      if (path === "POST /api/jobs/j1/finish") return { ok: true };
      return {};
    };
    const res = await runSync();
    expect(res.problems).toBe(0);
    expect(res.aborted).toBe(false);
    expect(await loadReport().then((r) => r.items)).toEqual([]);
    expect((await loadReport()).lastSuccessAt).toBeTruthy();
    expect((await idb.get("meta", "pending-regs") as unknown[]).length).toBe(0);
    expect(posted).toContain("POST /api/jobs/j1/finish");
  });

  it("holds events/photos/finishes until a failed registration succeeds", async () => {
    await seedMeta("pending-regs", [{ job_id: "j1", procedure_id: "p", procedure_version_id: "v" } as PendingReg]);
    await idb.put("events", "e1", ev("e1", "j1"));
    await seedMeta("pending-finishes", [{ job_id: "j1", outcome: "completed" } as PendingFinish]);
    let regOk = false;
    handler = (path, body) => {
      if (path === "POST /api/jobs") {
        if (!regOk) throw new HttpError("Jobs can only start from an approved procedure version", 409);
        return { id: "j1" };
      }
      if (path === "POST /api/sync/events") return { acknowledged: (body as { events: { event_id: string }[] }).events.map((e) => e.event_id), duplicates: [], failed: [] };
      if (path === "POST /api/jobs/j1/finish") return { ok: true };
      throw new HttpError("unexpected " + path, 500);
    };
    const r1 = await runSync();
    expect(r1.problems).toBeGreaterThan(0);
    // Events were NOT submitted while registration failed.
    expect(await idb.get<JobEventRec>("events", "e1").then((r) => r?.sync_status)).toBe("pending");
    const items = (await loadReport()).items;
    expect(items.some((i) => i.queue === "event" && i.classification === "registration")).toBe(true);
    // Retry after the server accepts the registration: everything flows.
    regOk = true;
    const r2 = await runSync();
    expect(r2.problems).toBe(0);
    expect(await idb.get<JobEventRec>("events", "e1").then((r) => r?.sync_status)).toBe("synced");
  });

  it("includes the offline grant in registration", async () => {
    await seedMeta("pending-regs", [{ job_id: "j9", procedure_id: "p", procedure_version_id: "v", grant: "fg-grant.X.Y" } as PendingReg]);
    let seen: unknown = null;
    handler = (path, body) => {
      if (path === "POST /api/jobs") { seen = body; return { id: "j9" }; }
      return { acknowledged: [], duplicates: [], failed: [] };
    };
    await runSync();
    expect(seen).toMatchObject({ offline_grant: "fg-grant.X.Y" });
  });

  it("keeps unknown-session events queued with a diagnostic", async () => {
    await idb.put("events", "e9", ev("e9", "ghost"));
    handler = (path) => {
      if (path === "POST /api/sync/events") return { acknowledged: [], duplicates: [], failed: [{ event_id: "e9", error: "Unknown session_id" }] };
      return {};
    };
    const res = await runSync();
    expect(res.problems).toBe(1);
    expect(await idb.get<JobEventRec>("events", "e9").then((r) => r?.sync_status)).toBe("pending");
    const items = (await loadReport()).items;
    expect(items[0].classification).toBe("unknown-session");
    expect(items[0].recoverable).toBe(true);
  });

  it("records orphaned media honestly instead of dropping it", async () => {
    await seedMeta("pending-photos", [{ key: "gone", job_id: "j1", step_id: null, description: "d" } as PendingPhoto]);
    handler = () => ({ acknowledged: [], duplicates: [], failed: [] });
    await runSync();
    expect(await idb.get("meta", "pending-photos")).toEqual([]);
    const items = (await loadReport()).items;
    expect(items).toHaveLength(1);
    expect(items[0].classification).toBe("media-missing");
    expect(items[0].recoverable).toBe(false);
  });

  it("treats duplicates as synced and per-event failures individually", async () => {
    await idb.put("events", "e1", ev("e1", "j1"));
    await idb.put("events", "e2", ev("e2", "j1"));
    handler = (path) => {
      if (path === "POST /api/sync/events") return { acknowledged: ["e1"], duplicates: ["e2"], failed: [{ event_id: "e-missing", error: "nope" }] };
      return {};
    };
    await runSync();
    expect(await idb.get<JobEventRec>("events", "e1").then((r) => r?.sync_status)).toBe("synced");
    expect(await idb.get<JobEventRec>("events", "e2").then((r) => r?.sync_status)).toBe("synced");
  });

  it("prevents concurrent runs", async () => {
    handler = async () => {
      await new Promise((r) => setTimeout(r, 50));
      return { acknowledged: [], duplicates: [], failed: [] };
    };
    const [a, b] = await Promise.all([runSync(), runSync()]);
    expect([a.ran, b.ran].filter(Boolean)).toHaveLength(1);
    expect([a, b].find((r) => !r.ran)!.message).toMatch(/already.*running/i);
  });

  it("aborts cleanly on network loss without marking anything synced", async () => {
    await seedMeta("pending-regs", [{ job_id: "j1", procedure_id: "p", procedure_version_id: "v" } as PendingReg]);
    await idb.put("events", "e1", ev("e1", "j1"));
    await seedMeta("pending-finishes", [{ job_id: "j1", outcome: "completed" } as PendingFinish]);
    let failEvents = true;
    handler = (path, body) => {
      if (path === "POST /api/jobs") return { id: "j1" };
      if (path === "POST /api/sync/events") {
        if (failEvents) throw new TypeError("Failed to fetch");
        return { acknowledged: (body as { events: { event_id: string }[] }).events.map((e) => e.event_id), duplicates: [], failed: [] };
      }
      if (path === "POST /api/jobs/j1/finish") return { ok: true };
      return {};
    };
    const r1 = await runSync();
    expect(r1.aborted).toBe(true);
    expect(await idb.get<JobEventRec>("events", "e1").then((r) => r?.sync_status)).toBe("pending");
    failEvents = false;
    const r2 = await runSync();
    expect(r2.aborted).toBe(false);
    expect(r2.problems).toBe(0);
    expect(await idb.get<JobEventRec>("events", "e1").then((r) => r?.sync_status)).toBe("synced");
  });

  it("records unrecoverable finish rejections with an explicit action", async () => {
    await seedMeta("pending-finishes", [{ job_id: "gone", outcome: "completed" } as PendingFinish]);
    handler = (path) => {
      if (path === "POST /api/jobs/gone/finish") throw new HttpError("Job not found", 404);
      return { acknowledged: [], duplicates: [], failed: [] };
    };
    const res = await runSync();
    expect(res.problems).toBe(1);
    expect((await loadReport()).items[0]).toMatchObject({ queue: "finish", recoverable: false });
    // Still queued — discarding is an explicit user decision.
    expect(await idb.get("meta", "pending-finishes")).toHaveLength(1);
  });

  it("discards queue entries with confirmation handled by UI", async () => {
    await idb.put("events", "e1", ev("e1", "j1"));
    handler = () => ({ acknowledged: [], duplicates: [], failed: [{ event_id: "e1", error: "Unknown session_id" }] });
    await runSync();
    expect((await loadReport()).items).toHaveLength(1);
    await discardQueuedItem("event", "e1");
    expect(await idb.get("events", "e1")).toBeUndefined();
    expect((await loadReport()).items).toHaveLength(0);
  });
});
