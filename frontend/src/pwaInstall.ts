// PWA install flow: capture beforeinstallprompt, expose an in-app install
// button, and report diagnostics (including TWA asset-link status).
import { useEffect, useState } from "react";

export interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function usePwaInstall() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    const onBIP = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setDeferred(null);
    };
    window.addEventListener("beforeinstallprompt", onBIP as EventListener);
    window.addEventListener("appinstalled", onInstalled);
    try {
      if (window.matchMedia("(display-mode: standalone)").matches) setInstalled(true);
    } catch { /* matchMedia unavailable */ }
    return () => {
      window.removeEventListener("beforeinstallprompt", onBIP as EventListener);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  async function install(): Promise<void> {
    const d = deferred;
    if (!d) return;
    setOutcome(null);
    await d.prompt();
    try {
      const choice = await d.userChoice;
      setOutcome(choice.outcome);
    } catch {
      setOutcome("unknown");
    }
    setDeferred(null);
  }

  return { canInstall: deferred !== null, installed, outcome, install };
}

export interface AssetLinksStatus {
  state: "ok" | "placeholder" | "missing" | "offline";
  detail: string;
}

/** Check whether the TWA asset-link file publishes a real signing fingerprint.
 * A placeholder means APK (TWA) installs fall back to a Custom Tab with the
 * address bar — exactly the reported symptom. */
export async function checkAssetLinks(): Promise<AssetLinksStatus> {
  try {
    const r = await fetch(".well-known/assetlinks.json", { headers: { Accept: "application/json" } });
    if (!r.ok) {
      return { state: "missing", detail: `Not served (HTTP ${r.status}) — TWA installs will show the address bar.` };
    }
    const body = (await r.json()) as { target?: { sha256_cert_fingerprints?: string[] } }[];
    const fp = body?.[0]?.target?.sha256_cert_fingerprints?.[0] || "";
    if (!fp || /REPLACE/i.test(fp)) {
      return { state: "placeholder", detail: "Placeholder fingerprint — TWA installs will show the address bar until the real signing key is published." };
    }
    if (!/^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){31}$/.test(fp)) {
      return { state: "placeholder", detail: "Fingerprint is not a valid SHA-256 value — TWA verification will fail." };
    }
    return { state: "ok", detail: "Real fingerprint published. If the bar persists, reinstall the APK (Android caches verification)." };
  } catch {
    return { state: "offline", detail: "Not fetchable — offline or unreachable." };
  }
}
