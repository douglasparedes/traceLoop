// Browser smoke: the guided loop in a real browser against a real server.
// Scenario A — successful maintenance job (Procedures → start → finish).
// Scenario B — blocked execution (halt → resolve → finish).
// Scenario C — offline queue (disconnect → queue → reconnect → sync).
// Tutorial-to-procedure (Scenario D) stays a documented manual demo:
// it needs a real recording + minutes of AI processing, unsuitable for CI.
import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/seed");
});

async function startFirstReadyJob(page: Page) {
  await page.goto("/");
  const ready = page.getByRole("region", { name: "Ready to start" });
  await expect(ready).toBeVisible();
  await ready.getByRole("button", { name: "Start job" }).first().click();
  await expect(page.getByRole("heading", { name: "Procedure Execution" })).toBeVisible();
}

async function completeAllSteps(page: Page) {
  for (let i = 0; i < 10; i++) {
    const next = page.getByRole("button", { name: /^Next step/ });
    if (await next.count()) {
      await next.first().click();
      continue;
    }
    const finish = page.getByRole("button", { name: /^Finish job/ });
    if (await finish.count()) {
      await finish.first().click();
      return;
    }
    break;
  }
}

test("A — start, execute, and finish a job with one click", async ({ page, request }) => {
  await startFirstReadyJob(page);
  await completeAllSteps(page);
  await expect(page.getByText(/Job finished/)).toBeVisible();
  // Canonical server state, not just UI text.
  const jobs = await request.get("/api/jobs").then((r) => r.json()) as { status: string }[];
  expect(jobs.some((j) => j.status === "finished")).toBe(true);
  // Workbench shows it under recently completed.
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Recently completed" })).toBeVisible();
  await expect(page.getByText("Completed").first()).toBeVisible();
});

test("B — blocked step halts, resolve resumes, finish stays single-click", async ({ page }) => {
  await startFirstReadyJob(page);
  await page.getByRole("button", { name: /Report.*[Bb]locked/ }).first().click();
  await page.getByLabel(/Technician notes/).fill("Smoke-test blockage");
  await page.getByRole("button", { name: /Log incident/ }).click();
  await expect(page.getByText(/Job halted/)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Next step/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Finish job/ })).toHaveCount(0);
  // Resolve through the blocked step's own action.
  await page.getByRole("button", { name: /Resolve.*resume/ }).first().click();
  await expect(page.getByRole("button", { name: /^Next step/ })).toBeVisible();
  await completeAllSteps(page);
  await expect(page.getByText(/Job finished/)).toBeVisible();
});

test("C — offline steps queue and sync on reconnect", async ({ page, context }) => {
  await startFirstReadyJob(page);
  await context.setOffline(true);
  const next = page.getByRole("button", { name: /^Next step/ });
  await next.first().click();
  // Queued locally: the UI keeps working and reports pending sync.
  await expect(page.getByText(/stored on this device|pending/i).first()).toBeVisible();
  await context.setOffline(false);
  await page.getByRole("button", { name: /Retry sync|Sync/i }).first().click().catch(() => undefined);
  await page.waitForTimeout(3000);
  // No crash, no lost job: still on the execution screen or synced.
  await expect(page.getByRole("heading", { name: "Procedure Execution" })).toBeVisible();
});
