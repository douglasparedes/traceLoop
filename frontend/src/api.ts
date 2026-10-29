import type { Role } from "./types";

export const API = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_URL || "";

const TOKEN_KEY = "fg-auth-token";

let identity: { user: string; role: Role } = { user: "demo-tech", role: "technician" };
export function setIdentity(user: string, role: Role) { identity = { user, role }; }
export function getIdentity() { return identity; }

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* private mode: session-only */ }
}
export function clearToken() { setToken(null); }

/** Fired when the server answers 401 — the app shows the passphrase lock. */
export const AUTH_REQUIRED_EVENT = "fieldguard:auth-required";
function emitAuthRequired() {
  try { window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT)); } catch { /* noop */ }
}

function baseHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { "X-User": identity.user, "X-Role": identity.role, ...extra };
  const t = getToken();
  if (t) h["X-Auth-Token"] = t;
  return h;
}

/** Same identity headers for the call sites that fetch() directly. */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return baseHeaders(extra);
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const t = getToken();
  const sep = path.includes("?") ? "&" : "?";
  return `${proto}//${window.location.host}${path}${t ? `${sep}token=${encodeURIComponent(t)}` : ""}`;
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...baseHeaders(init.headers as Record<string, string> || {}) },
  });
  if (res.status === 401) { emitAuthRequired(); }
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
    headers: { "Content-Type": "application/json", ...baseHeaders(extraHeaders) },
    body: JSON.stringify(body ?? {}),
  });
  if (res.status === 401) { emitAuthRequired(); }
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
    headers: { ...baseHeaders(extraHeaders) },
  });
  if (res.status === 401) { emitAuthRequired(); }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const b = await res.json(); msg = (b as { detail?: string }).detail || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function authStatus(): Promise<{ auth_enabled: boolean }> {
  try {
    const res = await fetch(`${API}/api/auth/status`);
    if (res.ok) return (await res.json()) as { auth_enabled: boolean };
  } catch { /* offline: assume locked if we have no token */ }
  return { auth_enabled: !!getToken() };
}

export async function login(password: string): Promise<boolean> {
  const res = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) return false;
  const body = (await res.json()) as { token?: string; demo_open?: boolean };
  if (body.token) setToken(body.token);
  return true;
}

export async function checkSession(): Promise<boolean> {
  try {
    const res = await fetch(`${API}/api/auth/me`, { headers: baseHeaders() });
    return res.ok;
  } catch { return !!getToken(); }
}

export const api = {
  get: <T,>(p: string) => req<T>(p),
  post: <T,>(p: string, body?: unknown, extraHeaders: Record<string, string> = {}) => req<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined, headers: extraHeaders }),
  put: <T,>(p: string, body: unknown, extraHeaders: Record<string, string> = {}) => req<T>(p, { method: "PUT", body: JSON.stringify(body), headers: extraHeaders }),
  upload: async <T,>(p: string, form: FormData, extraHeaders: Record<string, string> = {}): Promise<T> => {
    const res = await fetch(`${API}${p}`, { method: "POST", headers: baseHeaders(extraHeaders), body: form });
    if (res.status === 401) { emitAuthRequired(); }
    if (!res.ok) { let m = `Upload failed (${res.status})`; try { m = ((await res.json()) as { detail?: string }).detail || m; } catch { /* noop */ } throw new Error(m); }
    return res.json() as Promise<T>;
  },
};
