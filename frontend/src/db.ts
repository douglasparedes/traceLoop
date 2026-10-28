// Minimal IndexedDB wrapper: procedures cache, local jobs, durable event queue, media blobs.
const DB_NAME = "fieldguard";
const STORES = ["versions", "jobs", "events", "meta", "media"] as const;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 2);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const s of STORES) if (!db.objectStoreNames.contains(s)) db.createObjectStore(s, { keyPath: "key" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const req = fn(t.objectStore(store));
    let result: T;
    req.onsuccess = () => { result = req.result; };
    req.onerror = () => reject(req.error);
    // Resolve only when the transaction commits, not merely when the
    // request succeeds, so "saved" actually means durable.
    t.oncomplete = () => resolve(result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error("IndexedDB transaction aborted"));
  });
}

export const idb = {
  put: (store: string, key: string, value: unknown) => tx(store, "readwrite", (s) => s.put({ key, value })),
  get: async <T,>(store: string, key: string): Promise<T | undefined> => {
    const row = await tx<{ key: string; value: T } | undefined>(store, "readonly", (s) => s.get(key) as IDBRequest<{ key: string; value: T } | undefined>);
    return row?.value;
  },
  all: async <T,>(store: string): Promise<T[]> => {
    const rows = await tx<{ key: string; value: T }[]>(store, "readonly", (s) => s.getAll() as IDBRequest<{ key: string; value: T }[]>);
    return (rows || []).map((r) => r.value);
  },
  del: (store: string, key: string) => tx(store, "readwrite", (s) => s.delete(key)),
  clear: (store: string) => tx(store, "readwrite", (s) => s.clear()),
};

export function uuid(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
