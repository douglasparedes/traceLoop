import { useCallback, useEffect, useRef, useState } from "react";
import { api, setIdentity, authStatus, checkSession, login as apiLogin, clearToken, AUTH_REQUIRED_EVENT } from "./api";
import { idb, uuid } from "./db";
import { Icon, type IconName } from "./icons";
import TutorialMode from "./TutorialMode";
import TutorialLibrary, { type LibraryItem } from "./TutorialLibrary";
import TutorialStudio from "./TutorialStudio";
import TutorialUpload, { ModeSelector, QueuedUploads } from "./TutorialUpload";
import { requestPersistentStorage, type AnalysisMode } from "./uploadQueue";
import type { JobEventRec, LocalJob, ProcSummary, Role, Step, Version, View } from "./types";
import { checkAssetLinks, usePwaInstall, type AssetLinksStatus } from "./pwaInstall";
import { clearMediaCache } from "./mediaCache";
import { runSync, storeGrant, getStoredGrant, isNetworkError, pendingCounts, pendingForJob, type PendingReg, type PendingFinish, type PendingPhoto } from "./sync";
import SyncDiagnostics from "./SyncDiagnostics";

const ISSUE_TYPES = ["Component not found", "Instructions unclear", "Expected result not observed", "Tool unavailable", "Manual mismatch", "Unexpected condition", "Other"];

interface JobRow { id: string; procedure_title: string; status: string; outcome: string | null; started_at: string; ended_at: string | null; events: number }
interface ManualRow { id: string; title: string; model: string | null; chunks: number }

async function loadPending<T>(key: string): Promise<T[]> {
  return (await idb.get<T[]>("meta", key)) || [];
}
async function savePending<T>(key: string, items: T[]): Promise<void> {
  await idb.put("meta", key, items);
}

export default function App() {
  const [view, setView] = useState<View>("home");
  const [role, setRole] = useState<Role>(() => {
    try {
      const r = localStorage.getItem("fg-role");
      return r === "reviewer" || r === "expert" ? r : "technician";
    } catch { return "technician"; }
  });
  const [authChecked, setAuthChecked] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [online, setOnline] = useState(navigator.onLine);
  const [syncState, setSyncState] = useState<"idle" | "syncing" | "failed">("idle");
  const [pending, setPending] = useState(0);
  const [procs, setProcs] = useState<ProcSummary[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [msg, setMsg] = useState("");
  const [msgKind, setMsgKind] = useState<"ok" | "error" | "info">("ok");
  const [listsLoading, setListsLoading] = useState(true);
  const [cachedIds, setCachedIds] = useState<Set<string>>(new Set());
  const [activeVersion, setActiveVersion] = useState<Version | null>(null);
  const [activeJob, setActiveJob] = useState<LocalJob | null>(null);
  const [recentFinishes, setRecentFinishes] = useState<LocalJob[]>([]);
  const [updateReady, setUpdateReady] = useState(false);
  const [reviewVersion, setReviewVersion] = useState<Version | null>(null);
  const [studioItem, setStudioItem] = useState<LibraryItem | null>(null);
  const [tutRefresh, setTutRefresh] = useState(0);
  const [detailVersion, setDetailVersion] = useState<Version | null>(null);
  const [storageNote, setStorageNote] = useState<string | null>(null);
  const pwa = usePwaInstall();

  const notify = useCallback((text: string, kind: "ok" | "error" | "info" = "ok") => { setMsg(text); setMsgKind(kind); }, []);

  const refreshCached = useCallback(async () => {
    const vs = await idb.all<Version>("versions");
    setCachedIds(new Set(vs.map((v) => v.id)));
  }, []);

  const refreshPending = useCallback(async () => {
    try {
      setPending((await pendingCounts()).total);
    } catch { /* storage unavailable: keep last count */ }
  }, []);

  const loadRecentFinishes = useCallback(async () => {
    try { setRecentFinishes((await idb.get<LocalJob[]>("meta", "recent-finishes")) || []); }
    catch { /* storage unavailable */ }
  }, []);
  const dismissRecentFinish = useCallback(async (id: string) => {
    try {
      const recent = ((await idb.get<LocalJob[]>("meta", "recent-finishes")) || []).filter((r) => r.id !== id);
      await idb.put("meta", "recent-finishes", recent);
      setRecentFinishes(recent);
    } catch { /* best effort */ }
  }, []);

  const loadLists = useCallback(async () => {
    try {
      const [p, j] = await Promise.all([api.get<ProcSummary[]>("/api/procedures"), api.get<JobRow[]>("/api/jobs")]);
      setProcs(p); setJobs(j);
      await idb.put("meta", "lists", { procs: p, jobs: j });
    } catch { /* offline: IDB-restored lists stay visible */ } finally { setListsLoading(false); }
  }, []);

  const syncNow = useCallback(async () => {
    setSyncState("syncing");
    try {
      const res = await runSync();
      if (!res.ran) { setSyncState("idle"); notify(res.message, "info"); return; }
      setSyncState(res.problems || res.aborted ? "failed" : "idle");
      notify(res.message, res.problems || res.aborted ? "error" : "ok");
      await refreshPending(); await loadLists(); await loadRecentFinishes();
      // Drop locally-kept completions once nothing remains unsynced for
      // them — the server Activity list is authoritative from here on.
      try {
        const recent = (await idb.get<LocalJob[]>("meta", "recent-finishes")) || [];
        const kept: LocalJob[] = [];
        for (const r of recent) {
          if ((await pendingForJob(r.id)).total > 0) kept.push(r);
        }
        if (kept.length !== recent.length) {
          await idb.put("meta", "recent-finishes", kept);
          setRecentFinishes(kept);
        }
      } catch { /* best effort */ }
    } catch (e) { setSyncState("failed"); notify(e instanceof Error ? e.message : "Sync failed", "error"); }
  }, [loadLists, notify, refreshPending, loadRecentFinishes]);

  useEffect(() => { setIdentity(role === "technician" ? "demo-tech" : role === "expert" ? "demo-expert" : "demo-reviewer", role); loadLists(); }, [role, loadLists]);
  useEffect(() => {
    try { localStorage.setItem("fg-role", role); } catch { /* private mode */ }
  }, [role]);
  // Passphrase gate: only enforced when the server enables it. Runs once at
  // boot; any later 401 re-opens the lock without losing local work.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const st = await authStatus();
        if (!alive) return;
        if (!st.auth_enabled) { setAuthRequired(false); }
        else {
          const ok = await checkSession();
          if (alive) setAuthRequired(!ok);
        }
      } catch { if (alive) setAuthRequired(false); }
      finally { if (alive) setAuthChecked(true); }
    })();
    const on401 = () => setAuthRequired(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, on401);
    return () => { alive = false; window.removeEventListener(AUTH_REQUIRED_EVENT, on401); };
  }, []);
  async function doLogin() {
    if (!authPassword || authBusy) return;
    setAuthBusy(true); setAuthError("");
    try {
      const ok = await apiLogin(authPassword);
      if (ok && await checkSession()) { setAuthPassword(""); setAuthRequired(false); notify("Signed in — loading server state.", "ok"); void loadLists(); }
      else setAuthError("Wrong passphrase. Try again.");
    } catch { setAuthError("Sign-in failed — check the connection and retry."); }
    finally { setAuthBusy(false); }
  }
  function doLogout() {
    clearToken(); setAuthRequired(true); setAuthPassword("");
    // Auth boundary: wipe cached private media so the next user on this
    // device cannot read it from the service-worker cache. Queued work and
    // downloaded procedures stay (IndexedDB), per the offline policy.
    void clearMediaCache();
    notify("Signed out on this device. Queued work stays saved locally.", "info");
  }
  useEffect(() => {
    loadLists(); refreshPending(); refreshCached(); loadRecentFinishes();
    idb.get<{ procs: ProcSummary[]; jobs: JobRow[] }>("meta", "lists").then((l) => { if (l) { setProcs(l.procs); setJobs(l.jobs); } });
    idb.get<LocalJob>("jobs", "active").then(async (j) => {
      if (j && !j.finished) {
        setActiveJob(j);
        const v = await idb.get<Version>("versions", j.procedure_version_id);
        if (v) setActiveVersion(v);
      }
    });
    const on = () => { setOnline(true); void syncNow(); }; const off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, [loadLists, refreshPending, refreshCached, syncNow, loadRecentFinishes]);

  useEffect(() => {
    const h = document.querySelector<HTMLElement>("main h2");
    if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
  }, [view]);

  // Service-worker update flow: a waiting worker means a new build is ready.
  // Never force-activate mid-session; the tech reloads when safe instead.
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    let alive = true;
    let onVis: (() => void) | undefined;
    navigator.serviceWorker.getRegistration().then((reg) => {
      if (!reg || !alive) return;
      const checkWaiting = () => {
        if (reg.waiting && navigator.serviceWorker.controller) setUpdateReady(true);
      };
      checkWaiting();
      reg.addEventListener("updatefound", () => {
        const sw = reg.installing;
        if (!sw) { checkWaiting(); return; }
        sw.addEventListener("statechange", () => {
          if (sw.state === "installed") checkWaiting();
        });
      });
      onVis = () => { void reg.update().then(checkWaiting).catch(() => undefined); };
      document.addEventListener("visibilitychange", onVis);
      // Check for a waiting worker again after the page settles (covers a
      // worker that finished installing between load and registration).
      setTimeout(() => { void reg.update().then(checkWaiting).catch(() => undefined); }, 5000);
    }).catch(() => undefined);
    return () => { alive = false; if (onVis) document.removeEventListener("visibilitychange", onVis); };
  }, []);

  function applyUpdate() {
    navigator.serviceWorker.getRegistration().then((reg) => {
      if (reg?.waiting) {
        const done = () => window.location.reload();
        navigator.serviceWorker.addEventListener("controllerchange", done, { once: true });
        reg.waiting.postMessage({ type: "SKIP_WAITING" });
        // Safety net: if activation stalls, reload anyway after 3s.
        setTimeout(done, 3000);
      } else window.location.reload();
    }).catch(() => window.location.reload());
  }

  async function queueEvent(ev: Omit<JobEventRec, "sync_status">) {
    await idb.put("events", ev.event_id, { ...ev, sync_status: "pending" });
    await refreshPending();
  }

  async function openVersion(vid: string): Promise<Version | null> {
    try {
      const v = await api.get<Version>(`/api/procedure-versions/${vid}`);
      await idb.put("versions", v.id, v);
      void refreshCached();
      // Fetch an offline execution grant with each approved download: if
      // this revision is later superseded, an offline-started job can still
      // register against it. Best-effort — offline caching must not fail.
      if (v.status === "approved") {
        try {
          const g = await api.post<{ offline_grant: string }>(`/api/procedure-versions/${vid}/offline-grant`, {});
          if (g.offline_grant) await storeGrant(v.id, g.offline_grant);
        } catch { /* grant refresh happens on next online open */ }
      }
      return v;
    } catch {
      return (await idb.get<Version>("versions", vid)) || null;
    }
  }

  async function openDetail(vid: string) {
    const v = await openVersion(vid);
    if (v) { setDetailVersion(v); setView("detail"); }
    else notify("That version is not available offline yet.", "error");
  }

  useEffect(() => {
    let alive = true;
    if (typeof navigator !== "undefined" && navigator.storage?.estimate) {
      navigator.storage.estimate().then((e) => {
        if (!alive || !e.quota) return;
        const gb = e.quota / 1024 ** 3;
        setStorageNote(gb >= 1 ? `Storage: Ready (${Math.round(gb * 1024)} MB)` : "Storage: Ready");
      }).catch(() => { /* estimate unavailable — omit the badge */ });
    }
    return () => { alive = false; };
  }, []);

  async function startJob(p: ProcSummary) {
    if (!p.approved_version_id) { notify("This procedure has no approved version yet.", "error"); return; }
    const v = await openVersion(p.approved_version_id);
    if (!v) { notify("Could not load the approved procedure. Connect once to download it for offline use.", "error"); return; }
    if (!v.steps.length) { notify("This approved version has no steps and cannot start a job.", "error"); return; }
    let jobId = uuid();
    try {
      const j = await api.post<{ id: string }>("/api/jobs", { procedure_id: p.id, procedure_version_id: v.id });
      jobId = j.id;
    } catch (e) {
      if (!isNetworkError(e)) {
        // Real server rejection (e.g. 409 revision conflict, 404): do NOT
        // queue offline — tell the technician exactly what went wrong.
        notify(e instanceof Error ? e.message : "Could not start the job.", "error");
        return;
      }
      const regs = await loadPending<PendingReg>("pending-regs");
      if (!regs.some((r) => r.job_id === jobId)) {
        regs.push({ job_id: jobId, procedure_id: p.id, procedure_version_id: v.id, grant: await getStoredGrant(v.id) });
        await savePending("pending-regs", regs);
      }
      notify("Offline: this job is saved on this device under a stable id and will register with the server on sync.", "info");
    }
    const local: LocalJob = { id: jobId, procedure_id: p.id, procedure_version_id: v.id, title: p.title, current: 0, stepStates: {}, started_at: new Date().toISOString(), finished: false };
    await idb.put("jobs", "active", local);
    setActiveJob(local); setActiveVersion(v); setView("job");
  }

  const pendingReview = procs.filter((p) => p.has_pending_review).length;
  // Four primary destinations. Review stays available as a secondary
  // destination (badge shows the queue); Guided job is contextual, reached
  // from an approved procedure or Continue Working — never a nav item.
  const deskNav: { view: View; label: string; icon: IconName }[] = [
    { view: "home", label: "Workbench", icon: "home" }, { view: "library", label: "Procedures", icon: "book" },
    { view: "tutorials", label: "Tutorials", icon: "videocam" }, { view: "activity", label: "Activity", icon: "schedule" },
  ];
  const deskSecondary: { view: View; label: string; icon: IconName }[] = [
    { view: "review", label: `Review${pendingReview ? ` (${pendingReview})` : ""}`, icon: "edit" },
    { view: "manuals", label: "Manuals", icon: "library" }, { view: "settings", label: "Settings", icon: "cog" },
  ];
  const mobileNav: { view: View; label: string; icon: IconName }[] = [
    { view: "home", label: "Home", icon: "home" }, { view: "library", label: "Procedures", icon: "book" },
    { view: "tutorials", label: "Tutorials", icon: "videocam" },
    { view: "activity", label: pending ? `Activity (${pending})` : "Activity", icon: "schedule" },
  ];
  const mobileCurrent: View = view === "home" || view === "library" || view === "tutorials" || view === "settings" ? view
    : view === "detail" || view === "manuals" ? "library"
    : view === "studio" || view === "capture" ? "tutorials" : "activity";
  const screenLabel: Record<View, string> = {
    home: "Workbench", library: "Procedures", detail: "Procedure", capture: "Tutorials", tutorials: "Tutorials", studio: "Tutorial Studio",
    review: "Review", job: "Guided job", history: "Activity", manuals: "Manuals", settings: "Settings", activity: "Activity",
  };

  async function handleSetJob(j: LocalJob | null) {
    if (!j) { setActiveJob(null); return; }
    if (j.finished) {
      setActiveJob(null);
      // Queue the finish for sync only if it is not already confirmed:
      // a server-confirmed finalize leaves nothing to deliver.
      const finishId = `evt:${j.id}:finish`;
      const finEv = await idb.get<JobEventRec>("events", finishId).catch(() => undefined);
      if (!finEv || finEv.sync_status !== "synced") {
        const finishes = await loadPending<PendingFinish>("pending-finishes");
        if (!finishes.some((f) => f.job_id === j.id)) {
          finishes.push({ job_id: j.id, outcome: j.finish_outcome || "completed" });
          await savePending("pending-finishes", finishes);
          await refreshPending();
        }
      }
      // Immediate local record so a just-finished job appears in Workbench
      // and Activity before the server confirms it — never silently gone.
      try {
        const recent = (await idb.get<LocalJob[]>("meta", "recent-finishes")) || [];
        const updated = [{ ...j }, ...recent.filter((r) => r.id !== j.id)].slice(0, 20);
        await idb.put("meta", "recent-finishes", updated);
        setRecentFinishes(updated);
      } catch { /* best effort */ }
      await idb.del("jobs", "active");
      return;
    }
    setActiveJob(j); await idb.put("jobs", "active", j);
  }

  if (!authChecked) {
    return (
      <div>
        <a className="skip-link" href="#main">Skip to content</a>
        <main id="main"><div className="card" aria-label="Loading"><div className="skeleton" /><div className="skeleton" /></div></main>
      </div>
    );
  }
  if (authRequired) {
    return (
      <div>
        <a className="skip-link" href="#main">Skip to content</a>
        <header className="topbar">
          <div className="app-header-inner">
            <div className="app-brand">
              <span className="app-logo" aria-hidden="true">T</span>
              <h1 className="brand">TraceLoop<small>Sign in</small></h1>
            </div>
          </div>
        </header>
        <main id="main">
          <div className="card" style={{ maxWidth: 480, margin: "24px auto" }}>
            <h2>Team sign-in</h2>
            <p className="muted">This deployment is protected by a team passphrase. Your queued offline work stays on this device; nothing is uploaded until you sign in and sync.</p>
            <form onSubmit={(e) => { e.preventDefault(); void doLogin(); }}>
              <label htmlFor="team-pass">Team passphrase</label>
              <input id="team-pass" type="password" autoComplete="current-password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} placeholder="Enter team passphrase" />
              {authError && <div className="notice error" role="alert">{authError}</div>}
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" type="submit" disabled={authBusy || !authPassword}>{authBusy ? "Checking…" : "Sign in"}</button>
              </div>
            </form>
          </div>
        </main>
      </div>
    );
  }
  return (
    <div>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="app-header-inner">
          <div className="app-brand">
            <span className="app-logo" aria-hidden="true">T</span>
            <h1 className="brand">TraceLoop<small>{screenLabel[view]}</small></h1>
          </div>
          <div className="app-header-side">
            <span className={`sync-pill${online ? "" : " offline"}`} role="status">
              <span className="sync-dot" aria-hidden="true" />{online ? (syncState === "syncing" ? "Syncing…" : `Online · ${pending} pending`) : "Offline · local"}
            </span>
            {syncState === "failed" && <span className="pill error">Sync needs attention</span>}
            <button className="avatar-btn" onClick={() => setView("settings")} title={`Profile & settings (demo identity: ${role})`} aria-label={`Profile and settings. Demo identity: ${role}`}>
              <span className="avatar" aria-hidden="true">{role[0].toUpperCase()}</span>
            </button>
          </div>
        </div>
      </header>
      <div className="shell">
        <nav className="nav" aria-label="Primary">
          {deskNav.map((n) => (
            <button key={n.view} aria-current={view === n.view ? "page" : undefined} onClick={() => setView(n.view)}><Icon name={n.icon} size={18} /> {n.label}</button>
          ))}
          <span className="nav-sep" aria-hidden="true">Review & setup</span>
          {deskSecondary.map((n) => (
            <button key={n.view} className="nav-secondary" aria-current={view === n.view ? "page" : undefined} onClick={() => setView(n.view)}><Icon name={n.icon} size={18} /> {n.label}</button>
          ))}
        </nav>
        <main id="main">
          {updateReady && (
            <div className="notice info" role="status" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span><strong>App update ready.</strong> Reload when safe — your queued work is stored on this device and survives the reload.</span>
              <span className="row" style={{ marginLeft: "auto" }}>
                <button className="btn small" onClick={applyUpdate}>Reload now</button>
                <button className="btn small secondary" onClick={() => setUpdateReady(false)}>Later</button>
              </span>
            </div>
          )}
          {msg && <div className={`notice ${msgKind === "error" ? "error" : msgKind === "info" ? "info" : "ok"}`} role={msgKind === "error" ? "alert" : "status"}>{msg} <button className="btn small secondary" onClick={() => setMsg("")}>Dismiss</button></div>}
          {listsLoading && procs.length === 0 && <div className="card" aria-label="Loading procedures"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>}
          {view === "home" && <Home procs={procs} jobs={jobs} activeJob={activeJob} activeVersion={activeVersion} pending={pending} online={online} storageNote={storageNote} role={role} go={setView} recentFinishes={recentFinishes} pwa={pwa} openReview={async (vid) => { const v = await openVersion(vid); if (v) { setReviewVersion(v); setView("review"); } else notify("That version is not available offline yet.", "error"); }} continueJob={() => { if (activeJob) { openVersion(activeJob.procedure_version_id).then((v) => { if (v) { setActiveVersion(v); setView("job"); } else notify("Downloaded procedure not found on this device. Reconnect and open it from Procedures.", "error"); }); } }} />}
          {view === "library" && <Library procs={procs} cachedIds={cachedIds} reload={loadLists} startJob={startJob} openVersion={openDetail} cache={async (vid) => { const v = await openVersion(vid); notify(v ? "Saved for offline use — verified in local storage on this device." : "Download failed — check connection.", v ? "ok" : "error"); }} />}
          {view === "detail" && <ProcedureDetail title={(detailVersion && procs.find((x) => x.id === detailVersion.procedure_id)?.title) || ""} version={detailVersion} cached={detailVersion ? cachedIds.has(detailVersion.id) : false} startJob={() => { const p = detailVersion ? procs.find((x) => x.id === detailVersion.procedure_id) : undefined; if (p) startJob(p); else if (detailVersion) notify("Procedure record unavailable — reload the library.", "error"); }} cache={async () => { if (detailVersion) { const v = await openVersion(detailVersion.id); notify(v ? "Saved for offline use — verified in local storage on this device." : "Download failed — check connection.", v ? "ok" : "error"); } }} openReview={() => { if (detailVersion) { setReviewVersion(detailVersion); setView("review"); } }} go={setView} />}
          {view === "capture" && <TutorialsView
            onOpenStudio={(t) => { setStudioItem(t); setView("studio"); }}
            refreshKey={tutRefresh} />}
          {view === "tutorials" && <TutorialsView
            onOpenStudio={(t) => { setStudioItem(t); setView("studio"); }}
            refreshKey={tutRefresh} />}
          {view === "studio" && (studioItem
            ? <TutorialStudio item={studioItem} onBack={() => { setView("tutorials"); setTutRefresh((n) => n + 1); }}
              onOpenReview={async (vid: string) => { const v = await openVersion(vid); if (v) { setReviewVersion(v); setView("review"); } else notify("That version is not available offline yet.", "error"); }}
              notify={notify} />
            : <div className="card"><div className="empty"><h3>No tutorial selected</h3><p>Pick a tutorial from the library to edit it in the Studio.</p><button className="btn" onClick={() => setView("tutorials")}>Open Tutorials</button></div></div>)}
          {view === "review" && <ReviewView version={reviewVersion} setVersion={setReviewVersion} procs={procs} openVersion={openVersion} role={role} reload={loadLists} notify={notify} />}
          {view === "job" && <JobView job={activeJob} version={activeVersion} queueEvent={queueEvent} setJob={handleSetJob} notify={notify} reload={loadLists} refreshPending={refreshPending} go={setView} pending={pending} online={online} offlineReady={activeVersion ? cachedIds.has(activeVersion.id) : false} />}
          {view === "activity" && <Activity jobs={jobs} pending={pending} pendingReview={pendingReview} reload={loadLists} go={setView} syncNow={() => void syncNow()} syncing={syncState === "syncing"} role={role} notify={notify} recent={recentFinishes} onDismissRecent={(id) => void dismissRecentFinish(id)} onProposeRevision={async (vid) => { const v = await openVersion(vid); if (v) { setReviewVersion(v); setView("review"); notify("Opened the job's exact revision. Use “Propose new revision” there — it goes through normal review."); } else notify("That revision is not available offline yet.", "error"); }} />}
          {view === "history" && <Activity jobs={jobs} pending={pending} pendingReview={pendingReview} reload={loadLists} go={setView} syncNow={() => void syncNow()} syncing={syncState === "syncing"} role={role} notify={notify} recent={recentFinishes} onDismissRecent={(id) => void dismissRecentFinish(id)} onProposeRevision={async (vid) => { const v = await openVersion(vid); if (v) { setReviewVersion(v); setView("review"); notify("Opened the job's exact revision. Use “Propose new revision” there — it goes through normal review."); } else notify("That revision is not available offline yet.", "error"); }} />}
          {view === "manuals" && <Manuals notify={notify} />}
          {view === "settings" && <Settings pending={pending} role={role} setRole={setRole} onSignOut={doLogout} pwa={pwa} clearCache={async () => { await idb.clear("versions"); await refreshCached(); notify("Offline procedure cache cleared. Downloaded jobs and queued events were kept."); }} />}
        </main>
      </div>
      {view !== "job" && (
        <nav className="bottomnav" aria-label="Primary mobile">
          {mobileNav.map((n) => (
            <button key={n.view} aria-current={mobileCurrent === n.view ? "page" : undefined} onClick={() => setView(n.view)}><Icon name={n.icon} size={22} />{n.label}</button>
          ))}
        </nav>
      )}
    </div>
  );
}

function Home({ procs, jobs, activeJob, activeVersion, pending, online, storageNote, role, go, recentFinishes, openReview, continueJob, pwa }: {
  procs: ProcSummary[]; jobs: JobRow[]; activeJob: LocalJob | null; activeVersion: Version | null;
  pending: number; online: boolean; storageNote: string | null; role: Role; go: (v: View) => void;
  recentFinishes: LocalJob[];
  openReview: (vid: string) => void; continueJob: () => void;
  pwa: { canInstall: boolean; installed: boolean; outcome: string | null; install: () => Promise<void> };
}) {
  const approved = procs.filter((p) => p.approved_version_id);
  const reviewQueue = procs.flatMap((p) => p.versions.filter((v) => v.status === "pending_review" || v.status === "draft" || v.status === "rejected").map((v) => ({ ...v, title: p.title })));
  const pendingReview = reviewQueue.filter((v) => v.status === "pending_review");
  const drafts = reviewQueue.filter((v) => v.status === "draft");
  const returned = reviewQueue.filter((v) => v.status === "rejected");
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const roleLabel = role === "reviewer" ? "Reviewer" : role === "expert" ? "Expert" : "Technician";
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  const doneCount = activeJob && activeVersion
    ? activeVersion.steps.filter((s) => activeJob.stepStates[s.id] === "done").length : 0;
  const blockedSteps = activeJob && activeVersion
    ? activeVersion.steps.filter((s) => activeJob.stepStates[s.id] === "blocked") : [];
  const totalSteps = activeVersion?.steps.length || 0;
  const homeNext = activeJob && activeVersion ? (() => {
    // Resume label = first step without a done/skipped outcome.
    // Blocked steps halt here — they are the resume target, never skipped.
    const sts = [...activeVersion.steps].sort((a, b) => a.step_order - b.step_order);
    const i = sts.findIndex((s) => !["done", "skipped"].includes(activeJob.stepStates[s.id]));
    return i === -1 ? sts.length : i + 1;
  })() : 1;
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: "1.7rem", letterSpacing: "-0.01em" }}>{greeting}, {roleLabel}</h2>
        <p className="muted"><Icon name="domain" size={15} /> {today} · Field operations</p>
        <div className="panel" role="status" style={{ marginTop: 8 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="eyebrow"><span className="sync-dot" style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: online ? "var(--primary-container)" : "var(--warn)", marginRight: 6 }} />{online ? `Online · ${pending} update${pending === 1 ? "" : "s"} pending sync` : `Offline · ${pending} update${pending === 1 ? "" : "s"} stored on this device`}</span>
            {storageNote && <span className="badge neutral">{storageNote}</span>}
          </div>
        </div>
      </div>
      {pwa.canInstall && !pwa.installed && (
        <div className="notice info" role="status" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
          <span><strong>Install TraceLoop</strong> for fullscreen field use — no address bar, works offline.</span>
          <span className="row" style={{ marginLeft: "auto" }}>
            <button className="btn small" onClick={() => void pwa.install()}>Install app</button>
          </span>
        </div>
      )}
      {pwa.outcome === "dismissed" && (
        <p className="muted small-text" role="status">Install dismissed — use Settings → Install &amp; display to try again.</p>
      )}
      {activeJob ? (
        <div className="card accent-edge">
          <div className="row" style={{ justifyContent: "space-between" }}>
            {blockedSteps.length > 0
              ? <span className="badge crit"><Icon name="warning" size={13} /> Job blocked — needs attention</span>
              : <span className="badge ok"><Icon name="play" size={13} /> In-progress field job</span>}
            <span className="muted small-text num">{new Date(activeJob.started_at).toLocaleString()}</span>
          </div>
          <h2 style={{ marginTop: 8 }}>{activeJob.title}</h2>
          <p className="muted small-text">Rev {activeVersion?.version_number} ({activeVersion?.status}) · saved on this device</p>
          {blockedSteps.length > 0 && (
            <p className="notice warn" role="status" style={{ margin: "8px 0 0" }}>
              Halted at: {blockedSteps.map((s) => `step ${s.step_order} (${s.title})`).join("; ")}. Open the job to resolve and resume.
            </p>
          )}
          {totalSteps > 0 && (
            <div className="panel" style={{ marginTop: 10 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="small-text">Step {totalSteps ? Math.min(homeNext, totalSteps) : ""} of {totalSteps}</span>
                <strong className="num">{Math.round((doneCount / totalSteps) * 100)}%</strong>
              </div>
              <div className="progress" role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={totalSteps} aria-label={`${doneCount} of ${totalSteps} steps complete`} style={{ marginTop: 6 }}><div style={{ width: `${(doneCount / totalSteps) * 100}%` }} /></div>
            </div>
          )}
          <button className="btn" style={{ width: "100%", marginTop: 12 }} onClick={continueJob}>{blockedSteps.length > 0 ? "Resolve issue" : "Resume"} step {totalSteps ? homeNext : ""} <Icon name="forward" size={18} /></button>
        </div>
      ) : (
        <div className="card primary-action">
          <h2>What needs doing?</h2>
          <p className="muted">Start from an approved procedure, or record new expert knowledge as a tutorial. Approved work keeps running without a connection.</p>
          <div className="row"><button className="btn" onClick={() => go("library")}>Find an approved procedure</button><button className="btn secondary" onClick={() => go("tutorials")}>Record a tutorial</button></div>
        </div>
      )}
      {recentFinishes.filter((r) => !jobs.some((j) => j.id === r.id)).slice(0, 3).length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h3 style={{ marginTop: 0 }}>Recently completed on this device</h3>
          {recentFinishes.filter((r) => !jobs.some((j) => j.id === r.id)).slice(0, 3).map((r) => (
            <p key={r.id} className="list-row">
              <strong>{r.title}</strong>{" "}
              <span className={`tag ${r.finish_outcome === "completed" ? "approved" : "warn"}`}>{r.finish_outcome === "completed" ? "completed" : "finished with exceptions"}</span>{" "}
              <span className="muted small-text">saved on this device — appears here until the server confirms it</span>{" "}
              <button className="btn small secondary" onClick={() => go("activity")}>View in Activity</button>
            </p>
          ))}
        </div>
      )}
      <div className="grid" style={{ marginBottom: 14 }}>
        <button className="card" style={{ textAlign: "left", margin: 0 }} onClick={() => go("tutorials")}>
          <span className="tool-pill" style={{ background: "var(--primary-container)", color: "#fff" }}><Icon name="videocam" size={20} /></span>
          <span className="panel-title" style={{ display: "block", marginTop: 8 }}>Tutorials</span>
          <span className="muted small-text">Record and refine expert knowledge</span>
        </button>
        <button className="card" style={{ textAlign: "left", margin: 0 }} onClick={() => go("library")}>
          <span className="tool-pill"><Icon name="book" size={20} /></span>
          <span className="panel-title" style={{ display: "block", marginTop: 8 }}>Procedure Library</span>
          <span className="muted small-text">{approved.length} approved guide{approved.length === 1 ? "" : "s"}</span>
        </button>
      </div>
      {reviewQueue.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <h3><Icon name="flag" size={17} /> Review pipeline</h3>
          {pendingReview.length > 0 && (
            <div className="card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>Pending approval</strong>
                <span className="badge review">{pendingReview.length} awaiting decision</span>
              </div>
              <p className="muted small-text">AI drafts are never executable until a reviewer approves them.</p>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="muted small-text">{pendingReview[0].title} · v{pendingReview[0].version_number}</span>
                <button className="btn secondary" onClick={() => openReview(pendingReview[0].id)}>Review revision <Icon name="chevronRight" size={17} /></button>
              </div>
            </div>
          )}
          {drafts.length > 0 && (
            <p className="muted small-text">{drafts.length} draft{drafts.length === 1 ? "" : "s"} in progress — continue editing from the Procedures library.</p>
          )}
          {returned.length > 0 && (
            <p className="muted small-text">{returned.length} returned for changes — edit and resubmit from the Procedures library.</p>
          )}
        </div>
      )}
      <div>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>Field work</h3>
          <span className="muted small-text">Active · needs attention · completed</span>
        </div>
        {(() => {
          const openJobs = jobs.filter((j) => j.status !== "finished");
          const doneJobs = jobs.filter((j) => j.status === "finished");
          const isBlockedLocal = (blockedSteps?.length || 0) > 0;
          return (
            <>
              {activeJob && (
                <div className="card" style={{ marginBottom: 10, borderLeft: isBlockedLocal ? "4px solid var(--danger)" : undefined }}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <strong>{isBlockedLocal ? "Needs attention" : "My active work"}</strong>
                    {isBlockedLocal
                      ? <span className="badge crit">Blocked — resolve issue</span>
                      : <span className="badge info">In progress — continue job</span>}
                  </div>
                  <p className="muted small-text" style={{ margin: "6px 0 0" }}>
                    {activeJob.title} · step {homeNext} of {totalSteps} · saved on this device{pending > 0 ? ` · ${pending} update${pending === 1 ? "" : "s"} pending sync` : " · synced"}
                  </p>
                </div>
              )}
              {openJobs.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <p className="eyebrow" style={{ margin: "0 0 6px" }}>Ready to continue (server-confirmed open jobs)</p>
                  <div className="recent-grid">
                    {openJobs.slice(0, 4).map((j) => (
                      <div key={j.id} className="card" style={{ marginBottom: 0 }}>
                        <div className="row" style={{ justifyContent: "space-between" }}>
                          <div style={{ minWidth: 0 }}>
                            <strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>{j.procedure_title}</strong>
                            <span className="muted small-text num">{new Date(j.started_at).toLocaleString()} · {j.events} event{j.events === 1 ? "" : "s"} · server-confirmed</span>
                          </div>
                          <span className="badge info">In progress</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {doneJobs.length === 0 && recentFinishes.filter((r) => !jobs.some((j) => j.id === r.id)).length === 0 ? (
                <div className="card"><div className="empty">
                  <h4 style={{ margin: 0 }}>No completed jobs yet</h4>
                  <p className="muted small-text">Finished jobs appear here with a completion summary.</p>
                </div></div>
              ) : (
                <div>
                  <p className="eyebrow" style={{ margin: "0 0 6px" }}>Recently completed</p>
                  <div className="recent-grid">
                    {doneJobs.slice(0, 4).map((j) => (
                      <div key={j.id} className="card" style={{ marginBottom: 0 }}>
                        <div className="row" style={{ justifyContent: "space-between" }}>
                          <div style={{ minWidth: 0 }}>
                            <strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>{j.procedure_title}</strong>
                            <span className="muted small-text num">{j.ended_at ? new Date(j.ended_at).toLocaleString() : new Date(j.started_at).toLocaleString()} · server-confirmed</span>
                          </div>
                          {j.outcome === "completed"
                            ? <span className="badge ok">Completed — view summary</span>
                            : <span className="badge warn">{j.outcome || "Completed"} — view summary</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          );
        })()}
        {jobs.length > 0 && <button className="btn secondary" style={{ marginTop: 12 }} onClick={() => go("activity")}>View all activity</button>}
      </div>
    </div>
  );
}

function ProcessingLog() {
  const [items, setItems] = useState<ProcEventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [entity, setEntity] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  async function load() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "50", offset: "0" });
      if (entity) params.set("entity_type", entity);
      if (model) params.set("model", model);
      if (status) params.set("status", status);
      if (q.trim()) params.set("q", q.trim());
      const r = await api.get<{ total: number; items: ProcEventRow[] }>(`/api/processing/events?${params}`);
      setItems(r.items || []); setTotal(r.total || 0);
    } catch { /* offline: list stays */ }
    setLoading(false);
  }
  useEffect(() => { void load(); }, []);
  // Live tail: poll newest-first while enabled. Pauses itself on failure.
  useEffect(() => {
    if (!live) return;
    let alive = true;
    const tick = async () => {
      try {
        const params = new URLSearchParams({ limit: "50", offset: "0" });
        if (entity) params.set("entity_type", entity);
        if (model) params.set("model", model);
        if (status) params.set("status", status);
        if (q.trim()) params.set("q", q.trim());
        const r = await api.get<{ total: number; items: ProcEventRow[] }>(`/api/processing/events?${params}`);
        if (!alive) return;
        setItems(r.items || []); setTotal(r.total || 0);
      } catch { if (alive) setLive(false); }
    };
    void tick();
    const t = window.setInterval(tick, 3000);
    return () => { alive = false; window.clearInterval(t); };
  }, [live]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="card">
      <h3>Processing log</h3>
      <p className="muted small-text">Every AI/model stage across tutorials, capture and review — newest first. Same correlation IDs appear in the server logs.</p>
      <div className="row">
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Filter by entity" style={{ flex: "1 1 140px" }}>
          <option value="">All entities</option><option value="tutorial">Tutorial</option><option value="capture">Capture</option><option value="procedure">Procedure</option>
        </select>
        <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Model (e.g. sam-3.1)" aria-label="Filter by model" style={{ flex: "1 1 140px" }} />
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status" style={{ flex: "1 1 140px" }}>
          <option value="">Any status</option><option value="succeeded">Succeeded</option><option value="ok">OK</option><option value="failed">Failed</option><option value="error">Error</option><option value="simulated">Simulated</option><option value="no_match">No match</option><option value="needs_tap">Needs tap</option>
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search prompt, note…" aria-label="Search processing log" style={{ flex: "2 1 160px" }} />
        <button className="btn small" onClick={() => void load()} disabled={loading}>{loading ? "Loading…" : "Filter"}</button>
        <button className="btn small secondary" aria-pressed={live} onClick={() => setLive((v) => !v)}>{live ? "⏸ Pause live" : "▶ Live tail"}</button>
      </div>
      {items.length === 0 ? <div className="empty">No processing events match. Run a tutorial or capture to generate the first entries.</div>
        : items.map((e) => (
          <div key={e.id} className="list-row">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{e.stage}</strong>
              <span className={`tag ${e.status === "succeeded" || e.status === "ok" ? "approved" : e.status === "failed" || e.status === "error" ? "error" : "warn"}`}>{e.status}</span>
            </div>
            <p className="muted small-text" style={{ margin: "2px 0" }}>
              {e.entity_type}:{e.entity_id.slice(0, 8)}…{e.operation ? ` · ${e.operation}` : ""}{e.model ? ` · ${e.model}` : ""}{e.duration_ms != null ? ` · ${e.duration_ms} ms` : ""} · {new Date(e.created_at).toLocaleString()}
            </p>
          </div>
        ))}
      {total > items.length && <p className="muted small-text">Showing {items.length} of {total} — refine the filters to narrow down.</p>}
    </div>
  );
}

function Activity({ jobs, pending, pendingReview, reload, go, syncNow, syncing, role, notify, onProposeRevision, recent, onDismissRecent }: { jobs: JobRow[]; pending: number; pendingReview: number; reload: () => void; go: (v: View) => void; syncNow: () => void; syncing: boolean; role: Role; notify: (s: string, kind?: "ok" | "error" | "info") => void; onProposeRevision: (versionId: string) => void; recent: LocalJob[]; onDismissRecent: (id: string) => void }) {
  const fresh = recent.filter((r) => !jobs.some((j) => j.id === r.id));
  return (
    <div>
      <div className="card"><h2><Icon name="schedule" size={20} /> Activity</h2>
        <p>{pending} update{pending === 1 ? "" : "s"} pending synchronization. Items are only marked synced after the server acknowledges them.</p>
        <div className="row">
          <button className="btn secondary" onClick={() => go("review")}><Icon name="flag" size={17} /> Review queue{pendingReview ? ` (${pendingReview})` : ""}</button>
          <button className="btn secondary" onClick={() => go("manuals")}><Icon name="book" size={17} /> Manuals</button>
          <button className="btn secondary" onClick={() => go("settings")}><Icon name="cog" size={17} /> Settings</button>
        </div>
      </div>
      {fresh.map((r) => <CompletionSummary key={r.id} job={r} go={go} onDismiss={() => onDismissRecent(r.id)} />)}
      <SyncDiagnostics pending={pending} syncing={syncing} onSync={syncNow} onChanged={reload} notify={notify} />
      <History jobs={jobs} reload={reload} role={role} notify={notify} onProposeRevision={onProposeRevision} />
      <ProcessingLog />
    </div>
  );
}

function CompletionSummary({ job, go, onDismiss }: { job: LocalJob; go: (v: View) => void; onDismiss: () => void }) {
  const [unsynced, setUnsynced] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    pendingForJob(job.id).then((p) => { if (alive) setUnsynced(p.total); }).catch(() => undefined);
    return () => { alive = false; };
  }, [job.id]);
  const steps = Object.keys(job.stepStates).length;
  const done = Object.values(job.stepStates).filter((s) => s === "done").length;
  const skipped = Object.values(job.stepStates).filter((s) => s === "skipped").length;
  const blocked = Object.values(job.stepStates).filter((s) => s === "blocked").length;
  const ok = job.finish_outcome === "completed";
  return (
    <div className="card accent-edge" role="status" aria-label="Job completion summary">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className={`badge ${ok ? "ok" : "warn"}`}>{ok ? "Job completed" : "Finished with exceptions"}</span>
        <span className="muted small-text">{unsynced == null ? "Checking sync…" : unsynced > 0 ? `${unsynced} item${unsynced === 1 ? "" : "s"} waiting to sync` : "Synced with server"}</span>
      </div>
      <h3 style={{ margin: "8px 0 4px" }}>{job.title}</h3>
      <p className="muted small-text" style={{ margin: 0 }}>
        {done} completed · {skipped} skipped · {blocked} blocked of {steps} recorded steps.
        {ok ? " All required steps completed." : " Skipped/blocked steps are listed above — the outcome reflects the exceptions."}
      </p>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn small" onClick={() => go("home")}>Back to Workbench</button>
        <button className="btn small secondary" onClick={onDismiss}>Got it</button>
      </div>
    </div>
  );
}

function ProcedureDetail({ title, version, cached, startJob, cache, openReview, go }: { title: string; version: Version | null; cached: boolean; startJob: () => void; cache: () => void; openReview: () => void; go: (v: View) => void }) {
  if (!version) return <div className="card"><div className="empty"><h3>No procedure selected</h3><p>Pick a procedure from the library to inspect its approved revision, steps, and tooling.</p><button className="btn" onClick={() => go("library")}>Open procedure library</button></div></div>;
  const tools = [...new Set(version.steps.flatMap((s) => s.required_tools || []))];
  const safety = ((version.source_evidence as { safety_notes?: string[] }).safety_notes || []).filter(Boolean);
  const canStart = version.status === "approved" && version.steps.length > 0;
  const guideFormat = typeof (version.source_evidence as { guide_format?: unknown }).guide_format === "string" ? (version.source_evidence as { guide_format: string }).guide_format : "";
  return (
    <div>
      <button className="btn small secondary" onClick={() => go("library")}><Icon name="back" size={17} /> Library</button>
      <div className="detail-layout" style={{ marginTop: 10 }}>
      <div className="card" style={{ marginTop: 0 }}>
        <div className="proc-badges">
          {version.status === "approved"
            ? <span className="badge ok"><Icon name="verified" size={13} /> Approved (Rev {version.version_number})</span>
            : version.status === "pending_review"
              ? <span className="badge review"><Icon name="warning" size={13} /> Pending review · Draft v{version.version_number}</span>
              : <span className="badge neutral"><Icon name="note" size={13} /> {version.status} · v{version.version_number}</span>}
          {cached ? <span className="badge ok"><Icon name="check" size={13} /> Offline cached</span> : <span className="badge neutral"><Icon name="cloudDone" size={13} /> Server only</span>}
          {version.ai_simulated ? <span className="badge info">AI draft · simulated model</span> : version.ai_model ? <span className="badge info">AI draft · {version.ai_model}</span> : null}
          {guideFormat ? <span className="badge info"><Icon name="note" size={13} /> {({ work_instruction: "Work instruction", reference_manual: "Reference manual", interactive: "Interactive guided execution" } as Record<string, string>)[guideFormat] || guideFormat}</span> : null}
        </div>
        <h2 style={{ marginTop: 8 }}>{title || "Procedure"}</h2>
        <p className="muted">{version.summary}</p>
        {version.prerequisites && <p><strong>Prerequisites:</strong> {version.prerequisites}</p>}
        {safety.length > 0 && (
          <div className="safety-banner"><Icon name="warning" size={20} /><div><strong>Mandatory safety</strong><p style={{ margin: "4px 0 0" }}>{safety.join(" ")}</p></div></div>
        )}
        {tools.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <span className="eyebrow">Required field tooling</span>
            <div className="tool-pills" style={{ marginTop: 6 }}>{tools.map((t) => <span key={t} className="tool-pill">{t}</span>)}</div>
          </div>
        )}
        <div className="proc-actions" style={{ marginTop: 12 }}>
          {canStart && <button className="btn" onClick={startJob}><Icon name="play" size={19} /> Start job</button>}
          {version.status !== "approved" && <button className="btn review" onClick={openReview}><Icon name="flag" size={19} /> View revision history</button>}
          <button className="btn secondary" onClick={cache}><Icon name="download" size={19} /> {cached ? "Update offline copy" : "Save for offline use"}</button>
        </div>
        {!canStart && version.status === "approved" && <p className="muted small-text">This approved version has no steps, so a guided job cannot start. Ask a reviewer to create a revision with steps.</p>}
        {version.status !== "approved" && <p className="muted small-text">Drafts and pending versions cannot start jobs. Only human-approved versions are executable.</p>}
      </div>
      <div className="card">
        <h3>Steps ({version.steps.length})</h3>
        {version.steps.length === 0 && <div className="empty">No steps in this version yet.</div>}
        {[...version.steps].sort((a, b) => a.step_order - b.step_order).map((s) => (
          <div key={s.id} className="list-row">
            <p style={{ margin: "0 0 4px" }}><strong>Step {s.step_order}: {s.title}</strong></p>
            <p className="muted small-text" style={{ margin: "0 0 4px" }}>{s.instruction}</p>
            {s.expected_result && <p className="small-text" style={{ margin: 0 }}><strong>Expected:</strong> {s.expected_result}</p>}
          </div>
        ))}
      </div>
      </div>
    </div>
  );
}

function Library({ procs, cachedIds, reload, startJob, openVersion, cache }: { procs: ProcSummary[]; cachedIds: Set<string>; reload: () => void; startJob: (p: ProcSummary) => void; openVersion: (id: string) => void; cache: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "approved" | "offline" | "drafts" | "review">("all");
  const [cat, setCat] = useState<string>("all");
  const [sort, setSort] = useState<"updated" | "title">("updated");
  const isOfflineReady = (p: ProcSummary) => !!(p.approved_version_id && cachedIds.has(p.approved_version_id));
  const hasDraft = (p: ProcSummary) => p.versions.some((v) => v.status === "draft");
  const hasReturned = (p: ProcSummary) => p.versions.some((v) => v.status === "rejected");
  const needsReview = (p: ProcSummary) => p.versions.some((v) => v.status === "pending_review");
  const counts = {
    all: procs.length,
    approved: procs.filter((p) => p.approved_version_id).length,
    offline: procs.filter(isOfflineReady).length,
    drafts: procs.filter((p) => hasDraft(p) || hasReturned(p)).length,
    review: procs.filter(needsReview).length,
  };
  const cats = [...new Set(procs.map((p) => (p.asset_type || "").trim()).filter(Boolean))].sort();
  const list = procs
    .filter((p) => (p.title + " " + p.id + " " + (p.asset_type || "")).toLowerCase().includes(q.toLowerCase()))
    .filter((p) => filter === "all" || (filter === "approved" ? !!p.approved_version_id : filter === "offline" ? isOfflineReady(p) : filter === "drafts" ? hasDraft(p) : needsReview(p)))
    .filter((p) => cat === "all" || (p.asset_type || "").trim() === cat)
    .sort((a, b) => sort === "title" ? a.title.localeCompare(b.title) : (b.updated_at || "").localeCompare(a.updated_at || ""));
  const tab = (key: typeof filter, label: string) => (
    <button key={key} className="filter-tab" aria-pressed={filter === key} onClick={() => setFilter(key)}>
      {key === "offline" && <Icon name="download" size={15} />}{label} <span className="num">({counts[key]})</span>
    </button>
  );
  const resetFilters = () => { setQ(""); setFilter("all"); setCat("all"); };
  return (
    <div>
      <section className="card">
        <div className="row" style={{ justifyContent: "flex-start" }}>
          <span className="tool-pill" style={{ background: "var(--primary-container)", color: "#fff" }}><Icon name="cloudDone" size={20} /></span>
          <div>
            <span className="eyebrow">Offline ready · sector storage</span>
            <p className="small-text" style={{ margin: 0 }}>{counts.offline} procedure{counts.offline === 1 ? "" : "s"} cached with full content for zero-connectivity field zones.</p>
          </div>
        </div>
      </section>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2>Procedure Library</h2>
          <p className="muted" style={{ marginTop: -8 }}>Approved maintenance guides &amp; pending revisions</p>
        </div>
        <button className="btn small secondary icon-only" aria-label={sort === "updated" ? "Sorted by most recently updated. Activate to sort by title." : "Sorted by title. Activate to sort by most recently updated."} onClick={() => setSort(sort === "updated" ? "title" : "updated")}><Icon name="sort" size={18} /> {sort === "updated" ? "Updated" : "Title"}</button>
      </div>
      <div className="panel" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <Icon name="search" size={20} />
        <label htmlFor="proc-search" className="visually-hidden">Search procedures</label>
        <input id="proc-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, procedure ID, or equipment type..." style={{ border: 0, background: "transparent", minHeight: 40, padding: "6px 0" }} />
        {q && <button className="btn small secondary icon-only" aria-label="Clear search" onClick={() => setQ("")}><Icon name="close" size={17} /></button>}
      </div>
      <div className="filter-tabs" role="group" aria-label="Status filter">
        {tab("all", "All")}{tab("approved", "Approved")}{tab("offline", "Downloaded")}{tab("drafts", "Drafts & returned")}{tab("review", "In review")}
      </div>
      {cats.length > 1 && (
        <div className="cat-pills" role="group" aria-label="Equipment category">
          <span className="eyebrow"><Icon name="grid" size={13} /> Category:</span>
          <button className="cat-pill" aria-pressed={cat === "all"} onClick={() => setCat("all")}>All gear</button>
          {cats.map((c) => <button key={c} className="cat-pill" aria-pressed={cat === c} onClick={() => setCat(c)}>{c}</button>)}
        </div>
      )}
      <div className="proc-grid" style={{ marginTop: 10 }}>
      {list.length === 0 && (
        <div className="card"><div className="empty">
          <p><strong>No matching procedures</strong></p>
          <p>Try adjusting equipment tags or clearing the search query.</p>
          <button className="btn secondary" style={{ marginTop: 8 }} onClick={resetFilters}>Clear filter</button>
        </div></div>
      )}
      {list.map((p) => {
        const offlineReady = isOfflineReady(p);
        const review = p.versions.find((v) => v.status === "pending_review");
        const draft = p.versions.find((v) => v.status === "draft");
        const returned = p.versions.find((v) => v.status === "rejected");
        const approvedV = p.versions.filter((v) => v.status === "approved").slice(-1)[0];
        return (
          <article key={p.id} className="proc-card">
            <div className="proc-badges">
              {approvedV
                ? <span className="badge ok"><Icon name="verified" size={13} /> Approved (Rev {approvedV.version_number})</span>
                : review ? <span className="badge review"><Icon name="warning" size={13} /> Pending review · Draft v{review.version_number}</span>
                : draft ? <span className="badge neutral"><Icon name="note" size={13} /> Draft v{draft.version_number} · in progress</span>
                : returned ? <span className="badge warn"><Icon name="note" size={13} /> Returned v{returned.version_number} · needs changes</span>
                : <span className="badge neutral">No approved version</span>}
              {p.approved_version_id && (offlineReady
                ? <span className="badge ok"><Icon name="check" size={13} /> Offline cached</span>
                : <span className="badge neutral"><Icon name="cloudDone" size={13} /> Not downloaded</span>)}
            </div>
            <div>
              <h3 style={{ marginBottom: 2 }}>{p.title}</h3>
              <p className="muted small-text" style={{ margin: 0 }}>
                {p.asset_type ? <>{p.asset_type} · </> : ""}{p.versions.length} version{p.versions.length === 1 ? "" : "s"}{p.updated_at ? <> · Updated {new Date(p.updated_at).toLocaleDateString()}</> : ""}
              </p>
            </div>
            {review && (
              <div className="panel">
                <span className="small-text"><Icon name="bot" size={15} /> <strong>AI-generated draft.</strong> <span className="muted">Not executable in the field until reviewed by a Level-3 specialist.</span></span>
              </div>
            )}
            <div className="proc-actions">
              {p.approved_version_id
                ? <><button className="btn" onClick={() => startJob(p)}><Icon name="play" size={19} /> Start Job</button>
                  <button className="btn secondary" aria-label={offlineReady ? `Update offline copy of ${p.title}` : `Download ${p.title} for offline use`} onClick={() => p.approved_version_id && cache(p.approved_version_id)}><Icon name="download" size={19} /></button></>
                : review
                  ? <button className="btn review" onClick={() => openVersion(review.id)}><Icon name="flag" size={19} /> Review revision</button>
                  : draft
                    ? <button className="btn secondary" onClick={() => openVersion(draft.id)}><Icon name="edit" size={19} /> Continue editing</button>
                    : returned
                      ? <button className="btn secondary" onClick={() => openVersion(returned.id)}><Icon name="edit" size={19} /> Revise &amp; resubmit</button>
                      : null}
              {(review || draft || returned || approvedV) && (
                <button className="btn secondary" aria-label={`View details of ${p.title}`} onClick={() => openVersion((review || draft || returned || approvedV)!.id)}><Icon name="eye" size={19} /></button>
              )}
            </div>
          </article>
        );
      })}
      </div>
      <button className="btn small secondary" onClick={reload} style={{ marginTop: 10 }}><Icon name="sync" size={16} /> Refresh from server</button>
    </div>
  );
}

interface SegMask { svg_path: string; width: number; height: number }
interface SegObject { object_id: number; bbox_norm: number[]; confidence?: number | null; mask?: SegMask | null }
interface SegGeometry { bbox_norm: number[]; label: string; mask?: SegMask | null; objects?: SegObject[]; image_size?: number[] }

function TutorialsView({ onOpenStudio, refreshKey }: { onOpenStudio: (t: LibraryItem) => void; refreshKey?: number }) {
  // Two equal ways to create a tutorial — recording and uploading feed the
  // same TutorialJob pipeline. Analysis mode is shared by both.
  const [showRecord, setShowRecord] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [mode, setMode] = useState<AnalysisMode>("auto");
  const [libKey, setLibKey] = useState(0);
  useEffect(() => { void requestPersistentStorage(); }, []);
  useEffect(() => { setLibKey((n) => n + 1); }, [refreshKey]);
  return (
    <div>
      <span className="eyebrow">Knowledge capture</span>
      <h2>Tutorials</h2>
      <p className="muted" style={{ marginTop: -8 }}>Turn a hands-on recording into a reviewed, field-ready procedure.</p>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h3 style={{ margin: 0 }}>Record a tutorial</h3>
            <p className="muted small-text" style={{ margin: "2px 0 0" }}>Record a video with narration. Processing runs on the server after upload.</p>
          </div>
          <button className="btn small secondary" aria-expanded={showRecord} onClick={() => setShowRecord((v) => !v)}>{showRecord ? "Hide recorder" : "Record a tutorial"}</button>
        </div>
        {showRecord && (
          <div style={{ marginTop: 10 }}>
            <ModeSelector mode={mode} onModeChange={setMode} />
            <TutorialMode hideLibrary analysisMode={mode} onOpenStudio={(t) => onOpenStudio({ id: t.id, access_token: t.access_token, title: t.title } as LibraryItem)} />
          </div>
        )}
      </div>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h3 style={{ margin: 0 }}>Upload an existing video</h3>
            <p className="muted small-text" style={{ margin: "2px 0 0" }}>Already have the recording on this device? Upload it instead — same pipeline, same library.</p>
          </div>
          <button className="btn small secondary" aria-expanded={showUpload} onClick={() => setShowUpload((v) => !v)}>{showUpload ? "Hide upload" : "Upload existing video"}</button>
        </div>
        {showUpload && (
          <div style={{ marginTop: 10 }}>
            <TutorialUpload mode={mode} onModeChange={setMode} onOpenStudio={onOpenStudio} onUploaded={() => setLibKey((n) => n + 1)} />
          </div>
        )}
      </div>
      <QueuedUploads onChanged={() => setLibKey((n) => n + 1)} />
      <TutorialLibrary onOpen={onOpenStudio} refreshKey={(refreshKey || 0) + libKey} />
    </div>
  );
}

function SegmentOverlay({ geometry, simulated, imageUrl, onConfirm }: { geometry: SegGeometry; simulated: boolean; imageUrl?: string | null; onConfirm?: (confirmed: boolean) => Promise<void> }) {
  const [confirmed, setConfirmed] = useState<string>("");
  const objects: SegObject[] = geometry.objects?.length ? geometry.objects : geometry.bbox_norm?.length === 4 ? [{ object_id: 0, bbox_norm: geometry.bbox_norm, mask: geometry.mask }] : [];
  return (
    <div style={{ marginTop: 14 }}>
      <p><span className="tag ai">{simulated ? "AI segmentation · simulated" : "AI segmentation · SAM 3.1 live"}</span> Prompt: “{geometry.label}”{objects.length > 1 ? ` · ${objects.length} matches` : ""}</p>
      {objects.length === 0 ? (
        <div className="notice warn" role="status">No highlight for this prompt — recovery options are below.</div>
      ) : (
        <div className="overlay-wrap" role="img" aria-label={`Photo with highlight on ${geometry.label}`}>
          {imageUrl ? (
            <img src={imageUrl} alt="" />
          ) : (
            <div style={{ padding: 24, color: "#dfe9e3" }}>Photo not available in this browser session — the highlight below uses the stored segmentation coordinates. Re-attach the photo to see it on the image.</div>
          )}
          {objects.map((o) => {
            const [x1, y1, x2, y2] = o.bbox_norm;
            return (
              <div key={o.object_id} className="bbox" style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}>
                <span>{geometry.label}{o.confidence != null ? ` · ${Math.round(o.confidence * 100)}%` : ""}</span>
                {o.mask?.svg_path && (
                  <svg className="mask-svg" viewBox={`0 0 ${o.mask.width} ${o.mask.height}`} preserveAspectRatio="none" aria-hidden="true">
                    <path d={o.mask.svg_path} />
                  </svg>
                )}
              </div>
            );
          })}
        </div>
      )}
      {objects.length > 0 && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn small" onClick={async () => { try { await onConfirm?.(true); setConfirmed("Confirmed and saved — this is the intended component."); } catch { setConfirmed("Confirmed locally, but saving failed — check connection."); } }}>Confirm highlight</button>
          <button className="btn small danger" onClick={async () => { try { await onConfirm?.(false); setConfirmed("Rejected and saved — retry with a clearer prompt or another photo."); } catch { setConfirmed("Rejected locally, but saving failed — check connection."); } }}>Reject highlight</button>
        </div>
      )}
      {confirmed && <div className="notice ok" role="status">{confirmed}</div>}
      <p className="muted">New segmentation needs connectivity. Confirmed highlights on downloaded procedures remain visible offline.</p>
    </div>
  );
}

function ReviewEvidence({ versionId }: { versionId: string }) {
  const [items, setItems] = useState<EvidenceItem[]>([]);
  useEffect(() => {
    let alive = true;
    api.get<{ evidence: EvidenceItem[] }>(`/api/procedure-versions/${versionId}/evidence`)
      .then((r) => { if (alive) setItems(r.evidence || []); })
      .catch(() => { if (alive) setItems([]); });
    return () => { alive = false; };
  }, [versionId]);
  if (!items.length) return <p className="muted">No linked source evidence was returned for this version. Treat unsupported steps with extra care.</p>;
  return (
    <div>
      <h4>Source evidence</h4>
      {items.map((e) => (
        <div key={e.id} className="list-row">
          <span className="tag">{e.evidence_type}</span> {e.description || e.source_reference}
          {e.text_content && <p className="muted small-text">“{e.text_content.slice(0, 220)}”</p>}
          {e.image_url && <img src={e.image_url} alt="Source evidence" style={{ maxWidth: 260, borderRadius: 8, display: "block", marginTop: 6 }} />}
          {e.segmentation && <p className="muted small-text">Segmentation: {e.segmentation.status} · {e.segmentation.simulated ? "simulated" : e.segmentation.model} · prompt “{e.segmentation.prompt}”</p>}
        </div>
      ))}
    </div>
  );
}

function ProposalBanner({ version }: { version: Version }) {
  const proposal = (version.source_evidence as { proposal?: {
    job_id?: string; base_version_id?: string; base_version_number?: number; base_changed_since_job?: boolean;
    feedback_event_id?: string; feedback_summary?: { step_outcomes?: { step_id: string; status: string; note: string }[]; missing_info?: string; unexpected?: string; visual_correct?: boolean | null; assistance_needed?: boolean; overall?: string };
    changes?: { step_order: number; field: string; before: string; after: string; reason: string; confidence: string }[];
    simulated?: boolean; model?: string; note?: string;
  } }).proposal;
  if (!proposal) return null;
  const changes = proposal.changes || [];
  const fb = proposal.feedback_summary || {};
  const flagged = (fb.step_outcomes || []).filter((o) => o.status !== "ok");
  return (
    <div className="notice info" role="status">
      <strong><Icon name="flag" size={17} /> Field-feedback proposal.</strong>{" "}
      Suggested from job <span className="num">{(proposal.job_id || "").slice(0, 8)}</span>
      {proposal.base_changed_since_job ? " (based on the latest approved revision — the job ran an older one)" : ` (based on approved v${proposal.base_version_number ?? "?"})`}.{" "}
      {proposal.simulated ? <span className="tag warn">simulated analysis (no Meta key)</span> : <span className="tag ai">Muse Spark analysis{proposal.model ? ` · ${proposal.model}` : ""}</span>}{" "}
      Review every change below before approving — nothing here modifies the approved revision until you approve this draft.
      {changes.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {changes.map((c, i) => (
            <div key={i} className="card" style={{ marginBottom: 8 }}>
              <strong>Step {c.step_order} · {c.field.replace(/_/g, " ")}</strong>{" "}
              <span className="tag">{c.confidence} confidence</span>
              <p className="small-text" style={{ margin: "6px 0 0" }}><span className="muted">Before:</span> {c.before || <em className="muted">empty</em>}</p>
              <p className="small-text" style={{ margin: "4px 0 0" }}><span className="muted">After:</span> {c.after}</p>
              {c.reason && <p className="muted small-text" style={{ margin: "4px 0 0" }}>Why: {c.reason}</p>}
            </div>
          ))}
        </div>
      )}
      {(flagged.length > 0 || fb.missing_info || fb.unexpected || fb.overall) && (
        <details style={{ marginTop: 6 }}>
          <summary className="small-text"><strong>Technician feedback behind this proposal</strong></summary>
          {flagged.length > 0 && <p className="small-text">Flagged steps: {flagged.map((o) => `${o.status}${o.note ? ` — “${o.note}”` : ""}`).join("; ")}</p>}
          {fb.missing_info && <p className="small-text"><strong>Missing info:</strong> {fb.missing_info}</p>}
          {fb.unexpected && <p className="small-text"><strong>Unexpected condition:</strong> {fb.unexpected}</p>}
          {fb.visual_correct === false && <p className="small-text"><strong>Visual guidance reported incorrect</strong> by the technician.</p>}
          {fb.overall && <p className="small-text"><strong>Overall:</strong> {fb.overall}</p>}
        </details>
      )}
    </div>
  );
}

function ReviewView({ version, setVersion, procs, openVersion, role, reload, notify }: { version: Version | null; setVersion: (v: Version | null) => void; procs: ProcSummary[]; openVersion: (id: string) => Promise<Version | null>; role: Role; reload: () => void; notify: (s: string, kind?: "ok" | "error" | "info") => void }) {
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [confirmApprove, setConfirmApprove] = useState(false);
  const queue = procs.flatMap((p) => p.versions.filter((v) => v.status === "pending_review" || v.status === "draft" || v.status === "rejected").map((v) => ({ ...v, title: p.title })));
  const [queueTab, setQueueTab] = useState<"pending" | "draft" | "returned">("pending");
  const queueGroups: Record<"pending" | "draft" | "returned", typeof queue> = {
    pending: queue.filter((v) => v.status === "pending_review"),
    draft: queue.filter((v) => v.status === "draft"),
    returned: queue.filter((v) => v.status === "rejected"),
  };
  const shownQueue = queueGroups[queueTab];
  const canReview = role === "reviewer" || role === "expert";
  const autoOpened = useRef<string | null>(null);
  useEffect(() => {
    if (!version && queue.length > 0 && autoOpened.current !== queue[0].id) {
      autoOpened.current = queue[0].id;
      openVersion(queue[0].id).then((v) => { if (v) setVersion(v); else autoOpened.current = null; });
    }
  });
  async function act(path: string, ok: string) {
    if (!version) return;
    if (path === "reject" && !comment.trim()) { notify("Add a rejection reason first so the author knows what to fix.", "error"); return; }
    setBusy(true);
    try { await api.post(`/api/procedure-versions/${version.id}/${path}`, { comment: comment || "Reviewed in FieldGuard" }); notify(ok); setComment(""); setConfirmApprove(false); reload(); const v = await openVersion(version.id); setVersion(v); }
    catch (e) { notify(e instanceof Error ? e.message : "Action failed", "error"); }
    finally { setBusy(false); }
  }
  async function saveEdits() {
    if (!version) return; setBusy(true);
    try { const v = await api.put<Version>(`/api/procedure-versions/${version.id}`, { summary: version.summary, prerequisites: version.prerequisites, steps: version.steps }); setVersion(v); notify("Draft edits saved. Approved versions are never edited in place."); }
    catch (e) { notify(e instanceof Error ? e.message : "Save failed", "error"); }
    finally { setBusy(false); }
  }
  return (
    <div className="review-layout">
      <div className="card"><h2><Icon name="flag" size={20} /> Review &amp; approvals</h2>
        <p className="muted">AI drafts are never approved automatically. {canReview ? "You can approve or reject versions pending review." : "Approval needs the Reviewer demo role (Activity → Settings) — the server enforces this."} Signed-in role: <strong>{role}</strong>.</p>
        <div className="filter-tabs" role="group" aria-label="Review queue">
          {(["pending", "draft", "returned"] as const).map((t) => (
            <button key={t} className="filter-tab" aria-pressed={queueTab === t} onClick={() => setQueueTab(t)}>
              {t === "pending" ? "Pending review" : t === "draft" ? "Drafts in progress" : "Returned for changes"} <span className="num">({queueGroups[t].length})</span>
            </button>
          ))}
        </div>
        {queue.length === 0
          ? <div className="empty">Queue empty — generate a draft in Capture.</div>
          : shownQueue.length === 0
          ? <div className="empty">Nothing here — try another queue tab.</div>
          : shownQueue.map((v) => (
            <div key={v.id} className="list-row">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ minWidth: 0 }}>
                  <strong style={{ display: "block" }}>{v.title}</strong>
                  <span className="muted small-text">v{v.version_number} · {v.status.replace("_", " ")}</span>
                </div>
                <button className="btn small secondary" onClick={async () => { const ver = await openVersion(v.id); if (ver) setVersion(ver); else notify("That version is not available offline yet.", "error"); }}>Review draft &amp; evidence</button>
              </div>
            </div>
          ))}
      </div>
      {version && (
        <div className="card">
          <div className="proc-badges">
            <span className={`badge ${version.status === "approved" ? "ok" : version.status === "pending_review" ? "review" : "neutral"}`}>{version.status.replace("_", " ")} · v{version.version_number}</span>
            {version.ai_simulated ? <span className="badge info"><Icon name="bot" size={13} /> AI draft · simulated model (no Meta key)</span> : version.ai_model ? <span className="badge info"><Icon name="bot" size={13} /> AI draft · {version.ai_model}</span> : <span className="badge neutral">Seeded demo data</span>}
            {typeof (version.source_evidence as { guide_format?: unknown }).guide_format === "string" && (version.source_evidence as { guide_format?: string }).guide_format ? (
              <span className="badge info"><Icon name="note" size={13} /> {({ work_instruction: "Work instruction", reference_manual: "Reference manual", interactive: "Interactive guided execution" } as Record<string, string>)[(version.source_evidence as { guide_format: string }).guide_format] || (version.source_evidence as { guide_format: string }).guide_format}{(version.source_evidence as { format_source?: string }).format_source === "user" ? " · chosen" : " · suggested"}</span>
            ) : null}
          </div>
          <h3 style={{ marginTop: 8 }}>{version.steps.length ? "Procedure draft" : "Procedure"}</h3>
          <label htmlFor="rv-sum">Summary</label><input id="rv-sum" value={version.summary} disabled={version.status === "approved"} onChange={(e) => setVersion({ ...version, summary: e.target.value })} />
          <label htmlFor="rv-pre">Prerequisites</label><textarea id="rv-pre" rows={2} value={version.prerequisites} disabled={version.status === "approved"} onChange={(e) => setVersion({ ...version, prerequisites: e.target.value })} />
          {Array.isArray((version.source_evidence as { uncertainties?: string[] }).uncertainties) && <div className="notice warn"><strong>Uncertainties to resolve:</strong> {((version.source_evidence as { uncertainties?: string[] }).uncertainties || []).join(" ")}</div>}
          {Array.isArray((version.source_evidence as { missing_information?: string[] }).missing_information) && ((version.source_evidence as { missing_information?: string[] }).missing_information || []).length > 0 && <div className="notice warn"><strong>Missing information:</strong> {((version.source_evidence as { missing_information?: string[] }).missing_information || []).join(" ")}</div>}
          {Array.isArray((version.source_evidence as { safety_notes?: string[] }).safety_notes) && ((version.source_evidence as { safety_notes?: string[] }).safety_notes || []).length > 0 && <div className="notice info"><strong>Safety notes (from capture):</strong> {((version.source_evidence as { safety_notes?: string[] }).safety_notes || []).join(" ")}</div>}
          <ReviewEvidence versionId={version.id} />
          <ProposalBanner version={version} />
          {(() => {
            const sync = (version.source_evidence as { sync?: { action?: string; conflicting_steps?: number[]; changed_steps?: number[] } }).sync;
            if (!sync || (sync.action !== "conflict" && !(sync.conflicting_steps || []).length)) return null;
            const rows = sync.conflicting_steps || [];
            return (
              <div className="notice warn" role="alert">
                <strong>Regenerated content conflicts with expert edits.</strong>{" "}
                {rows.length ? <>Steps {rows.join(", ")} were edited here and changed in the tutorial since. Your text was kept. </> : null}
                Use “Use latest AI text” on a step to accept the regenerated wording, or keep yours.
                {sync.action === "resolved" ? " All conflicts resolved." : ""}
              </div>
            );
          })()}
          {version.steps.map((s, i) => (
            <div key={s.id} className="card">
              <strong>Step {s.step_order}: {s.title}</strong>
              <label htmlFor={`st-${s.id}`}>Instruction</label>
              <textarea id={`st-${s.id}`} rows={2} value={s.instruction} disabled={version.status === "approved"} onChange={(e) => { const steps = [...version.steps]; steps[i] = { ...s, instruction: e.target.value }; setVersion({ ...version, steps }); }} />
              <p className="muted">Expected: {s.expected_result || "—"} · Evidence refs: {s.evidence_refs.length ? s.evidence_refs.join(", ") : "none linked"} {s.verification_notes ? `· Check: ${s.verification_notes}` : ""}</p>
              {(s.transcript_segments || []).length > 0 && (
                <details>
                  <summary className="small-text"><strong>Supporting narration ({(s.transcript_segments || []).length})</strong> — transcript behind this step</summary>
                  <ul className="small-text" style={{ paddingLeft: 18 }}>
                    {(s.transcript_segments || []).slice(0, 4).map((t) => (
                      <li key={t.index}><span className="muted num">{Math.floor(t.start / 60)}:{String(Math.floor(t.start % 60)).padStart(2, "0")}</span> — {t.text}</li>
                    ))}
                    {(s.transcript_segments || []).length > 4 && <li className="muted">…and {(s.transcript_segments || []).length - 4} more</li>}
                  </ul>
                </details>
              )}
              {((version.source_evidence as { sync?: { conflicting_steps?: number[] } }).sync?.conflicting_steps || []).includes(s.step_order) && (version.status === "draft" || version.status === "rejected") && (
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="tag warn">Edited here and changed upstream — your text kept</span>
                  <button className="btn small" disabled={busy} onClick={async () => {
                    setBusy(true);
                    try {
                      const v = await api.post<Version>(`/api/procedure-versions/${version.id}/resolve-conflict`, { step_orders: [s.step_order] });
                      setVersion(v);
                      const left = ((v.source_evidence as { sync?: { conflicting_steps?: number[] } }).sync?.conflicting_steps || []).length;
                      notify(left ? "Step updated to the regenerated wording." : "All conflicts resolved — draft matches the latest canonical content.", "ok");
                    } catch (e) { notify(e instanceof Error ? e.message : "Could not apply canonical text", "error"); }
                    finally { setBusy(false); }
                  }}>Use latest AI text</button>
                </div>
              )}
            </div>
          ))}
          {version.status === "pending_review" && (<>
            <label htmlFor="rv-comment">Review comment (required to reject)</label>
            <input id="rv-comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What did you verify, or what must change?" />
          </>)}
          <div className="row">
            {(version.status === "draft" || version.status === "rejected") && <><button className="btn secondary" disabled={busy} onClick={saveEdits}>Save edits</button><button className="btn" disabled={busy} onClick={() => act("submit-review", version.status === "rejected" ? "Resubmitted for review." : "Submitted for review.")}>{version.status === "rejected" ? "Submit again for review" : "Submit for review"}</button></>}
            {version.status === "pending_review" && (canReview
              ? <><button className="btn" disabled={busy || confirmApprove} onClick={() => setConfirmApprove(true)}>Approve</button><button className="btn danger" disabled={busy} onClick={() => act("reject", "Rejected and returned with an audit record.")}>Reject</button></>
              : <span className="tag warn">Reviewer role required to approve or reject</span>)}
            {confirmApprove && version.status === "pending_review" && canReview && (
              <div className="notice warn" role="alertdialog" aria-label="Confirm approval" style={{ marginTop: 10 }}>
                <strong>Approve this version?</strong> It becomes immutable and available for jobs. This cannot be undone — edits afterwards require a new revision.
                <div className="row" style={{ marginTop: 10 }}>
                  <button className="btn" disabled={busy} onClick={() => void act("approve", "Approved. This version is now immutable and available to technicians.")}>Yes, approve</button>
                  <button className="btn secondary" disabled={busy} onClick={() => setConfirmApprove(false)}>Keep reviewing</button>
                </div>
              </div>
            )}
            {version.status === "approved" && <button className="btn secondary" disabled={busy} onClick={async () => { setBusy(true); try { const v = await api.post<Version>(`/api/procedure-versions/${version.id}/new-revision`, {}); setVersion(v); notify("New draft revision created. The approved version is unchanged."); } catch (e) { notify(e instanceof Error ? e.message : "Could not create a revision", "error"); } finally { setBusy(false); } }}>Propose new revision</button>}
          </div>
          {version.reviewed_by && <p className="muted">Reviewed by {version.reviewed_by}: {version.review_comment || ""}</p>}
        </div>
      )}
    </div>
  );
}

interface EvidenceItem {
  id: string; evidence_type: string; description: string; source_reference: string;
  text_content?: string | null; image_url: string | null;
  segmentation: { id: string; geometry: SegGeometry; simulated: boolean; status: string; prompt: string; model?: string } | null;
}

interface ProcEventRow {
  id: string; correlation_id: string; entity_type: string; entity_id: string; actor: string; stage: string;
  operation: string; provider: string; model: string; status: string; duration_ms?: number | null;
  summary: Record<string, unknown>; created_at: string;
}

function StepEvidence({ versionId, step }: { versionId: string; step: Step }) {
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    api.get<{ evidence: EvidenceItem[] }>(`/api/procedure-versions/${versionId}/evidence`)
      .then((r) => { if (alive) setItems(r.evidence || []); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [versionId]);
  const refs = new Set([...(step.evidence_refs || []), ...(step.visual_refs || [])]);
  const mine = items.filter((e) => refs.has(e.id) && e.image_url);
  if (failed) return <p className="muted small-text">Step reference photo is unavailable offline — the approved instruction above remains fully usable.</p>;
  if (!mine.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      {mine.map((e) => {
        const geo = e.segmentation?.geometry;
        const objs = geo?.objects?.length ? geo.objects : geo?.bbox_norm?.length === 4 ? [{ object_id: 0, bbox_norm: geo.bbox_norm, mask: geo.mask }] : [];
        return (
          <figure key={e.id} style={{ margin: 0 }}>
            <div className="overlay-wrap" role="img" aria-label={`Step reference photo${geo ? ` with highlight on ${geo.label}` : ""}`}>
              <img src={e.image_url || ""} alt="" />
              {objs.map((o) => {
                const [x1, y1, x2, y2] = o.bbox_norm;
                return (
                  <div key={o.object_id} className="bbox" style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}>
                    <span>{geo?.label}</span>
                    {o.mask?.svg_path && (
                      <svg className="mask-svg" viewBox={`0 0 ${o.mask.width} ${o.mask.height}`} preserveAspectRatio="none" aria-hidden="true"><path d={o.mask.svg_path} /></svg>
                    )}
                  </div>
                );
              })}
            </div>
            <figcaption className="muted small-text">
              Step reference{e.segmentation
                ? <> · <span className="tag ai">{e.segmentation.simulated ? "SAM highlight · simulated" : "SAM 3.1 highlight"} · {e.segmentation.status}</span></>
                : " · Highlighting unavailable for this photo — showing the original image."}
              {e.description ? <> · {e.description}</> : null}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}

interface JobPhoto {
  id: string; description: string; step_id: string | null; captured_at: string | null; image_url: string | null;
}

function JobView({ job, version, queueEvent, setJob, notify, reload, refreshPending, go, pending, online, offlineReady }: {
  job: LocalJob | null; version: Version | null;
  queueEvent: (e: Omit<JobEventRec, "sync_status">) => Promise<void>; setJob: (j: LocalJob | null) => Promise<void>;
  notify: (s: string, kind?: "ok" | "error" | "info") => void; reload: () => void; refreshPending: () => void; go: (v: View) => void;
  pending: number; online: boolean; offlineReady: boolean;
}) {
  const [issueType, setIssueType] = useState(ISSUE_TYPES[0]);
  const [note, setNote] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [fieldNote, setFieldNote] = useState("");
  const [askQ, setAskQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [photos, setPhotos] = useState<JobPhoto[]>([]);
  const [pendingPhotos, setPendingPhotos] = useState(0);
  const [uploading, setUploading] = useState(false);
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const steps = version ? [...version.steps].sort((a, b) => a.step_order - b.step_order) : [];
  // Canonical progression: only done/skipped advance the frontier.
  // Blocked halts the job at the blocking step — it is never skipped over.
  const isDoneOrSkipped = (st: string | undefined) => st === "done" || st === "skipped";
  const frontierIdx = (() => {
    if (!job) return 0;
    const i = steps.findIndex((s) => !isDoneOrSkipped(job.stepStates[s.id]));
    return i === -1 ? steps.length : i;
  })();
  const allDone = job !== null && steps.length > 0 && frontierIdx >= steps.length;
  const frontierStep = job && steps.length && frontierIdx < steps.length ? steps[frontierIdx] : undefined;
  const blockedAtFrontier = !!frontierStep && job?.stepStates[frontierStep.id] === "blocked";
  const isLastPending = !!job && steps.length > 0 && frontierIdx === steps.length - 1 && !blockedAtFrontier;
  const doneCount = job ? steps.filter((s) => job.stepStates[s.id] === "done").length : 0;
  // Viewed step (Previous navigation) vs frontier (where work happens).
  // Reviewing history never mutates it; actions always target the frontier.
  const [viewIdx, setViewIdx] = useState<number | null>(null);
  useEffect(() => { setViewIdx(null); setMediaError(""); setFinishBlocked(null); }, [job?.id]);
  const effectiveIdx = viewIdx ?? (allDone ? steps.length - 1 : frontierIdx);
  const step = job && steps.length ? steps[Math.min(Math.max(effectiveIdx, 0), steps.length - 1)] : undefined;
  const viewingPast = viewIdx !== null && viewIdx < frontierIdx && !allDone;
  const [mediaError, setMediaError] = useState("");
  const [jobPending, setJobPending] = useState(0);
  const [askBusy, setAskBusy] = useState(false);
  // Steps the server still lacks after a sync-first finish attempt.
  // Shown with a jump-to-step action instead of a dead-end error.
  const [finishBlocked, setFinishBlocked] = useState<number[] | null>(null);
  // actingRef is the guard (stale closures made the state check pass twice
  // on rapid clicks); actingUi only drives disabled buttons.
  const actingRef = useRef(false);
  const [actingUi, setActingUi] = useState(false);
  function setActing(v: boolean) { actingRef.current = v; setActingUi(v); }
  useEffect(() => {
    let alive = true;
    if (job) {
      pendingForJob(job.id).then((p) => { if (alive) setJobPending(p.total); }).catch(() => undefined);
    } else setJobPending(0);
    return () => { alive = false; };
  }, [job?.id, pending, job?.finished]);
  // Server reconciliation on mount/resume: adopt server-terminal states we
  // lack locally, and finalize locally if the server already finished.
  // Local pending work always survives; server state never deletes it.
  // Returns the server state (or null offline) so finish can re-check it.
  async function pullServerState(): Promise<{
    steps: { step_id: string; state: string }[]; finished: boolean; outcome: string | null;
    is_blocked?: boolean; can_progress?: boolean; can_finalize?: boolean;
  } | null> {
    if (!job || !online || job.finished) return null;
    try {
      const st = await api.get<{
        steps: { step_id: string; state: string }[]; finished: boolean; outcome: string | null;
        is_blocked?: boolean; can_progress?: boolean; can_finalize?: boolean;
      }>(`/api/jobs/${job.id}/state`);
      let changed = false;
      const merged = { ...job.stepStates };
      for (const p of st.steps) {
        if ((p.state === "done" || p.state === "skipped" || p.state === "blocked") && !merged[p.step_id]) {
          merged[p.step_id] = p.state as "done" | "skipped" | "blocked";
          changed = true;
        }
      }
      if (st.finished) {
        await setJob({ ...job, stepStates: merged, finished: true, finish_outcome: st.outcome || "completed" });
        notify("The server shows this job finished — marked complete locally.", "info");
        go("history");
        return st;
      }
      if (changed) {
        await setJob({ ...job, stepStates: merged });
        notify("Recovered progress confirmed by the server.", "info");
      }
      return st;
    } catch { return null; /* offline or gone: local state stands */ }
  }
  useEffect(() => {
    let alive = true;
    void (async () => { if (alive) await pullServerState(); })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id]);

  async function loadPhotos() {
    if (!job || !step) return;
    try {
      const r = await api.get<{ evidence: JobPhoto[] }>(`/api/jobs/${job.id}/evidence`);
      setPhotos((r.evidence || []).filter((p) => !p.step_id || p.step_id === step.id));
    } catch { /* offline: pending list shown instead */ }
    try {
      const pend = await loadPending<PendingPhoto>("pending-photos");
      setPendingPhotos(pend.filter((p) => p.job_id === job.id && (!p.step_id || p.step_id === step.id)).length);
    } catch { /* storage unavailable: counts stay */ }
  }
  useEffect(() => { void loadPhotos(); }, [job?.id, step?.id]);

  if (!job || !version) return <div className="card"><div className="empty"><h3>No active job</h3><p>Start one from an approved procedure. Downloaded procedures open here even in airplane mode.</p><button className="btn" onClick={() => go("library")}>Open procedure library</button></div></div>;
  if (steps.length === 0 || !step) return <div className="card"><div className="empty"><h3>No steps in this version</h3><p>This procedure version has no steps, so a guided job cannot run. Ask a reviewer to create a revision with steps.</p><button className="btn" onClick={() => go("library")}>Open procedure library</button></div></div>;

  /** Record a terminal state for the FRONTIER step and advance the view.
   *  Viewing history can never overwrite it: same-state repeats no-op. */
  async function mark(state: "done" | "skipped" | "blocked") {
    if (!job || actingRef.current || allDone || blockedAtFrontier) return;
    const target = steps[frontierIdx];
    if (!target) return;
    if (job.stepStates[target.id] === state) { notify("Already recorded — no duplicate event created."); return; }
    setActing(true);
    try {
      const eventId = `evt:${job.id}:${target.id}:${state === "done" ? "complete" : state}`;
      const existing = await idb.get<JobEventRec>("events", eventId);
      if (!existing) {
        await queueEvent({ event_id: eventId, session_id: job.id, step_id: target.id, event_type: state === "done" ? "step_completed" : state === "skipped" ? "step_skipped" : "step_blocked", payload: { step_order: target.step_order }, occurred_at: new Date().toISOString() });
      }
      const next = { ...job, stepStates: { ...job.stepStates, [target.id]: state }, current: Math.min(frontierIdx + 1, steps.length) };
      await setJob(next); setViewIdx(null); setFinishBlocked(null);
      notify(state === "done" ? "Step completed and saved on this device." : `Step marked ${state} and saved on this device.`);
    } finally { setActing(false); }
  }
  async function recordIssue() {
    // Incidents always target the frontier (current work), never a
    // history view the technician navigated back to.
    const target = frontierStep;
    if (!job || !target || actingRef.current) return;
    if (!note.trim()) { notify("Describe the anomaly first so the reviewer knows what to fix.", "error"); return; }
    setActing(true);
    try {
      await queueEvent({ event_id: uuid(), session_id: job.id, step_id: target.id, event_type: "issue_recorded", payload: { issue_type: issueType, note }, occurred_at: new Date().toISOString() });
      let halted = job.stepStates[target.id] === "blocked";
      if (!halted) {
        await queueEvent({ event_id: `evt:${job.id}:${target.id}:blocked`, session_id: job.id, step_id: target.id, event_type: "step_blocked", payload: { step_order: target.step_order }, occurred_at: new Date().toISOString() });
        halted = true;
      }
      await setJob({ ...job, stepStates: { ...job.stepStates, [target.id]: "blocked" } });
      setNote(""); setDrawerOpen(false); setViewIdx(null);
      notify(`Anomaly logged on step ${target.step_order} — job halted. Resolve it to resume. It syncs when connectivity returns.`);
    } catch {
      notify("Could not save the incident on this device — nothing was recorded. Retry.", "error");
    } finally { setActing(false); }
  }
  /** Resume a halted step: history is preserved as events; the step simply
   *  becomes workable again (it returns to the frontier). */
  async function resumeStep() {
    const target = frontierStep;
    if (!job || !target || actingRef.current) return;
    if (job.stepStates[target.id] !== "blocked") { notify("Only a blocked step can be resumed."); return; }
    setActing(true);
    try {
      await queueEvent({ event_id: uuid(), session_id: job.id, step_id: target.id, event_type: "step_resumed", payload: { step_order: target.step_order }, occurred_at: new Date().toISOString() });
      const next = { ...job.stepStates };
      delete next[target.id];
      await setJob({ ...job, stepStates: next });
      setViewIdx(null); setFinishBlocked(null);
      notify("Step resumed — it is workable again. The halt stays in the audit history.", "ok");
    } catch {
      notify("Could not resume on this device — nothing changed. Retry.", "error");
    } finally { setActing(false); }
  }
  async function saveFieldNote() {
    // Field notes attach to the frontier step (current work).
    const target = frontierStep || step;
    if (!job || !target || actingRef.current) return;
    if (!fieldNote.trim()) { notify("Write the note first.", "error"); return; }
    setActing(true);
    try {
      await queueEvent({ event_id: uuid(), session_id: job.id, step_id: target.id, event_type: "field_note", payload: { note: fieldNote, step_order: target.step_order }, occurred_at: new Date().toISOString() });
      setFieldNote(""); setNoteOpen(false); notify("Field note saved on this device. It syncs with your queued events.");
    } finally { setActing(false); }
  }
  async function attachPhoto(f: File | undefined) {
    // Evidence attaches to the frontier step (current work).
    const target = frontierStep || step;
    if (!f || !job || !target || uploading || actingRef.current) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(f.type)) { notify("Only JPEG, PNG or WebP photos are supported.", "error"); return; }
    if (f.size > 8 * 1024 * 1024) { notify("Photo is larger than 8 MB — pick a smaller file.", "error"); return; }
    setUploading(true);
    const desc = `Step ${target.step_order} field photo`;
    try {
      const fd = new FormData(); fd.append("file", f); fd.append("description", desc); fd.append("step_id", target.id);
      const up = await api.upload<{ id: string }>(`/api/jobs/${job.id}/evidence`, fd);
      await queueEvent({ event_id: uuid(), session_id: job.id, step_id: target.id, event_type: "evidence_attached", payload: { evidence_id: up.id, step_order: target.step_order, description: desc }, occurred_at: new Date().toISOString() });
      notify("Photo attached to this step and queued for server confirmation."); void loadPhotos(); void reload();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (!online || /failed to fetch|network|load failed|upload failed/i.test(msg)) {
        const key = uuid();
        await idb.put("media", key, f);
        const pend = await loadPending<PendingPhoto>("pending-photos");
        pend.push({ key, job_id: job.id, step_id: target.id, description: desc });
        await savePending("pending-photos", pend);
        setPendingPhotos((n) => n + 1);
        notify("Photo saved on this device — it uploads automatically on the next sync.", "info");
      } else notify(msg || "Photo upload failed.", "error");
    } finally { setUploading(false); }
  }
  /** Single coherent finalization: the last-step action completes the
   *  final step AND finalizes the job in one interaction (online) or queues
   *  both in order (offline). Blocked jobs cannot finalize until resolved.
   *  Retries reuse stable event ids, so double-clicks never duplicate. */
  async function finishFinal() {
    if (!job || actingRef.current || steps.length === 0) return;
    if (blockedAtFrontier) { notify("Job blocked — resolve the blocked step before finishing.", "error"); return; }
    if (!allDone && !isLastPending) return;
    setActing(true);
    setFinishBlocked(null);
    try {
      const finalStep = allDone ? steps[steps.length - 1] : steps[frontierIdx];
      // One-click final step: record its completion locally first (unless
      // already recorded) so the UI and the server finalize atomically.
      const finalEventId = `evt:${job.id}:${finalStep.id}:complete`;
      let workingJob = job;
      if (workingJob.stepStates[finalStep.id] !== "done" && workingJob.stepStates[finalStep.id] !== "skipped") {
        const existing = await idb.get<JobEventRec>("events", finalEventId);
        if (!existing) {
          await queueEvent({ event_id: finalEventId, session_id: job.id, step_id: finalStep.id,
                             event_type: "step_completed", payload: { step_order: finalStep.step_order, final: true },
                             occurred_at: new Date().toISOString() });
        }
        workingJob = { ...workingJob, stepStates: { ...workingJob.stepStates, [finalStep.id]: "done" } };
        await setJob(workingJob);
      }
      const outcomeGuess = steps.every((s) => (workingJob.stepStates[s.id] || (s.id === finalStep.id ? "done" : undefined)) === "done")
        ? "completed" : "finished-with-exceptions";
      const localOutcome = doneCount === steps.length || outcomeGuess === "completed" ? "completed" : "finished-with-exceptions";
      // The server can only finalize what it has: sync recorded steps
      // first so an online finish never fails on work this device already
      // did. Without this, tapping fast then finishing hits a 422 for
      // steps the server has not seen yet.
      const pend = await pendingForJob(job.id).catch(() => ({ total: 0 }));
      if (pend.total > 0) {
        notify("Syncing your recorded steps before finishing…", "info");
        try {
          await runSync();
          await refreshPending();
        } catch {
          notify("Sync failed — finishing on this device; the server confirms it on the next sync.", "info");
        }
        const st = await pullServerState();
        const missing = st ? steps.filter((s) => {
          const cur = st.steps.find((x) => x.step_id === s.id);
          // Blocked is not terminal: it must be resolved, not skipped over.
          return !cur || (cur.state !== "done" && cur.state !== "skipped");
        }).map((s) => s.step_order) : [];
        if (missing.length > 0) {
          // Sync ran but the server still lacks outcomes (e.g. a step the
          // server rejected, or validation failures in the queue). Do not
          // finalize blindly — point at the exact steps instead.
          setFinishBlocked(missing);
          notify(`The server still has no outcome for step${missing.length === 1 ? "" : "s"} ${missing.join(", ")}. Complete, skip, or resolve them first — or discard the failing queue item in Activity and retry.`, "error");
          return;
        }
        if (st?.is_blocked) {
          notify("Job blocked on the server — resolve the blocked step before finishing.", "error");
          return;
        }
      }
      const finishId = `evt:${job.id}:finish`;
      const existingFinish = await idb.get<JobEventRec>("events", finishId);
      if (!existingFinish) {
        await queueEvent({ event_id: finishId, session_id: job.id, step_id: null, event_type: "job_finished", payload: { outcome: localOutcome }, occurred_at: new Date().toISOString() });
      }
      let serverOutcome: string | null = null;
      try {
        const r = await api.post<{ ok: boolean; outcome?: string; already_finished?: boolean }>(
          `/api/jobs/${job.id}/finalize`,
          { step_id: finalStep.id, event_id: finalEventId, reason: "" });
        serverOutcome = r.outcome || null;
      } catch (e) {
        if (!isNetworkError(e)) { notify(e instanceof Error ? e.message : "Finalization rejected.", "error"); return; }
        // Offline: the queued job_finished event plus the pending finish
        // entry deliver finalization in order on the next sync.
      }
      const outcome = serverOutcome || localOutcome;
      if (serverOutcome) {
        // Server confirmed finalization: the queued finish event and any
        // pending finish for this job are already satisfied — mark them
        // confirmed so the next sync does not re-send or fail them.
        try {
          const fin = await idb.get<JobEventRec>("events", finishId);
          if (fin) await idb.put("events", finishId, { ...fin, sync_status: "synced" });
          const fins = await loadPending<PendingFinish>("pending-finishes");
          await savePending("pending-finishes", fins.filter((f) => f.job_id !== job.id));
          await refreshPending();
        } catch { /* bookkeeping only */ }
      }
      await setJob({ ...workingJob, finished: true, finish_outcome: outcome });
      notify(outcome === "completed"
        ? "Job completed — final step recorded and job closed."
        : "Job finished with exceptions — skipped steps are listed in the summary.", "ok");
      go("history");
    } finally { setActing(false); }
  }
  async function ask() {
    if (!version || askBusy) return;
    if (!askQ.trim()) { setAnswer("Type a question first."); return; }
    setAskBusy(true);
    try { const r = await api.post<{ answer: string }>("/api/ask", { question: askQ, procedure_version_id: version.id }); setAnswer(r.answer); }
    catch { setAnswer("AI assistance is unavailable offline. The approved steps and cached manual text above remain fully usable."); }
    finally { setAskBusy(false); }
  }
  const safety = ((version.source_evidence as { safety_notes?: string[] }).safety_notes || []).filter(Boolean);
  const hasRefs = (step.evidence_refs?.length || 0) + (step.visual_refs?.length || 0) > 0;
  const skippedCount = steps.filter((s) => job.stepStates[s.id] === "skipped").length;
  const blockedCount = steps.filter((s) => job.stepStates[s.id] === "blocked").length;
  // Per-job sync state: local completion vs server-confirmed completion.
  const jobSyncLabel = !online ? "Offline — saved on this device"
    : jobPending > 0 ? `${jobPending} item${jobPending === 1 ? "" : "s"} waiting to sync`
    : "Synced with server";
  // Tracker reflects RECORDED states only — never the view index.
  const segClass = (s: Step) => {
    const st = job.stepStates[s.id];
    if (st === "done") return "on on-done";
    if (st === "skipped") return "on on-skip";
    if (st === "blocked") return "on on-block";
    return "";
  };
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <button className="btn small secondary" onClick={() => go("home")} aria-label="Exit job and return home. Progress stays saved on this device."><Icon name="back" size={17} /> Exit</button>
        <h2 style={{ margin: 0, fontSize: "1.05rem" }}>Procedure Execution</h2>
        <span className={`sync-pill${online ? "" : " offline"}`} role="status"><span className="sync-dot" aria-hidden="true" />{jobSyncLabel}</span>
      </div>
      <div className="job-layout"><div>
      <section className="card" aria-live="polite">
        <div className="proc-badges">
          <span className="badge ok"><Icon name="verified" size={13} /> Rev {version.version_number} (Approved)</span>
          {offlineReady && <span className="badge ok"><Icon name="cloudDone" size={13} /> Offline cache ready</span>}
          {job.stepStates[step.id] === "done" && <span className="badge ok">Step {step.step_order}: completed</span>}
          {job.stepStates[step.id] === "skipped" && <span className="badge warn">Step {step.step_order}: skipped</span>}
          {job.stepStates[step.id] === "blocked" && <span className="badge crit">Step {step.step_order}: blocked</span>}
          {viewingPast && <span className="badge neutral">Reviewing history — actions target step {frontierStep ? frontierStep.step_order : steps.length}</span>}
        </div>
        <h2 style={{ marginTop: 8 }}>{job.title}</h2>
        <p className="muted small-text" style={{ marginTop: -6 }}>Asset job · step {step.step_order} of {steps.length}</p>
        <div className="seg-progress" style={{ marginTop: 8 }} role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={steps.length} aria-label={`${doneCount} of ${steps.length} steps complete`}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>Step {step.step_order} of {steps.length}</strong>
            <span className="muted small-text">{step.title}</span>
          </div>
          <div className="seg-progress-track" aria-hidden="true">
            {steps.map((s) => <span key={s.id} className={segClass(s)} />)}
          </div>
          <p className="muted small-text" style={{ margin: "6px 0 0" }} aria-hidden="true"><span className="seg-legend on-done" /> done · <span className="seg-legend on-skip" /> skipped · <span className="seg-legend on-block" /> blocked</p>
        </div>
      </section>
      <section className="card">
        <div className="row">
          <span className="tool-pill num" style={{ minWidth: 44, justifyContent: "center" }}>{String(step.step_order).padStart(2, "0")}</span>
          <span className="eyebrow">Primary action</span>
        </div>
        <p className="step-hero" style={{ marginTop: 8 }}>{step.instruction}</p>
      </section>
      <section className="result-card">
        <span className="result-check"><Icon name="check" size={15} /></span>
        <div><span className="panel-title" style={{ color: "var(--primary-container)" }}>Expected physical result</span>
        <p style={{ margin: "4px 0 0" }}>{step.expected_result || "Confirm visually before continuing."}</p></div>
      </section>
      </div><div>
      <section className="card" style={{ marginTop: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}><Icon name="camera" size={18} /> Component reference</h3>
        </div>
        {hasRefs ? <StepEvidence versionId={version.id} step={step} />
          : <p className="muted small-text">No reference photo linked to this step — follow the approved instruction above.</p>}
        {(photos.length > 0 || pendingPhotos > 0) && (
          <div style={{ marginTop: 10 }}>
            <span className="eyebrow">Field photos on this step</span>
            <div className="row" style={{ marginTop: 6 }}>
              {photos.map((p) => p.image_url && (
                <figure key={p.id} style={{ margin: 0, maxWidth: 160 }}>
                  <img src={p.image_url} alt={p.description || "Field photo"} style={{ width: "100%", borderRadius: 8, border: "1px solid var(--line)" }} />
                  <figcaption className="muted small-text">{p.description}{p.captured_at ? ` · ${new Date(p.captured_at).toLocaleTimeString()}` : ""}</figcaption>
                </figure>
              ))}
              {pendingPhotos > 0 && <span className="badge warn">{pendingPhotos} photo{pendingPhotos === 1 ? "" : "s"} waiting to upload</span>}
            </div>
          </div>
        )}
      </section>
      {(step.required_tools.length > 0 || safety.length > 0 || version.prerequisites) && (
        <section style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 12 }}>
          {safety.length > 0 && (
            <div className="safety-banner" role="note"><Icon name="warning" size={20} /><div><strong>Mandatory safety step</strong><p style={{ margin: "4px 0 0" }}>{safety.join(" ")}</p></div></div>
          )}
          <div className="card" style={{ margin: 0 }}>
            {version.prerequisites && <p className="small-text"><strong>Prerequisites:</strong> {version.prerequisites}</p>}
            <span className="eyebrow">Required field tooling</span>
            <div className="tool-pills" style={{ marginTop: 6 }}>
              {step.required_tools.length > 0 ? step.required_tools.map((t) => <span key={t} className="tool-pill">{t}</span>) : <span className="muted small-text">No special tooling for this step.</span>}
            </div>
          </div>
        </section>
      )}
      </div></div>
      <section className="card" style={{ marginTop: 12 }}>
        <h3>Job summary so far</h3>
        <p>{doneCount} completed · {blockedCount} blocked · {skippedCount} skipped of {steps.length} steps. {jobPending > 0 ? `${jobPending} item${jobPending === 1 ? "" : "s"} saved on this device, waiting for server confirmation.` : "Everything is confirmed by the server."}</p>
        <div className="row">
          {!allDone && !blockedAtFrontier && !viewingPast && <button className="btn secondary" onClick={() => mark("skipped")} disabled={actingUi}>Skip step {frontierStep ? frontierStep.step_order : ""}</button>}
          {viewingPast && frontierStep && <button className="btn secondary" onClick={() => setViewIdx(null)}>Return to step {frontierStep.step_order}</button>}
        </div>
        <p className="muted small-text" style={{ marginTop: 8 }}>If a step is blocked on anything hazardous, stop work and follow your site procedure — this app never instructs you to bypass safety steps.</p>
        {finishBlocked && finishBlocked.length > 0 && (
          <div className="notice warn" role="alert" style={{ marginTop: 8 }}>
            <strong>The server still has no outcome for step{finishBlocked.length === 1 ? "" : "s"} {finishBlocked.join(", ")}.</strong>{" "}
            Your updates may still be waiting to sync, or a queued step was rejected — check Activity → Sync diagnostics.
            <span className="row" style={{ marginTop: 8 }}>
              <button className="btn small" onClick={() => {
                const target = steps.findIndex((s) => s.step_order === finishBlocked[0]);
                if (target >= 0) { setViewIdx(target); setFinishBlocked(null); }
              }}>Go to step {finishBlocked[0]}</button>
              <button className="btn small secondary" onClick={() => setFinishBlocked(null)}>Dismiss</button>
            </span>
          </div>
        )}
      </section>
      <div className="action-dock">
        <div className="aux-row">
          <button className="btn secondary" disabled={effectiveIdx <= 0 || actingUi} onClick={() => setViewIdx(Math.max(effectiveIdx - 1, 0))}><Icon name="back" size={18} /> Previous</button>
          <button className="btn secondary" disabled={uploading} onClick={() => photoInputRef.current?.click()}><Icon name="camera" size={18} /> {uploading ? "Uploading…" : "Attach Photo"}</button>
          <button className="btn secondary" onClick={() => setNoteOpen(true)}><Icon name="note" size={18} /> Field Note</button>
        </div>
        <div className="action-dock-row">
          {blockedAtFrontier && !viewingPast ? (
            <>
              <span className="badge crit" role="status"><Icon name="warning" size={15} /> Job blocked — requires attention</span>
              <button className="btn" onClick={resumeStep} disabled={actingUi}><Icon name="forward" size={20} /> Resolve &amp; resume step {frontierStep ? frontierStep.step_order : ""}</button>
            </>
          ) : viewingPast ? (
            <>
              <button className="btn secondary" onClick={() => setDrawerOpen(true)} disabled={actingUi || blockedAtFrontier}><Icon name="warning" size={20} /> Report Blocked</button>
              <span className="muted small-text" role="status">Reviewing a recorded step — it cannot be changed from here.{frontierStep ? ` Current work is at step ${frontierStep.step_order}.` : ""}</span>
            </>
          ) : (allDone || isLastPending) ? (
            <button className="btn" onClick={finishFinal} disabled={actingUi}><Icon name="check" size={20} /> {actingUi ? "Finishing…" : isLastPending ? "Finish job ✓" : "Finish job ✓"}</button>
          ) : (
            <>
              <button className="btn secondary danger-ghost" style={{ background: "var(--danger-bg)", borderColor: "var(--danger-bg)", color: "var(--danger)" }} onClick={() => setDrawerOpen(true)} disabled={actingUi} aria-label="Report this step as blocked"><Icon name="warning" size={20} /></button>
              <button className="btn" onClick={() => mark("done")} disabled={actingUi}><Icon name="check" size={20} /> {actingUi ? "Saving…" : `Next step →`}</button>
            </>
          )}
        </div>
        {!allDone && !viewingPast && frontierStep && !blockedAtFrontier && (
          <p className="muted small-text" style={{ margin: "8px 0 0" }}>{isLastPending ? `Complete this final step and close the job.` : `Primary action records step ${frontierStep.step_order} of ${steps.length}.`}</p>
        )}
        {blockedAtFrontier && !viewingPast && (
          <p className="muted small-text" style={{ margin: "8px 0 0" }} role="status">Halted at step {frontierStep ? frontierStep.step_order : ""} — normal progression is paused until the incident is resolved.</p>
        )}
      </div>
      <input ref={photoInputRef} className="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" aria-label="Attach a field photo to this step" onChange={(e) => { void attachPhoto(e.target.files?.[0] || undefined); e.target.value = ""; }} />
      <div className="card">
        <h3>Ask about this procedure</h3>
        <label htmlFor="ask-q">Question</label><input id="ask-q" value={askQ} onChange={(e) => setAskQ(e.target.value)} placeholder="e.g. knob" />
        <button className="btn secondary" style={{ marginTop: 10 }} onClick={ask} disabled={askBusy}>{askBusy ? "Searching…" : "Search approved steps & manuals"}</button>
        {answer && <div className="notice ok" role="status">{answer}</div>}
      </div>
      {drawerOpen && (
        <div className="scrim" onClick={(e) => { if (e.target === e.currentTarget) setDrawerOpen(false); }}>
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Report field anomaly">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3><Icon name="warning" size={19} /> Report field anomaly</h3>
              <button className="btn small secondary icon-only" aria-label="Close anomaly report" onClick={() => setDrawerOpen(false)}><Icon name="close" size={18} /></button>
            </div>
            <p className="muted">Select a blocking category for step {frontierStep ? frontierStep.step_order : step.step_order}:</p>
            <div className="issue-tags" role="group" aria-label="Anomaly category">
              {ISSUE_TYPES.map((t) => (
                <button key={t} className="issue-tag" aria-pressed={issueType === t} onClick={() => setIssueType(t)}>{t}</button>
              ))}
            </div>
            <label htmlFor="drawer-note">Technician notes (required)</label>
            <textarea id="drawer-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Briefly describe physical condition or binding resistance..." />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn secondary" style={{ flex: 1 }} onClick={() => setDrawerOpen(false)}>Cancel</button>
              <button className="btn danger" style={{ flex: 1, background: "var(--danger)", borderColor: "var(--danger)", color: "#fff" }} onClick={recordIssue} disabled={actingUi}>Log incident &amp; halt</button>
            </div>
          </div>
        </div>
      )}
      {noteOpen && (
        <div className="scrim" onClick={(e) => { if (e.target === e.currentTarget) setNoteOpen(false); }}>
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Add field note">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3><Icon name="note" size={19} /> Field note · step {step.step_order}</h3>
              <button className="btn small secondary icon-only" aria-label="Close field note" onClick={() => setNoteOpen(false)}><Icon name="close" size={18} /></button>
            </div>
            <label htmlFor="field-note-text">Note (saved on this device, syncs with events)</label>
            <textarea id="field-note-text" rows={3} value={fieldNote} onChange={(e) => setFieldNote(e.target.value)} placeholder="e.g. Left clip needed extra force; right clip seated first try." />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn secondary" style={{ flex: 1 }} onClick={() => setNoteOpen(false)}>Cancel</button>
              <button className="btn" style={{ flex: 1 }} onClick={saveFieldNote} disabled={actingUi}>Save note</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface JobDetail {
  id: string; status: string; outcome: string | null; procedure_version_id: string;
  started_at: string; ended_at: string | null;
  events: { event_id: string; event_type: string; step_id: string | null; payload: Record<string, unknown>; occurred_at: string }[];
  evidence: JobPhoto[];
}

const FEEDBACK_STATUSES = ["ok", "confusing", "blocked", "incorrect"] as const;

function FeedbackPanel({ jobId, finished, versionId, role, notify, onProposeRevision }: {
  jobId: string; finished: boolean; versionId: string; role: Role;
  notify: (s: string, kind?: "ok" | "error" | "info") => void;
  onProposeRevision: (versionId: string) => void;
}) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [existing, setExisting] = useState<{ event_id: string; payload: Record<string, unknown> }[]>([]);
  const [ratings, setRatings] = useState<Record<string, { status: string; note: string }>>({});
  const [missing, setMissing] = useState("");
  const [unexpected, setUnexpected] = useState("");
  const [visual, setVisual] = useState<"unknown" | "yes" | "no">("unknown");
  const [assistance, setAssistance] = useState(false);
  const [overall, setOverall] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [v, fb] = await Promise.all([
          api.get<Version>(`/api/procedure-versions/${versionId}`),
          api.get<{ feedback: { event_id: string; payload: Record<string, unknown> }[] }>(`/api/jobs/${jobId}/feedback`),
        ]);
        if (!alive) return;
        setSteps(v.steps || []);
        setExisting(fb.feedback || []);
        const init: Record<string, { status: string; note: string }> = {};
        for (const s of v.steps || []) init[s.id] = { status: "ok", note: "" };
        setRatings(init);
      } catch { /* offline: form stays unavailable with a note */ }
      finally { if (alive) setLoaded(true); }
    })();
    return () => { alive = false; };
  }, [jobId, versionId]);

  async function submit(replace: boolean) {
    setBusy(true);
    try {
      await api.post(`/api/jobs/${jobId}/feedback`, {
        step_outcomes: Object.entries(ratings).map(([step_id, r]) => ({ step_id, status: r.status, note: r.note })),
        missing_info: missing, unexpected,
        visual_correct: visual === "unknown" ? null : visual === "yes",
        assistance_needed: assistance, overall, replace,
      });
      notify(replace ? "Feedback superseded — history preserved, latest will be used for proposals." : "Field feedback recorded and linked to this job.", "ok");
      const fb = await api.get<{ feedback: { event_id: string; payload: Record<string, unknown> }[] }>(`/api/jobs/${jobId}/feedback`);
      setExisting(fb.feedback || []);
    } catch (e) { notify(e instanceof Error ? e.message : "Feedback save failed", "error"); }
    finally { setBusy(false); }
  }

  async function propose() {
    if (!window.confirm("Generate an AI-assisted improvement draft from this job's feedback? The approved revision stays untouched; you review the draft next.")) return;
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; version_id: string; changes: unknown[]; simulated: boolean; summary: string }>(
        `/api/jobs/${jobId}/propose-improvement`, {});
      notify(r.simulated
        ? `Draft created with ${r.changes.length} suggestion(s) from labelled simulated analysis — verify every change in Review.`
        : `Draft created with ${r.changes.length} Muse Spark suggestion(s). Review it next.`, "ok");
      onProposeRevision(r.version_id);
    } catch (e) { notify(e instanceof Error ? e.message : "Proposal failed", "error"); }
    finally { setBusy(false); }
  }

  const canReview = role === "reviewer" || role === "expert";
  return (
    <div style={{ marginTop: 8 }}>
      <span className="eyebrow">Field feedback → improvement</span>
      {!loaded && <p className="muted small-text">Loading feedback…</p>}
      {loaded && steps.length === 0 && <p className="muted small-text">Step list unavailable offline — feedback needs the server copy of this revision.</p>}
      {loaded && steps.length > 0 && (
        <>
          {existing.length > 0 && (
            <div className="notice ok" role="status">
              <strong>{existing.length} feedback record(s)</strong> linked to this job.{" "}
              {(() => {
                const latest = existing[existing.length - 1].payload as { step_outcomes?: { status: string }[]; overall?: string };
                const bad = (latest.step_outcomes || []).filter((o) => o.status !== "ok").length;
                return <span className="muted small-text">Latest: {bad} flagged step(s){latest.overall ? ` — “${latest.overall}”` : ""}.</span>;
              })()}
            </div>
          )}
          <h4>How did each step go?</h4>
          {steps.map((s) => (
            <div key={s.id} className="list-row">
              <p style={{ margin: "0 0 4px" }}><strong>Step {s.step_order}: {s.title}</strong></p>
              <div className="row" role="group" aria-label={`Outcome for step ${s.step_order}`}>
                {FEEDBACK_STATUSES.map((st) => (
                  <button key={st} className={`btn small ${ratings[s.id]?.status === st ? "" : "secondary"}`}
                    aria-pressed={ratings[s.id]?.status === st} disabled={busy}
                    onClick={() => setRatings((r) => ({ ...r, [s.id]: { status: st, note: r[s.id]?.note || "" } }))}>{st}</button>
                ))}
              </div>
              {ratings[s.id]?.status !== "ok" && (
                <label>What went wrong on step {s.step_order}?<textarea rows={2} value={ratings[s.id]?.note || ""}
                  onChange={(e) => setRatings((r) => ({ ...r, [s.id]: { status: r[s.id].status, note: e.target.value } }))}
                  placeholder="e.g. Unclear which screw — photo would help." maxLength={2000} /></label>
              )}
            </div>
          ))}
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <label>Missing steps or info<textarea rows={2} value={missing} onChange={(e) => setMissing(e.target.value)} maxLength={4000} placeholder="Anything the procedure left out?" /></label>
            <label>Unexpected condition<textarea rows={2} value={unexpected} onChange={(e) => setUnexpected(e.target.value)} maxLength={4000} placeholder="Anything surprising in the field?" /></label>
          </div>
          <div className="row" role="group" aria-label="Did the visuals identify the right component?">
            <span className="small-text"><strong>Visuals identified the right component?</strong></span>
            {(["unknown", "yes", "no"] as const).map((v) => (
              <button key={v} className={`btn small ${visual === v ? "" : "secondary"}`} aria-pressed={visual === v} disabled={busy} onClick={() => setVisual(v)}>
                {v === "unknown" ? "Not sure" : v === "yes" ? "Yes" : "No"}
              </button>
            ))}
            <label className="check-row" htmlFor={`assist-${jobId}`}><input id={`assist-${jobId}`} type="checkbox" checked={assistance} disabled={busy} onChange={(e) => setAssistance(e.target.checked)} /> Expert assistance was needed</label>
          </div>
          <label>Overall notes<textarea rows={2} value={overall} onChange={(e) => setOverall(e.target.value)} maxLength={4000} placeholder="Would you follow this procedure again as written?" /></label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy} onClick={() => void submit(false)}>{existing.length ? "Add another record" : "Submit feedback"}</button>
            {existing.length > 0 && <button className="btn secondary" disabled={busy} onClick={() => void submit(true)}>Supersede with this version</button>}
            {finished && existing.length > 0 && canReview && (
              <button className="btn secondary" disabled={busy} onClick={() => void propose()}>Create improvement proposal</button>
            )}
          </div>
          {finished && existing.length > 0 && !canReview && (
            <p className="muted small-text">A reviewer can turn this feedback into a draft revision.</p>
          )}
          {!finished && <p className="muted small-text">Proposals unlock once the job is finished.</p>}
        </>
      )}
    </div>
  );
}

function History({ jobs, reload, role, onProposeRevision, notify }: { jobs: JobRow[]; reload: () => void; role: Role; onProposeRevision: (versionId: string) => void; notify: (s: string, kind?: "ok" | "error" | "info") => void }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  async function toggle(j: JobRow) {
    if (openId === j.id) { setOpenId(null); setDetail(null); return; }
    setOpenId(j.id); setDetail(null); setDetailError("");
    try { setDetail(await api.get<JobDetail>(`/api/jobs/${j.id}`)); }
    catch { setDetailError("Job detail unavailable offline — the list above is the last server-confirmed state."); }
  }
  return <div className="card"><h2><Icon name="schedule" size={20} /> Job history</h2><button className="btn small secondary" onClick={reload}><Icon name="sync" size={16} /> Refresh</button>
    {jobs.length === 0 ? <div className="empty">No jobs yet. Completed work, exceptions, and sync state will appear here.</div>
      : jobs.map((j) => (
        <div key={j.id} className="list-row">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <p style={{ margin: 0 }}><strong>{j.procedure_title}</strong> <span className="muted small-text num">{new Date(j.started_at).toLocaleString()}</span></p>
            {j.outcome === "completed"
              ? <span className="badge ok"><Icon name="check" size={13} /> Completed</span>
              : j.status === "finished"
                ? <span className="badge warn"><Icon name="flag" size={13} /> {j.outcome || "Completed"} — view summary</span>
                : <span className="badge info">In progress · {j.events} event{j.events === 1 ? "" : "s"}</span>}
          </div>
          <button className="btn small secondary" aria-expanded={openId === j.id} onClick={() => void toggle(j)}>{openId === j.id ? "Hide details" : "View details"}</button>
          {openId === j.id && detailError && <p className="muted">{detailError}</p>}
          {openId === j.id && detail && (
            <div style={{ marginTop: 8 }}>
              <p className="muted small-text">Revision {detail.procedure_version_id.slice(0, 8)}… · started {new Date(detail.started_at).toLocaleString()}{detail.ended_at ? ` · ended ${new Date(detail.ended_at).toLocaleString()}` : " · not finished"}. These are server-confirmed events.</p>
              {detail.events.length === 0 && <p className="muted">No events recorded yet.</p>}
              {detail.events.map((e) => (
                <p key={e.event_id} className="list-row">
                  <span className="tag">{e.event_type}</span> {new Date(e.occurred_at).toLocaleString()}
                  {e.event_type === "issue_recorded" && <> · {String((e.payload as { issue_type?: string }).issue_type || "Issue")}: {String((e.payload as { note?: string }).note || "")}</>}
                  {e.event_type === "field_note" && <> · {String((e.payload as { note?: string }).note || "")}</>}
                  {e.event_type === "evidence_attached" && <> · photo: {String((e.payload as { description?: string }).description || "")}</>}
                  {e.event_type === "field_feedback" && <> · structured feedback ({((e.payload as { step_outcomes?: unknown[] }).step_outcomes || []).length} step rating(s)){String((e.payload as { overall?: string }).overall || "") ? `: “${String((e.payload as { overall?: string }).overall)}”` : ""}</>}
                  {e.event_type === "issue_recorded" && (role === "reviewer" || role === "expert") && (
                    <> <button className="btn small secondary" onClick={() => onProposeRevision(detail.procedure_version_id)}>Propose revision from this feedback</button></>
                  )}
                </p>
              ))}
              <FeedbackPanel jobId={detail.id} finished={detail.status === "finished"} versionId={detail.procedure_version_id}
                role={role} notify={notify} onProposeRevision={onProposeRevision} />
              {detail.evidence && detail.evidence.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <span className="eyebrow">Field photos ({detail.evidence.length})</span>
                  <div className="row" style={{ marginTop: 6 }}>
                    {detail.evidence.map((p) => p.image_url && (
                      <figure key={p.id} style={{ margin: 0, maxWidth: 160 }}>
                        <img src={p.image_url} alt={p.description || "Field photo"} style={{ width: "100%", borderRadius: 8, border: "1px solid var(--line)" }} />
                        <figcaption className="muted small-text">{p.description}{p.captured_at ? ` · ${new Date(p.captured_at).toLocaleTimeString()}` : ""}</figcaption>
                      </figure>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    <p className="muted">Event history is append-only and server-confirmed. A proposed revision always goes through normal review — field feedback never edits an approved version directly.</p></div>;
}

function Manuals({ notify }: { notify: (s: string, kind?: "ok" | "error" | "info") => void }) {
  const [manuals, setManuals] = useState<ManualRow[]>([]);
  const [q, setQ] = useState("knob");
  const [hits, setHits] = useState<{ manual_title: string; page_number: number | null; snippet: string }[]>([]);
  async function load() { try { setManuals(await api.get<ManualRow[]>("/api/manuals")); } catch { notify("Manual list unavailable offline.", "error"); } }
  useEffect(() => { load(); }, []);
  async function upload(f: File | undefined) {
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) { notify("Only PDF manuals are supported.", "error"); return; }
    if (f.size > 15 * 1024 * 1024) { notify("PDF is larger than 15 MB — split or compress it before importing.", "error"); return; }
    const fd = new FormData(); fd.append("file", f); fd.append("title", f.name);
    try { const r = await api.upload<{ searchable: boolean }>("/api/manuals", fd); notify(r.searchable ? "Manual indexed and searchable." : "Manual stored, but no extractable text was found (scanned PDFs need OCR, which this build does not do).", r.searchable ? "ok" : "info"); load(); }
    catch (e) { notify(e instanceof Error ? e.message : "Upload failed", "error"); }
  }
  async function search() { try { setHits(await api.get("/api/manuals/search?q=" + encodeURIComponent(q))); } catch { notify("Search needs the server in this build; cached procedure text still works offline in Guided job.", "error"); } }
  return <div className="card"><h2><Icon name="book" size={20} /> Manuals</h2>
    <p className="muted">Imported manuals are indexed on the server for search. They are not downloaded for offline use in this build — offline work uses downloaded approved procedures.</p>
    <label className="btn secondary">Import PDF manual (max 15 MB)<input className="visually-hidden" type="file" accept="application/pdf" aria-label="Import PDF manual" onChange={(e) => upload(e.target.files?.[0])} /></label>
    {manuals.length === 0 ? <div className="empty">No manuals imported. Import a PDF you are authorized to use.</div> : manuals.map((m) => <p key={m.id}><strong>{m.title}</strong> <span className="muted">{m.model || ""} · {m.chunks} chunk(s) indexed</span></p>)}
    <label htmlFor="man-q">Search manual text (shows source manual + page)</label><input id="man-q" value={q} onChange={(e) => setQ(e.target.value)} />
    <button className="btn" style={{ marginTop: 10 }} onClick={search}>Search manuals</button>
    {hits.map((h, i) => <div key={i} className="notice ok"><strong>{h.manual_title}</strong>{h.page_number ? ` · page ${h.page_number}` : ""}<br />{h.snippet}</div>)}
  </div>;
}

function PwaDiagnostics({ pwa }: { pwa: { canInstall: boolean; installed: boolean } }) {
  const [info, setInfo] = useState<string | null>(null);
  const [links, setLinks] = useState<AssetLinksStatus | null>(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      const parts: string[] = [];
      try {
        parts.push(`Display mode: ${window.matchMedia("(display-mode: standalone)").matches ? "standalone (installed)" : "browser (open tab — install the app for fullscreen)"}`);
      } catch { parts.push("Display mode: unknown"); }
      try {
        if (!("serviceWorker" in navigator)) parts.push("Service worker: unsupported in this browser");
        else {
          const reg = await navigator.serviceWorker.getRegistration();
          if (!reg) parts.push("Service worker: not registered yet (reload once)");
          else if (reg.active) parts.push(`Service worker: active (${reg.scope})`);
          else if (reg.waiting || reg.installing) parts.push("Service worker: new version ready — accept the in-app update banner, then reload");
          else parts.push("Service worker: registered, activating…");
          parts.push(`Controlled by worker: ${navigator.serviceWorker.controller ? "yes" : "no"}`);
        }
      } catch { parts.push("Service worker: check failed"); }
      try {
        const r = await fetch("manifest.webmanifest", { headers: { Accept: "application/manifest+json" } });
        parts.push(`Manifest: ${r.ok ? "served" : `HTTP ${r.status}`} · start_url ${new URL((await r.clone().json() as { start_url?: string }).start_url || "/", window.location.origin).pathname}`);
      } catch {
        parts.push("Manifest: not fetchable offline");
      }
      parts.push(`Install prompt: ${pwa.installed ? "installed (running standalone or install event seen)" : pwa.canInstall ? "ready — use the Install button below" : "not offered by this browser right now (already installed, or iOS — use Share → Add to Home Screen)"}`);
      if (alive) setInfo(parts.join(" · "));
    })();
    return () => { alive = false; };
  }, [pwa.canInstall, pwa.installed]);
  useEffect(() => {
    let alive = true;
    void checkAssetLinks().then((s) => { if (alive) setLinks(s); });
    return () => { alive = false; };
  }, []);
  return (
    <div>
      <p className="muted small-text" role="status">{info || "Checking install state…"}</p>
      {links && (
        <p className="muted small-text" role="status">
          App links (APK/TWA): {links.detail}
        </p>
      )}
    </div>
  );
}

function Settings({ pending, role, setRole, clearCache, onSignOut, pwa }: { pending: number; role: Role; setRole: (r: Role) => void; clearCache: () => void; onSignOut: () => void; pwa: { canInstall: boolean; installed: boolean; outcome: string | null; install: () => Promise<void> } }) {
  const [note, setNote] = useState("");
  const [health, setHealth] = useState("");
  async function seed() { try { const r = await api.post<{ seeded: boolean }>("/api/seed", {}); setNote(r.seeded ? "Demo data seeded: approved harness procedure + operator notes. Open Procedures to start." : "Demo data already present."); } catch (e) { setNote(e instanceof Error ? e.message : "Seed failed — is the backend running?"); } }
  async function checkHealth() {
    setHealth("Checking…");
    try {
      const h = await api.get<{ status: string; db: boolean; ai_live: boolean; models: Record<string, string> }>("/api/health");
      setHealth(`API ${h.status} · database ${h.db ? "ok" : "unreachable"} · AI ${h.ai_live ? "live" : "simulated (no key)"} · Spark ${h.models.spark} · SAM ${h.models.segment} · Voice ${h.models.voice}`);
    } catch { setHealth("API unreachable from this browser. Queued work stays on this device."); }
  }
  return <div className="card"><h2><Icon name="cog" size={20} /> Settings</h2>
    <h3>Demo data</h3><p className="muted">Harmless Benchtop Cable Trainer scenario. Seeding is idempotent.</p>
    <button className="btn" onClick={seed}>Seed demo procedure</button>{note && <div className="notice ok" role="status">{note}</div>}
    <h3>Offline storage</h3><p>{pending} event(s) pending synchronization. Queued events and the active job survive reloads and airplane mode.</p>
    <button className="btn secondary" onClick={clearCache}>Clear downloaded procedure cache</button>
    <h3>Identity (demo)</h3><p className="muted">This build uses header-based demo identity — the server still enforces reviewer-only approval, but it is not production authentication. Switching role here only changes the demo identity sent to the server; it cannot grant real permissions. Your role choice is remembered on this device.</p>
    <label htmlFor="demo-role">Demo role</label>
    <select id="demo-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
      <option value="technician">Technician</option><option value="expert">Expert</option><option value="reviewer">Reviewer</option>
    </select>
    <div className="row" style={{ marginTop: 10 }}>
      <button className="btn secondary" onClick={onSignOut}>Sign out on this device</button>
    </div>
    <h3>Privacy</h3><p className="muted">The Meta API key lives only on the backend and never reaches this browser. Recordings are sent for transcription only when connected and only after you press Record. Delete local data any time by clearing site storage; server records follow your team retention policy.</p>
    <h3>Diagnostics</h3><p className="muted">Check the real API, database, and AI status. No secrets are shown.</p>
    <button className="btn secondary" onClick={checkHealth}>Check connection</button>{health && <div className="notice info" role="status">{health}</div>}
    <h3>Install &amp; display</h3>
    <p className="muted">Use this to diagnose the address-bar issue: in the installed app this should read <strong>standalone</strong> with a controlled service worker. In a browser tab it reads <strong>browser</strong> — install the app (Share/Add to Home Screen) for fullscreen.</p>
    {pwa.canInstall && !pwa.installed && (
      <div className="row" style={{ marginBottom: 8 }}>
        <button className="btn" onClick={() => void pwa.install()}>Install app on this device</button>
      </div>
    )}
    {pwa.outcome && <p className="muted small-text" role="status">Install prompt result: {pwa.outcome}.</p>}
    <PwaDiagnostics pwa={pwa} />
  </div>;
}


