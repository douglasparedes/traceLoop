import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { checkAssetLinks, usePwaInstall } from "./pwaInstall";

function HookProbe() {
  const pwa = usePwaInstall();
  const [done, setDone] = useState(false);
  return (
    <div>
      <span data-testid="can-install">{String(pwa.canInstall)}</span>
      <span data-testid="installed">{String(pwa.installed)}</span>
      <span data-testid="outcome">{pwa.outcome || "none"}</span>
      <button onClick={() => void pwa.install().then(() => setDone(true))}>install</button>
      {done && <span data-testid="done">done</span>}
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("usePwaInstall", () => {
  it("offers install only after the browser fires beforeinstallprompt", async () => {
    render(<HookProbe />);
    expect(screen.getByTestId("can-install")).toHaveTextContent("false");
    const evt = new Event("beforeinstallprompt", { cancelable: true });
    window.dispatchEvent(evt);
    await waitFor(() => expect(screen.getByTestId("can-install")).toHaveTextContent("true"));
  });

  it("calls prompt and reports the accepted outcome", async () => {
    const prompt = vi.fn().mockResolvedValue(undefined);
    render(<HookProbe />);
    const evt = new Event("beforeinstallprompt", { cancelable: true }) as Event & {
      prompt: () => Promise<void>;
      userChoice: Promise<{ outcome: "accepted" }>;
    };
    evt.prompt = prompt;
    evt.userChoice = Promise.resolve({ outcome: "accepted" });
    window.dispatchEvent(evt);
    await waitFor(() => expect(screen.getByTestId("can-install")).toHaveTextContent("true"));
    screen.getByRole("button", { name: "install" }).click();
    await waitFor(() => expect(screen.getByTestId("outcome")).toHaveTextContent("accepted"));
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("can-install")).toHaveTextContent("false");
  });

  it("marks installed when the appinstalled event fires", async () => {
    render(<HookProbe />);
    window.dispatchEvent(new Event("appinstalled"));
    await waitFor(() => expect(screen.getByTestId("installed")).toHaveTextContent("true"));
  });
});

describe("checkAssetLinks", () => {
  it("detects the placeholder fingerprint (TWA would show the address bar)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [{ target: { sha256_cert_fingerprints: ["REPLACE_WITH_SHA256_FINGERPRINT_FROM_PWA_BUILDER_PACKAGE"] } }],
    } as Response);
    const s = await checkAssetLinks();
    expect(s.state).toBe("placeholder");
    expect(s.detail).toMatch(/address bar/i);
  });

  it("accepts a real fingerprint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [{ target: { sha256_cert_fingerprints: ["AA:".repeat(31) + "BB"] } }],
    } as Response);
    const s = await checkAssetLinks();
    expect(s.state).toBe("ok");
  });

  it("reports missing file honestly", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as Response);
    const s = await checkAssetLinks();
    expect(s.state).toBe("missing");
  });
});
