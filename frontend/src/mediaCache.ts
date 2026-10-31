// Private-media cache lifecycle. The service worker (public/sw.js) caches
// tutorial/evidence media under token-bound keys; this helper wipes that
// cache on sign-out so the next user on this device cannot read the previous
// user's cached media. Queued work and downloads live in IndexedDB and are
// intentionally NOT touched here.
export const MEDIA_CACHE_NAME = "fieldguard-media-v2";

export async function clearMediaCache(): Promise<boolean> {
  try {
    const c = (globalThis as unknown as { caches?: CacheStorage }).caches;
    if (!c || typeof c.delete !== "function") return false;
    return await c.delete(MEDIA_CACHE_NAME);
  } catch {
    return false;
  }
}
