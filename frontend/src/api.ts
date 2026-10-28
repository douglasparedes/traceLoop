import type { Role } from "./types";

const API = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_URL || "";

let identity: { user: string; role: Role } = { user: "demo-tech", role: "technician" };
export function setIdentity(user: string, role: Role) { identity = { user, role }; }
export function getIdentity() { return identity; }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-User": identity.user, "X-Role": identity.role, ...(init.headers || {}) },
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const b = await res.json(); msg = (b as { detail?: string }).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function authPost<T>(path: string, body: unknown, extraHeaders: Record<string, string>): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User": identity.user, "X-Role": identity.role, ...extraHeaders },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const b = await res.json(); msg = (b as { detail?: string }).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function authDelete<T>(path: string, extraHeaders: Record<string, string>): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "DELETE",
    headers: { "X-User": identity.user, "X-Role": identity.role, ...extraHeaders },
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const b = await res.json(); msg = (b as { detail?: string }).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(p: string) => req<T>(p),
  post: <T,>(p: string, body?: unknown) => req<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T,>(p: string, body: unknown) => req<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  upload: async <T,>(p: string, form: FormData, extraHeaders: Record<string, string> = {}): Promise<T> => {
    const res = await fetch(`${API}${p}`, { method: "POST", headers: { "X-User": identity.user, "X-Role": identity.role, ...extraHeaders }, body: form });
    if (!res.ok) { let m = `Upload failed (${res.status})`; try { m = ((await res.json()) as { detail?: string }).detail || m; } catch { /* noop */ } throw new Error(m); }
    return res.json() as Promise<T>;
  },
};
