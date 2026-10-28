import { useCallback, useEffect, useRef, useState } from "react";
import { api, setIdentity } from "./api";
import { idb, uuid } from "./db";
import LiveMode from "./LiveMode";
import TutorialMode from "./TutorialMode";
import LiveTranscribe from "./LiveTranscribe";
import { extractObjectPhrase, promptVariants } from "./speechPrompt";
import type { JobEventRec, LocalJob, ProcSummary, Role, Version, View } from "./types";

const ISSUE_TYPES = ["Component not found", "Instructions unclear", "Expected result not observed", "Tool unavailable", "Manual mismatch", "Unexpected condition", "Other"];

function mediaErrorMessage(e: unknown, kind: "microphone" | "camera"): string {
  const name = e instanceof DOMException ? e.name : e instanceof Error ? e.name : "";
  const label = kind === "microphone" ? "Microphone" : "Camera";
  if (!window.isSecureContext) return `${label} unavailable: browser media requires HTTPS or http://localhost (not a LAN IP). Open the app via localhost or an HTTPS URL.`;
  if (name === "NotAllowedError" || name === "SecurityError") return `${label} blocked (${name}). Click the lock/site-settings icon in the address bar, allow ${kind} access for this site, then try again. Paste/type the transcript below still works.`;
  if (name === "NotFoundError" || name === "DevicesNotFoundError") return `No ${kind} found (${name}). Connect/enable a ${kind} in Windows Settings > Privacy, then try again.`;
  if (name === "NotReadableError" || name === "TrackStartError") return `${label} is busy (${name}). Close other apps using it (Teams/Zoom/Camera) and try again.`;
  if (name === "OverconstrainedError") return `${label} does not support the requested settings (${name}). Try again — a basic device will be requested.`;
  if (name === "NotSupportedError" || name === "TypeError") return `${label} unsupported in this browser (${name || "no mediaDevices"}). Use current Chrome/Edge on http://localhost or HTTPS.`;
  return `${label} unavailable (${name || "unknown error"}). Check browser permission and device, then try again.`;
}

function mediaDevicesOrFail(kind: "microphone" | "camera"): MediaDevices {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new DOMException("mediaDevices unavailable", "NotSupportedError");
  }
  return navigator.mediaDevices;
}

async function countDevices(kind: "audioinput" | "videoinput"): Promise<number | null> {
  try {
    if (!navigator.mediaDevices?.enumerateDevices) return null;
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === kind).length;
  } catch { return null; }
}

interface Capture { id: string; title: string; status: string; task_description: string; transcript_corrected: string }
interface JobRow { id: string; procedure_title: string; status: string; outcome: string | null; started_at: string; events: number }
interface ManualRow { id: string; title: string; model: string | null; chunks: number }

export default function App() {
  const [view, setView] = useState<View>("home");
  const [role, setRole] = useState<Role>("technician");
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
  const [reviewVersion, setReviewVersion] = useState<Version | null>(null);

  const notify = useCallback((text: string, kind: "ok" | "error" | "info" = "ok") => { setMsg(text); setMsgKind(kind); }, []);

  const refreshCached = useCallback(async () => {
    const vs = await idb.all<Version>("versions");
    setCachedIds(new Set(vs.map((v) => v.id)));
  }, []);

  const refreshPending = useCallback(async () => {
    const evs = await idb.all<JobEventRec>("events");
    setPending(evs.filter((e) => e.sync_status === "pending").length);
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
      try { await api.get("/api/health"); } catch { setSyncState("failed"); notify("Server unreachable. Events stay queued on this device.", "error"); return; }
      const evs = (await idb.all<JobEventRec>("events")).filter((e) => e.sync_status === "pending");
      let failedCount = 0;
      if (evs.length) {
        const res = await api.post<{ acknowledged: string[]; duplicates?: string[]; failed?: unknown[] }>("/api/sync/events", { events: evs });
        failedCount = res.failed?.length || 0;
        for (const id of [...(res.acknowledged || []), ...(res.duplicates || [])]) {
          const row = evs.find((e) => e.event_id === id);
          if (row) await idb.put("events", id, { ...row, sync_status: "synced" });
        }
      }
      setSyncState(failedCount ? "failed" : "idle");
      notify(evs.length ? (failedCount ? `Synchronized, but ${failedCount} event(s) were rejected by the server and remain visible as pending.` : "Synchronization complete — server acknowledged all queued events.") : "Nothing pending to synchronize.", failedCount ? "error" : "ok");
      await refreshPending(); await loadLists();
    } catch (e) { setSyncState("failed"); notify(e instanceof Error ? e.message : "Sync failed", "error"); }
  }, [loadLists, notify, refreshPending]);

  useEffect(() => { setIdentity(role === "technician" ? "demo-tech" : role === "expert" ? "demo-expert" : "demo-reviewer", role); loadLists(); }, [role, loadLists]);
  useEffect(() => {
    loadLists(); refreshPending(); refreshCached();
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
  }, [loadLists, refreshPending, refreshCached, syncNow]);

  useEffect(() => {
    const h = document.querySelector<HTMLElement>("main h2");
    if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
  }, [view]);

  async function queueEvent(ev: Omit<JobEventRec, "sync_status">) {
    await idb.put("events", ev.event_id, { ...ev, sync_status: "pending" });
    await refreshPending();
  }

  async function openVersion(vid: string): Promise<Version | null> {
    try {
      const v = await api.get<Version>(`/api/procedure-versions/${vid}`);
      await idb.put("versions", v.id, v);
      void refreshCached();
      return v;
    } catch {
      return (await idb.get<Version>("versions", vid)) || null;
    }
  }

  async function startJob(p: ProcSummary) {
    if (!p.approved_version_id) { notify("This procedure has no approved version yet.", "error"); return; }
    const v = await openVersion(p.approved_version_id);
    if (!v) { notify("Could not load the approved procedure. Connect once to download it for offline use.", "error"); return; }
    if (!v.steps.length) { notify("This approved version has no steps and cannot start a job.", "error"); return; }
    let jobId = uuid();
    try {
      const j = await api.post<{ id: string }>("/api/jobs", { procedure_id: p.id, procedure_version_id: v.id });
      jobId = j.id;
    } catch { notify("Offline: job created on this device and will register on sync. (Server job start requires one online start in this build.)", "info"); }
    const local: LocalJob = { id: jobId, procedure_id: p.id, procedure_version_id: v.id, title: p.title, current: 0, stepStates: {}, started_at: new Date().toISOString(), finished: false };
    await idb.put("jobs", "active", local);
    setActiveJob(local); setActiveVersion(v); setView("job");
  }

  const pendingReview = procs.filter((p) => p.has_pending_review).length;
  const deskNav: { view: View; label: string }[] = [
    { view: "home", label: "Workbench" }, { view: "library", label: "Procedures" }, { view: "capture", label: "Capture" },
    { view: "review", label: `Review${pendingReview ? ` (${pendingReview})` : ""}` }, { view: "job", label: "Guided job" }, { view: "activity", label: "Activity" },
  ];
  const mobileNav: { view: View; label: string }[] = [
    { view: "home", label: "Home" }, { view: "library", label: "Procedures" }, { view: "capture", label: "Capture" }, { view: "activity", label: pending ? `Activity (${pending})` : "Activity" },
  ];
  const mobileCurrent: View = view === "home" || view === "library" || view === "capture" ? view : "activity";

  async function handleSetJob(j: LocalJob | null) {
    if (!j) { setActiveJob(null); return; }
    if (j.finished) { setActiveJob(null); await idb.del("jobs", "active"); return; }
    setActiveJob(j); await idb.put("jobs", "active", j);
  }

  return (
    <div>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <h1 className="brand">TraceLoop FieldGuard<small>Capture · Approve · Guide · Verify — offline-first</small></h1>
        <span className={`pill ${online ? "online" : "offline"}`}>{online ? "Online" : "Offline — working locally"}</span>
        <span className="pill">{pending} pending sync</span>
        {syncState === "failed" && <span className="pill error">Sync needs attention</span>}
        <button className="btn small secondary" onClick={() => void syncNow()} disabled={syncState === "syncing"}>{syncState === "syncing" ? "Syncing…" : "Sync now"}</button>
        <label style={{ margin: 0, color: "#fff" }}>Role
          <select aria-label="Demo role" value={role} onChange={(e) => setRole(e.target.value as Role)} style={{ marginLeft: 8 }}>
            <option value="technician">Technician</option><option value="expert">Expert</option><option value="reviewer">Reviewer</option>
          </select>
        </label>
      </header>
      <div className="shell">
        <nav className="nav" aria-label="Primary">
          {deskNav.map((n) => (
            <button key={n.view} aria-current={view === n.view ? "page" : undefined} onClick={() => setView(n.view)}>{n.label}</button>
          ))}
        </nav>
        <main id="main">
          {msg && <div className={`notice ${msgKind === "error" ? "error" : msgKind === "info" ? "info" : "ok"}`} role={msgKind === "error" ? "alert" : "status"}>{msg} <button className="btn small secondary" onClick={() => setMsg("")}>Dismiss</button></div>}
          {listsLoading && procs.length === 0 && <div className="card" aria-label="Loading procedures"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>}
          {view === "home" && <Home procs={procs} jobs={jobs} activeJob={activeJob} pending={pending} role={role} go={setView} continueJob={() => { if (activeJob) { openVersion(activeJob.procedure_version_id).then((v) => { if (v) { setActiveVersion(v); setView("job"); } else notify("Downloaded procedure not found on this device. Reconnect and open it from Procedures.", "error"); }); } }} />}
          {view === "library" && <Library procs={procs} cachedIds={cachedIds} reload={loadLists} startJob={startJob} openVersion={async (vid) => { const v = await openVersion(vid); if (v) { setReviewVersion(v); setView("review"); } else notify("That version is not available offline yet.", "error"); }} cache={async (vid) => { const v = await openVersion(vid); notify(v ? "Saved for offline use — verified in local storage on this device." : "Download failed — check connection.", v ? "ok" : "error"); }} />}
          {view === "capture" && <CaptureView done={(v) => { setReviewVersion(v); setView("review"); loadLists(); }} />}
          {view === "review" && <ReviewView version={reviewVersion} setVersion={setReviewVersion} procs={procs} openVersion={openVersion} role={role} reload={loadLists} notify={notify} />}
          {view === "job" && <JobView job={activeJob} version={activeVersion} queueEvent={queueEvent} setJob={handleSetJob} notify={notify} reload={loadLists} go={setView} />}
          {view === "activity" && <Activity jobs={jobs} pending={pending} pendingReview={pendingReview} reload={loadLists} go={setView} syncNow={() => void syncNow()} syncing={syncState === "syncing"} />}
          {view === "history" && <History jobs={jobs} reload={loadLists} />}
          {view === "manuals" && <Manuals notify={notify} />}
          {view === "settings" && <Settings pending={pending} role={role} clearCache={async () => { await idb.clear("versions"); await refreshCached(); notify("Offline procedure cache cleared. Downloaded jobs and queued events were kept."); }} />}
        </main>
      </div>
      {view !== "job" && (
        <nav className="bottomnav" aria-label="Primary mobile">
          {mobileNav.map((n) => (
            <button key={n.view} aria-current={mobileCurrent === n.view ? "page" : undefined} onClick={() => setView(n.view)}>{n.label}</button>
          ))}
        </nav>
      )}
    </div>
  );
}

function Home({ procs, jobs, activeJob, pending, role, go, continueJob }: { procs: ProcSummary[]; jobs: JobRow[]; activeJob: LocalJob | null; pending: number; role: Role; go: (v: View) => void; continueJob: () => void }) {
  const approved = procs.filter((p) => p.approved_version_id);
  const pendingReview = procs.filter((p) => p.has_pending_review).length;
  return (
    <div>
      <div className="card primary-action">
        <h2>{activeJob ? "Continue your job" : "What needs doing?"}</h2>
        {activeJob ? (<div><p><strong>{activeJob.title}</strong> — step {activeJob.current + 1} in progress since {new Date(activeJob.started_at).toLocaleString()}. Your progress is saved on this device.</p>
          <button className="btn" onClick={continueJob}>Continue active job</button></div>)
          : (<div><p className="muted">Start from an approved procedure, or capture new expert knowledge. Approved work keeps running without a connection.</p>
            <div className="row"><button className="btn" onClick={() => go("library")}>Find an approved procedure</button><button className="btn secondary" onClick={() => go("capture")}>Capture knowledge</button></div></div>)}
      </div>
      {(pending > 0 || (pendingReview > 0 && role === "reviewer")) && (
        <div className="card"><h3>Needs attention</h3>
          {pending > 0 && <p>{pending} event(s) saved on this device, waiting for server acknowledgment. Use <strong>Sync now</strong> when connected.</p>}
          {pendingReview > 0 && role === "reviewer" && <p>{pendingReview} procedure(s) waiting for your review.</p>}
          <div className="row">{pendingReview > 0 && role === "reviewer" && <button className="btn secondary" onClick={() => go("review")}>Open review queue</button>}<button className="btn secondary" onClick={() => go("activity")}>Open activity</button></div>
        </div>
      )}
      <div className="grid">
        <div className="card"><h3>Approved procedures ({approved.length})</h3><p className="muted">Only human-approved versions can start a job.</p><button className="btn secondary" onClick={() => go("library")}>Open procedure library</button></div>
        <div className="card"><h3>Capture expert knowledge</h3><p className="muted">Record, photograph, and generate a reviewable draft — never auto-approved.</p><button className="btn secondary" onClick={() => go("capture")}>New capture session</button></div>
        <div className="card"><h3>Recent work</h3><p className="muted">{jobs.length ? `${jobs.length} job(s) on record. Latest: ${jobs[0].procedure_title} (${jobs[0].status}).` : "No jobs yet."}</p><button className="btn secondary" onClick={() => go("activity")}>View activity</button></div>
      </div>
      <div className="card"><h3>Recent procedures</h3>
        {procs.length === 0 ? <div className="empty">No procedures yet. Seed demo data from Activity → Settings, or capture expert knowledge.</div>
          : procs.slice(0, 5).map((p) => <p key={p.id} className="list-row"><strong>{p.title}</strong> {p.approved_version_id ? <span className="tag approved">Approved version available</span> : <span className="tag warn">No approved version</span>}</p>)}
      </div>
    </div>
  );
}

function Activity({ jobs, pending, pendingReview, reload, go, syncNow, syncing }: { jobs: JobRow[]; pending: number; pendingReview: number; reload: () => void; go: (v: View) => void; syncNow: () => void; syncing: boolean }) {
  return (
    <div>
      <div className="card"><h2>Activity</h2>
        <p>{pending} event(s) pending synchronization. Events are only marked synced after the server acknowledges them.</p>
        <div className="row">
          <button className="btn" onClick={syncNow} disabled={syncing}>{syncing ? "Syncing…" : "Sync now"}</button>
          <button className="btn secondary" onClick={() => go("review")}>Review queue{pendingReview ? ` (${pendingReview})` : ""}</button>
          <button className="btn secondary" onClick={() => go("manuals")}>Manuals</button>
          <button className="btn secondary" onClick={() => go("settings")}>Settings</button>
        </div>
      </div>
      <History jobs={jobs} reload={reload} />
    </div>
  );
}

function Library({ procs, cachedIds, reload, startJob, openVersion, cache }: { procs: ProcSummary[]; cachedIds: Set<string>; reload: () => void; startJob: (p: ProcSummary) => void; openVersion: (id: string) => void; cache: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "approved" | "offline">("all");
  const list = procs.filter((p) => p.title.toLowerCase().includes(q.toLowerCase()))
    .filter((p) => filter === "all" || (filter === "approved" ? !!p.approved_version_id : !!(p.approved_version_id && cachedIds.has(p.approved_version_id))));
  return (
    <div className="card">
      <h2>Procedure library</h2>
      <label htmlFor="proc-search">Search procedures</label>
      <input id="proc-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. cable harness" />
      <label htmlFor="proc-filter">Show</label>
      <select id="proc-filter" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
        <option value="all">All procedures</option><option value="approved">Approved only</option><option value="offline">Offline-ready only</option>
      </select>
      <button className="btn small secondary" onClick={reload} style={{ margin: "10px 0" }}>Refresh from server</button>
      {list.length === 0 && <div className="empty">No procedures match. Capture expert knowledge or seed the demo from Activity → Settings.</div>}
      {list.map((p) => { const latest = p.versions[p.versions.length - 1]; const offlineReady = !!(p.approved_version_id && cachedIds.has(p.approved_version_id)); return (
        <div key={p.id} className="card">
          <h3>{p.title}</h3>
          <p>{p.versions.map((v) => <span key={v.id} className={`tag ${v.status === "approved" ? "approved" : v.status === "pending_review" ? "warn" : ""}`}>v{v.version_number} · {v.status}</span>)}{offlineReady && <span className="tag approved">Offline ready</span>}</p>
          <div className="row">
            <button className="btn" disabled={!p.approved_version_id} onClick={() => startJob(p)}>Start guided job</button>
            {p.approved_version_id && <button className="btn secondary" onClick={() => cache(p.approved_version_id!)}>{offlineReady ? "Update offline copy" : "Save for offline use"}</button>}
            {latest && <button className="btn secondary" onClick={() => openVersion(latest.id)}>Inspect latest version</button>}
          </div>
        </div> ); })}
    </div>
  );
}

interface SegMask { svg_path: string; width: number; height: number }
interface SegObject { object_id: number; bbox_norm: number[]; confidence?: number | null; mask?: SegMask | null }
interface SegGeometry { bbox_norm: number[]; label: string; mask?: SegMask | null; objects?: SegObject[]; image_size?: number[] }

const CAPTURE_DRAFT_KEY = "fg-capture-draft-v1";
function loadCaptureDraft(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(CAPTURE_DRAFT_KEY) || "{}") as Record<string, string>; } catch { return {}; }
}

function CaptureView({ done }: { done: (v: Version) => void }) {
  const [mode, setMode] = useState<"photo" | "live" | "tutorial">("photo");
  const saved = useRef(loadCaptureDraft()).current;
  const [title, setTitle] = useState(saved.title || "Reseat the trainer cable harness");
  const [assetName, setAssetName] = useState(saved.assetName || "Benchtop Cable Trainer v1");
  const [desc, setDesc] = useState(saved.desc || "Expert walkthrough of the harness reseat on the harmless training assembly.");
  const [capId, setCapId] = useState<string | null>(saved.capId || null);
  const [transcript, setTranscript] = useState(saved.transcript || "First power off the trainer and remove the two enclosure screws. Then check the blue adjustment knob turns smoothly. Next press each harness connector until the latch clicks. Finally route cables through the guide clips, close the cover, and verify the indicator sequence.");
  const [status, setStatus] = useState("");
  const [statusKind, setStatusKind] = useState<"warn" | "error" | "ok">("warn");
  const [busy, setBusy] = useState(false);
  const [camState, setCamState] = useState<"unknown" | "ready" | "blocked">("unknown");
  const [cameraOpen, setCameraOpen] = useState(false);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [segPrompt, setSegPrompt] = useState(saved.segPrompt || "blue adjustment knob");
  const [photoEvId, setPhotoEvId] = useState<string | null>(saved.photoEvId || null);
  const [seg, setSeg] = useState<{ id: string; geometry: SegGeometry; simulated: boolean; note?: string; status?: string } | null>(null);
  const [segAttempts, setSegAttempts] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [detectedPhrase, setDetectedPhrase] = useState<string | null>(null);
  const [recoveryTap, setRecoveryTap] = useState<{ nx: number; ny: number } | null>(null);
  const dismissedPhraseRef = useRef("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const camStreamRef = useRef<MediaStream | null>(null);
  const photoUrlRef = useRef<string | null>(null);

  function say(text: string, kind: "warn" | "error" | "ok" = "warn") { setStatus(text); setStatusKind(kind); }
  useEffect(() => {
    try { localStorage.setItem(CAPTURE_DRAFT_KEY, JSON.stringify({ title, assetName, desc, transcript, segPrompt, capId: capId || "", photoEvId: photoEvId || "" })); } catch { /* storage full/blocked: session still works */ }
  }, [title, assetName, desc, transcript, segPrompt, capId, photoEvId]);

  function showPhoto(blob: Blob) {
    if (photoUrlRef.current) URL.revokeObjectURL(photoUrlRef.current);
    const url = URL.createObjectURL(blob);
    photoUrlRef.current = url; setPhotoUrl(url); setSeg(null); setSegAttempts([]); setSuggestions([]); setRecoveryTap(null);
  }
  function stopCamera() {
    camStreamRef.current?.getTracks().forEach((t) => t.stop());
    camStreamRef.current = null; setCameraOpen(false);
  }
  useEffect(() => {
    if (cameraOpen && videoRef.current && camStreamRef.current) {
      videoRef.current.srcObject = camStreamRef.current;
      videoRef.current.play().catch(() => { /* autoplay may need user gesture; user just clicked */ });
    }
  }, [cameraOpen]);
  useEffect(() => () => {
    camStreamRef.current?.getTracks().forEach((t) => t.stop());
    if (photoUrlRef.current) URL.revokeObjectURL(photoUrlRef.current);
  }, []);

  async function create() {
    if (!title.trim()) { say("Give the session a title first.", "error"); return; }
    setBusy(true); say("Creating capture session…");
    try {
      const c = await api.post<Capture>("/api/capture-sessions", { title, task_description: desc, asset_name: assetName, category: "assembly" });
      setCapId(c.id); say("Session saved on the server. Add evidence, then generate the draft.", "ok");
    } catch (e) { say(e instanceof Error ? e.message : "Failed to create session", "error"); } finally { setBusy(false); }
  }

  async function saveTranscript(): Promise<boolean> {
    if (!capId) return false;
    try {
      await api.put(`/api/capture-sessions/${capId}/transcript`, { transcript_original: transcript, transcript_corrected: transcript });
      await api.post<{ id: string }>(`/api/capture-sessions/${capId}/evidence`, { evidence_type: "transcript", text_content: transcript, description: "Expert narration (corrected)", source_reference: "capture-transcript" });
      say("Corrected transcript saved as evidence. The original AI output is preserved separately on the backend.", "ok");
      return true;
    } catch (e) { say(e instanceof Error ? e.message : "Transcript save failed — your text is kept in this form.", "error"); return false; }
  }

  async function openCamera() {
    if (!capId) { setStatus("Create the session first (step 1), then open the camera to attach photo evidence."); return; }
    if (cameraOpen) { stopCamera(); return; }
    try {
      const md = mediaDevicesOrFail("camera");
      const cams = await countDevices("videoinput");
      if (cams === 0) { setCamState("blocked"); setStatus("No camera found. Connect/enable a camera in Windows Settings > Privacy > Camera, then try again — or use Attach photo."); return; }
      let stream: MediaStream;
      try {
        stream = await md.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      } catch (e) {
        if (e instanceof DOMException && (e.name === "OverconstrainedError" || e.name === "NotFoundError")) {
          stream = await md.getUserMedia({ video: true, audio: false });
        } else throw e;
      }
      camStreamRef.current = stream; setCamState("ready"); setCameraOpen(true);
      setStatus("Camera open — frame the component, then Capture photo for SAM segmentation.");
    } catch (e) { setCamState("blocked"); setStatus(mediaErrorMessage(e, "camera")); }
  }

  async function capturePhoto(): Promise<string | null> {
    const video = videoRef.current;
    if (!video || !capId) { setStatus("Open the camera first."); return null; }
    const w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) { setStatus("Camera is still starting — wait a moment and capture again."); return null; }
    const canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d"); if (!ctx) { setStatus("Could not capture a frame from the camera."); return null; }
    ctx.drawImage(video, 0, 0, w, h);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", 0.92));
    if (!blob) { setStatus("Could not encode the captured photo."); return null; }
    showPhoto(blob); stopCamera();
    const fd = new FormData(); fd.append("file", new File([blob], "camera-capture.jpg", { type: "image/jpeg" })); fd.append("description", "Camera photo evidence");
    try {
      const r = await api.upload<{ id: string }>(`/api/capture-sessions/${capId}/image`, fd);
      setPhotoEvId(r.id); say("Photo captured and attached as evidence. Run SAM segmentation below.", "ok");
      return r.id;
    } catch (e) { setStatus(e instanceof Error ? e.message : "Photo upload failed"); return null; }
  }

  async function onPhoto(f: File | undefined) {
    if (!f || !capId) { setStatus("Create the session before attaching photos."); return; }
    showPhoto(f);
    const fd = new FormData(); fd.append("file", f); fd.append("description", "Expert photo evidence");
    try { const r = await api.upload<{ id: string }>(`/api/capture-sessions/${capId}/image`, fd); setPhotoEvId(r.id); say("Photo attached as evidence. Run SAM segmentation on it below.", "ok"); }
    catch (e) { setStatus(e instanceof Error ? e.message : "Photo upload failed"); }
  }

  type SegResp = { id: string; geometry: SegGeometry; simulated: boolean; note?: string; status?: string };

  async function runSegment(overridePrompt?: string, point?: { nx: number; ny: number }, evIdOverride?: string): Promise<SegResp | null> {
    const evId = evIdOverride || photoEvId;
    if (!evId) { say("Attach or capture photo evidence first, then segment it.", "error"); return null; }
    const base = (overridePrompt ?? segPrompt).trim() || "blue adjustment knob";
    try {
      if (point) {
        const r = await api.post<SegResp>(`/api/evidence/${evId}/segment`, { prompt_text: base, prompt_nx: point.nx, prompt_ny: point.ny });
        setSeg(r);
        say(r.status === "no_match" ? "SAM still found nothing at that tap. Try tapping the center of the object, or a clearer photo." : "Tap segmentation returned — confirm the highlighted component on your photo.", r.status === "no_match" ? "warn" : "ok");
        return r;
      }
      // No-match recovery ladder: try progressively simpler prompts automatically.
      const candidates = overridePrompt ? [base] : promptVariants(base);
      const tried: string[] = [];
      let last: SegResp | null = null;
      for (const cand of candidates) {
        tried.push(cand);
        last = await api.post<SegResp>(`/api/evidence/${evId}/segment`, { prompt_text: cand });
        setSeg(last);
        if (last.status !== "no_match" || last.simulated) break;
      }
      setSegAttempts(tried);
      if (last && last.status === "no_match") {
        say(`SAM 3.1 found no match (tried ${tried.map((t) => `“${t}”`).join(", ")}). Use the recovery options below — suggest objects, simplify, or tap the object.`, "warn");
      } else if (last?.simulated) {
        say(last.note || "Segmentation returned in simulated mode.", "warn");
      } else if (last) {
        say(tried.length > 1 ? `Matched with simpler prompt “${tried[tried.length - 1]}” — confirm the highlight.` : "SAM 3.1 segmentation returned — confirm the highlighted component on your photo.", "ok");
      }
      return last;
    } catch (e) { say(e instanceof Error ? e.message : "Segmentation failed", "error"); return null; }
  }

  async function suggestObjects() {
    if (!photoEvId) return;
    say("Asking Muse Spark to name visible objects…");
    try {
      const r = await api.post<{ suggestions: string[]; simulated: boolean; note?: string }>(`/api/evidence/${photoEvId}/suggest-prompts`, {});
      setSuggestions(r.suggestions || []);
      say(r.suggestions?.length ? "Spark suggested these visible objects — tap one to segment it." : (r.note || "No suggestions returned. Type a prompt or tap the object on the photo."), r.suggestions?.length ? "ok" : "warn");
    } catch (e) { say(e instanceof Error ? e.message : "Suggestions failed", "error"); }
  }

  async function segmentPhrase(phrase: string) {
    setDetectedPhrase(phrase); setSegPrompt(phrase);
    if (photoEvId) { say(`Heard “${phrase}” — segmenting it now.`); void runSegment(phrase); }
    else if (cameraOpen) {
      say(`Heard “${phrase}” — capturing this frame and segmenting it.`);
      const id = await capturePhoto();
      if (id) void runSegment(phrase, undefined, id);
      else say(`Heard “${phrase}”, but the frame could not be captured. Keep the camera open and say it again.`, "error");
    }
    else say(`Heard “${phrase}”. Attach or capture a photo and it will be segmented.`, "warn");
  }

  // Typed/pasted transcripts also surface a detected object phrase.
  useEffect(() => {
    const p = extractObjectPhrase(transcript);
    if (p && p !== dismissedPhraseRef.current) setDetectedPhrase(p);
  }, [transcript]);

  async function confirmSegment(confirmed: boolean) {
    if (!seg) return;
    await api.post(`/api/segmentation/${seg.id}/confirm`, { confirmed });
  }

  async function generate() {
    if (!capId) return;
    setBusy(true); say("Saving transcript, then generating schema-validated draft with Muse Spark…");
    try {
      const savedOk = await saveTranscript();
      if (!savedOk) { say("Transcript could not be saved, so draft generation was not started. Your text is kept in this form.", "error"); return; }
      const v = await api.post<Version>("/api/procedures/draft", { capture_session_id: capId, manual_excerpt: "" });
      try { localStorage.removeItem(CAPTURE_DRAFT_KEY); } catch { /* ignore */ }
      done(v);
    } catch (e) { say(e instanceof Error ? e.message : "Draft generation failed — your transcript stays saved.", "error"); } finally { setBusy(false); }
  }

  return (
    <div className="card">
      <h2>Knowledge capture</h2>
      <div className="row" role="group" aria-label="Capture mode" style={{ marginBottom: 12 }}>
        <button className={`btn small ${mode === "photo" ? "" : "secondary"}`} aria-pressed={mode === "photo"} onClick={() => setMode("photo")}>Photo</button>
        <button className={`btn small ${mode === "live" ? "" : "secondary"}`} aria-pressed={mode === "live"} onClick={() => setMode("live")}>Live</button>
        <button className={`btn small ${mode === "tutorial" ? "" : "secondary"}`} aria-pressed={mode === "tutorial"} onClick={() => setMode("tutorial")}>Tutorial</button>
      </div>
      {mode === "tutorial" ? <TutorialMode onUseTranscript={(t) => { setTranscript(t); setMode("photo"); }} /> : mode === "live" ? <LiveMode captureId={capId} onTranscript={(t) => setTranscript(t)} onEvidenceSaved={(id) => { setPhotoEvId(id); setMode("photo"); say("Live frame saved as photo evidence — run SAM or generate the draft in Photo mode.", "ok"); }} /> : (<>
      <ol className="steps-indicator" aria-label="Capture progress">
        <li className={capId ? "done" : "now"}>1 · Session</li>
        <li className={photoEvId ? "done" : capId ? "now" : ""}>2 · Evidence</li>
        <li className={capId ? "" : ""}>3 · Draft for review</li>
      </ol>
      <p className="muted">Your form is saved on this device as you type. Sessions save on the server before any AI request, so a dropped connection loses nothing.</p>
      <label htmlFor="cap-title">Session title</label><input id="cap-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="cap-asset">Training asset</label><input id="cap-asset" value={assetName} onChange={(e) => setAssetName(e.target.value)} />
      <label htmlFor="cap-desc">Task description</label><textarea id="cap-desc" rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn" onClick={create} disabled={!!capId || busy}>{capId ? "Session created" : busy ? "Creating…" : "1 · Create capture session"}</button>
        <button className="btn secondary" onClick={openCamera}>{cameraOpen ? "Close camera" : camState === "blocked" ? "Retry camera" : "Use camera"}</button>
        <label className="btn secondary">Attach photo<input className="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" aria-label="Attach photo" onChange={(e) => onPhoto(e.target.files?.[0])} /></label>
      </div>
      <LiveTranscribe captureId={capId} disabled={!capId}
        onFinal={(text) => setTranscript(text)}
        onObjectPhrase={(phrase) => segmentPhrase(phrase)} />
      {!capId && <p className="muted small-text">Create the session first to enable recording and photo upload. Typing the transcript works at any time and is saved on this device.</p>}
      <p className="muted">Camera: {camState === "ready" ? "available" : camState === "blocked" ? "blocked/unavailable — details below" : "not tested yet (click Use camera)"}. Media needs http://localhost or HTTPS and browser permission. Say <strong>“this is my flag”</strong> while recording and the flag will be segmented.</p>
      {cameraOpen && (
        <div style={{ marginTop: 12 }}>
          <video ref={videoRef} className="camera-preview" autoPlay playsInline muted aria-label="Camera preview" />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" onClick={capturePhoto}>Capture photo</button>
            <button className="btn secondary" onClick={stopCamera}>Cancel</button>
          </div>
        </div>
      )}
      {photoUrl && !seg && (
        <div style={{ marginTop: 12 }}>
          <p className="muted">Photo evidence preview — run SAM segmentation to overlay a highlight on this photo.</p>
          <img className="thumb" src={photoUrl} alt="Captured evidence" />
        </div>
      )}
      <label htmlFor="cap-transcript">Transcript — correct any errors (original AI output is kept separately)</label>
      <textarea id="cap-transcript" rows={5} value={transcript} onChange={(e) => setTranscript(e.target.value)} />
      {detectedPhrase && (
        <div className="notice info" role="status">
          Heard in narration: <strong>“{detectedPhrase}”</strong>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn small" onClick={() => segmentPhrase(detectedPhrase)} disabled={!photoEvId}>Segment “{detectedPhrase}”</button>
            <button className="btn small secondary" onClick={() => setSegPrompt(detectedPhrase)}>Use as prompt only</button>
            <button className="btn small secondary" onClick={() => { dismissedPhraseRef.current = detectedPhrase; setDetectedPhrase(null); }}>Dismiss</button>
          </div>
          {!photoEvId && <p className="muted small-text" style={{ marginTop: 6 }}>Attach or capture a photo first, then segment it.</p>}
        </div>
      )}
      <label htmlFor="seg-prompt">SAM segmentation prompt</label>
      <input id="seg-prompt" value={segPrompt} onChange={(e) => setSegPrompt(e.target.value)} placeholder="e.g. blue adjustment knob" />
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn secondary" onClick={() => void saveTranscript()} disabled={!capId || busy}>2 · Save corrected transcript</button>
        <button className="btn secondary" onClick={() => void runSegment()} disabled={!photoEvId || busy}>Highlight with SAM 3.1</button>
        <button className="btn" onClick={generate} disabled={!capId || busy}>{busy ? "Working…" : "3 · Generate procedure draft"}</button>
      </div>
      {seg && <SegmentOverlay geometry={seg.geometry} simulated={seg.simulated} imageUrl={photoUrl} onConfirm={confirmSegment} />}
      {seg?.status === "no_match" && (
        <div className="notice warn" role="status">
          <strong>SAM 3.1 found no match.</strong>{segAttempts.length > 0 && <> Tried: {segAttempts.map((t) => `“${t}”`).join(", ")}.</>} The object may be small, blurry, partly hidden, or named differently than SAM expects. Try, in order:
          <ol style={{ margin: "8px 0" }}>
            <li>Ask Spark to name what's actually visible, then tap a suggestion.</li>
            <li>Tap the object directly on the photo — a point prompt usually succeeds where words fail.</li>
            <li>Retake the photo closer, in better light, with the object centered.</li>
          </ol>
          <div className="row">
            <button className="btn small" onClick={() => void suggestObjects()}>Suggest objects with Muse Spark</button>
            {suggestions.map((s) => <button key={s} className="btn small secondary" onClick={() => { setSegPrompt(s); void runSegment(s); }}>{s}</button>)}
          </div>
          {photoUrl && (
            <div style={{ marginTop: 10 }}>
              <p className="muted small-text">Tap the object on the photo:</p>
              <div className="overlay-wrap" role="button" aria-label="Photo. Tap the object to segment it."
                onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setRecoveryTap({ nx: (e.clientX - r.left) / r.width, ny: (e.clientY - r.top) / r.height }); }}>
                <img src={photoUrl} alt="Evidence for tap segmentation" />
                {recoveryTap && <div className="tap-dot" style={{ left: `${recoveryTap.nx * 100}%`, top: `${recoveryTap.ny * 100}%` }} aria-hidden="true" />}
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn small" disabled={!recoveryTap} onClick={() => recoveryTap && void runSegment(segPrompt, recoveryTap)}>Segment tapped point</button>
                {recoveryTap && <span className="muted small-text">Tap at ({Math.round(recoveryTap.nx * 100)}%, {Math.round(recoveryTap.ny * 100)}%)</span>}
              </div>
            </div>
          )}
        </div>
      )}
      {status && <div className={`notice ${statusKind === "error" ? "error" : statusKind === "ok" ? "ok" : "warn"}`} role={statusKind === "error" ? "alert" : "status"}>{status}</div>}
      </>)}
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

function ReviewView({ version, setVersion, procs, openVersion, role, reload, notify }: { version: Version | null; setVersion: (v: Version | null) => void; procs: ProcSummary[]; openVersion: (id: string) => Promise<Version | null>; role: Role; reload: () => void; notify: (s: string, kind?: "ok" | "error" | "info") => void }) {
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const queue = procs.flatMap((p) => p.versions.filter((v) => v.status === "pending_review" || v.status === "draft" || v.status === "rejected").map((v) => ({ ...v, title: p.title })));
  const canReview = role === "reviewer" || role === "expert";
  async function act(path: string, ok: string) {
    if (!version) return;
    if (path === "reject" && !comment.trim()) { notify("Add a rejection reason first so the author knows what to fix.", "error"); return; }
    if (path === "approve" && !window.confirm("Approve this version? It becomes immutable and available for jobs.")) return;
    setBusy(true);
    try { await api.post(`/api/procedure-versions/${version.id}/${path}`, { comment: comment || "Reviewed in FieldGuard" }); notify(ok); setComment(""); reload(); const v = await openVersion(version.id); setVersion(v); }
    catch (e) { notify(e instanceof Error ? e.message : "Action failed", "error"); }
    setBusy(false);
  }
  async function saveEdits() {
    if (!version) return; setBusy(true);
    try { const v = await api.put<Version>(`/api/procedure-versions/${version.id}`, { summary: version.summary, prerequisites: version.prerequisites, steps: version.steps }); setVersion(v); notify("Draft edits saved. Approved versions are never edited in place."); }
    catch (e) { notify(e instanceof Error ? e.message : "Save failed", "error"); }
    setBusy(false);
  }
  return (
    <div>
      <div className="card"><h2>Review &amp; approvals</h2>
        <p className="muted">AI drafts are never approved automatically. {canReview ? "You can approve or reject versions pending review." : "Switch the demo role to Reviewer (top bar) to approve or reject — the server enforces this."} Signed-in role: <strong>{role}</strong>.</p>
        <div className="row">{queue.map((v) => <button key={v.id} className="btn small secondary" onClick={async () => { const ver = await openVersion(v.id); if (ver) setVersion(ver); else notify("That version is not available offline yet.", "error"); }}>{v.title} · v{v.version_number} · {v.status}</button>)}
        {queue.length === 0 && <span className="muted">Queue empty — generate a draft in Capture.</span>}</div>
      </div>
      {version && (
        <div className="card">
          <h3>{version.steps.length ? "Procedure draft" : "Procedure"} · v{version.version_number} <span className={`tag ${version.status === "approved" ? "approved" : "warn"}`}>{version.status}</span>
            {version.ai_simulated ? <span className="tag ai">AI draft · simulated model (no Meta key)</span> : version.ai_model ? <span className="tag ai">AI draft · {version.ai_model}</span> : <span className="tag">Seeded demo data</span>}</h3>
          <label htmlFor="rv-sum">Summary</label><input id="rv-sum" value={version.summary} disabled={version.status === "approved"} onChange={(e) => setVersion({ ...version, summary: e.target.value })} />
          <label htmlFor="rv-pre">Prerequisites</label><textarea id="rv-pre" rows={2} value={version.prerequisites} disabled={version.status === "approved"} onChange={(e) => setVersion({ ...version, prerequisites: e.target.value })} />
          {Array.isArray((version.source_evidence as { uncertainties?: string[] }).uncertainties) && <div className="notice warn"><strong>Uncertainties to resolve:</strong> {((version.source_evidence as { uncertainties?: string[] }).uncertainties || []).join(" ")}</div>}
          {version.steps.map((s, i) => (
            <div key={s.id} className="card">
              <strong>Step {s.step_order}: {s.title}</strong>
              <label htmlFor={`st-${s.id}`}>Instruction</label>
              <textarea id={`st-${s.id}`} rows={2} value={s.instruction} disabled={version.status === "approved"} onChange={(e) => { const steps = [...version.steps]; steps[i] = { ...s, instruction: e.target.value }; setVersion({ ...version, steps }); }} />
              <p className="muted">Expected: {s.expected_result || "—"} · Evidence refs: {s.evidence_refs.length ? s.evidence_refs.join(", ") : "none linked"} {s.verification_notes ? `· Check: ${s.verification_notes}` : ""}</p>
            </div>
          ))}
          {version.status === "pending_review" && (<>
            <label htmlFor="rv-comment">Review comment (required to reject)</label>
            <input id="rv-comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What did you verify, or what must change?" />
          </>)}
          <div className="row">
            {(version.status === "draft" || version.status === "rejected") && <><button className="btn secondary" disabled={busy} onClick={saveEdits}>Save edits</button><button className="btn" disabled={busy} onClick={() => act("submit-review", version.status === "rejected" ? "Resubmitted for review." : "Submitted for review.")}>{version.status === "rejected" ? "Submit again for review" : "Submit for review"}</button></>}
            {version.status === "pending_review" && (canReview
              ? <><button className="btn" disabled={busy} onClick={() => act("approve", "Approved. This version is now immutable and available to technicians.")}>Approve</button><button className="btn danger" disabled={busy} onClick={() => act("reject", "Rejected and returned with an audit record.")}>Reject</button></>
              : <span className="tag warn">Reviewer role required to approve or reject</span>)}
            {version.status === "approved" && <button className="btn secondary" disabled={busy} onClick={async () => { setBusy(true); try { const v = await api.post<Version>(`/api/procedure-versions/${version.id}/new-revision`, {}); setVersion(v); notify("New draft revision created. The approved version is unchanged."); } catch (e) { notify(e instanceof Error ? e.message : "Could not create a revision", "error"); } finally { setBusy(false); } }}>Propose new revision</button>}
          </div>
          {version.reviewed_by && <p className="muted">Reviewed by {version.reviewed_by}: {version.review_comment || ""}</p>}
        </div>
      )}
    </div>
  );
}

function JobView({ job, version, queueEvent, setJob, notify, reload, go }: { job: LocalJob | null; version: Version | null; queueEvent: (e: Omit<JobEventRec, "sync_status">) => Promise<void>; setJob: (j: LocalJob | null) => Promise<void>; notify: (s: string, kind?: "ok" | "error" | "info") => void; reload: () => void; go: (v: View) => void }) {
  const [issueType, setIssueType] = useState(ISSUE_TYPES[0]);
  const [note, setNote] = useState("");
  const [askQ, setAskQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [confirmFinish, setConfirmFinish] = useState(false);
  if (!job || !version) return <div className="card"><div className="empty"><h3>No active job</h3><p>Start one from an approved procedure. Downloaded procedures open here even in airplane mode.</p><button className="btn" onClick={() => go("library")}>Open procedure library</button></div></div>;
  const steps = [...version.steps].sort((a, b) => a.step_order - b.step_order);
  if (steps.length === 0) return <div className="card"><div className="empty"><h3>No steps in this version</h3><p>This procedure version has no steps, so a guided job cannot run. Ask a reviewer to create a revision with steps.</p><button className="btn" onClick={() => go("library")}>Open procedure library</button></div></div>;
  const step = steps[Math.min(job.current, steps.length - 1)];
  const doneCount = steps.filter((s) => job.stepStates[s.id] === "done").length;

  async function mark(state: "done" | "skipped" | "blocked") {
    if (!job || !step) return;
    if (job.stepStates[step.id] === state) { notify("Already recorded — no duplicate event created."); return; }
    await queueEvent({ event_id: uuid(), session_id: job.id, step_id: step.id, event_type: state === "done" ? "step_completed" : state === "skipped" ? "step_skipped" : "step_blocked", payload: { step_order: step.step_order }, occurred_at: new Date().toISOString() });
    const next = { ...job, stepStates: { ...job.stepStates, [step.id]: state }, current: Math.min(job.current + 1, steps.length - 1) };
    await setJob(next); notify(state === "done" ? "Step completed and saved on this device." : `Step marked ${state} and saved on this device.`);
  }
  async function recordIssue() {
    if (!job || !step) return;
    await queueEvent({ event_id: uuid(), session_id: job.id, step_id: step.id, event_type: "issue_recorded", payload: { issue_type: issueType, note }, occurred_at: new Date().toISOString() });
    setNote(""); notify("Issue recorded locally. It syncs when connectivity returns — nothing is lost offline.");
  }
  async function finish() {
    if (!job) return;
    await queueEvent({ event_id: uuid(), session_id: job.id, step_id: null, event_type: "job_finished", payload: { outcome: doneCount === steps.length ? "completed" : "finished-with-exceptions" }, occurred_at: new Date().toISOString() });
    try { await api.post(`/api/jobs/${job.id}/finish`, { outcome: doneCount === steps.length ? "completed" : "finished-with-exceptions", reason: "", summary: "" }); } catch { /* queued event carries the record offline */ }
    await setJob({ ...job, finished: true }); await idb.del("jobs", "active"); reload();
    notify("Job finished. Events remain queued until you press Sync now."); go("history");
  }
  async function ask() {
    if (!version) return;
    try { const r = await api.post<{ answer: string }>("/api/ask", { question: askQ, procedure_version_id: version.id }); setAnswer(r.answer); }
    catch { setAnswer("AI assistance is unavailable offline. The approved steps and cached manual text above remain fully usable."); }
  }
  return (
    <div>
      <div className="card" aria-live="polite">
        <p className="step-count">Step {step.step_order} of {steps.length} · {job.title} · v{version.version_number}</p>
        <div className="progress" role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={steps.length} aria-label={`${doneCount} of ${steps.length} steps complete`}><div style={{ width: `${(doneCount / steps.length) * 100}%` }} /></div>
        <h2 className="step-hero">{step.title}</h2>
        <p className="step-hero" style={{ fontSize: "1.1rem" }}>{step.instruction}</p>
        {step.required_tools.length > 0 && <p><strong>Tools:</strong> {step.required_tools.join(", ")}</p>}
        <p><strong>Expected result:</strong> {step.expected_result || "Confirm visually before continuing."}</p>
        <p><span className="tag approved">Human-approved instruction</span>{step.evidence_refs.length > 0 && <span className="tag">Evidence: {step.evidence_refs.length} ref(s)</span>}{job.stepStates[step.id] && <span className="tag warn">Status: {job.stepStates[step.id]}</span>}</p>
        <div className="big-actions">
          <button className="btn" onClick={() => mark("done")}>Mark complete</button>
          <button className="btn secondary" onClick={() => mark("blocked")}>Mark blocked</button>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn secondary" disabled={job.current === 0} onClick={() => setJob({ ...job, current: job.current - 1 })}>Previous</button>
          <button className="btn secondary" disabled={job.current >= steps.length - 1} onClick={() => setJob({ ...job, current: job.current + 1 })}>Next</button>
          <button className="btn secondary" onClick={() => mark("skipped")}>Skip step</button>
          {!confirmFinish
            ? <button className="btn danger" onClick={() => setConfirmFinish(true)}>Finish job</button>
            : <><span><strong>Finish with {doneCount}/{steps.length} steps complete?</strong></span><button className="btn danger" onClick={finish}>Confirm finish</button><button className="btn secondary" onClick={() => setConfirmFinish(false)}>Keep working</button></>}
        </div>
      </div>
      <div className="card">
        <h3>Record an issue on this step</h3>
        <label htmlFor="issue-type">Issue type</label>
        <select id="issue-type" value={issueType} onChange={(e) => setIssueType(e.target.value)}>{ISSUE_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
        <label htmlFor="issue-note">Note</label><textarea id="issue-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you observe?" />
        <button className="btn" style={{ marginTop: 10 }} onClick={recordIssue}>Record issue</button>
        <p className="muted">If a step is blocked on anything hazardous, stop work and follow your site procedure — this app never instructs you to bypass safety steps. (Demo uses a harmless training assembly.)</p>
      </div>
      <div className="card">
        <h3>Ask about this procedure</h3>
        <label htmlFor="ask-q">Question</label><input id="ask-q" value={askQ} onChange={(e) => setAskQ(e.target.value)} placeholder="e.g. knob" />
        <button className="btn secondary" style={{ marginTop: 10 }} onClick={ask}>Search approved steps &amp; manuals</button>
        {answer && <div className="notice ok" role="status">{answer}</div>}
      </div>
    </div>
  );
}

function History({ jobs, reload }: { jobs: JobRow[]; reload: () => void }) {
  return <div className="card"><h2>Job history</h2><button className="btn small secondary" onClick={reload}>Refresh</button>
    {jobs.length === 0 ? <div className="empty">No jobs yet. Completed work, exceptions, and sync state will appear here.</div>
      : jobs.map((j) => <p key={j.id}><strong>{j.procedure_title}</strong> — {j.status}{j.outcome ? ` · ${j.outcome}` : ""} · {j.events} event(s) · {new Date(j.started_at).toLocaleString()}</p>)}
    <p className="muted">Event history is append-only. Corrections create new audit events; approved versions are never rewritten by sync.</p></div>;
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
  return <div className="card"><h2>Manuals</h2>
    <p className="muted">Imported manuals are indexed on the server for search. They are not downloaded for offline use in this build — offline work uses downloaded approved procedures.</p>
    <label className="btn secondary">Import PDF manual (max 15 MB)<input className="visually-hidden" type="file" accept="application/pdf" aria-label="Import PDF manual" onChange={(e) => upload(e.target.files?.[0])} /></label>
    {manuals.length === 0 ? <div className="empty">No manuals imported. Import a PDF you are authorized to use.</div> : manuals.map((m) => <p key={m.id}><strong>{m.title}</strong> <span className="muted">{m.model || ""} · {m.chunks} chunk(s) indexed</span></p>)}
    <label htmlFor="man-q">Search manual text (shows source manual + page)</label><input id="man-q" value={q} onChange={(e) => setQ(e.target.value)} />
    <button className="btn" style={{ marginTop: 10 }} onClick={search}>Search manuals</button>
    {hits.map((h, i) => <div key={i} className="notice ok"><strong>{h.manual_title}</strong>{h.page_number ? ` · page ${h.page_number}` : ""}<br />{h.snippet}</div>)}
  </div>;
}

function Settings({ pending, role, clearCache }: { pending: number; role: Role; clearCache: () => void }) {
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
  return <div className="card"><h2>Settings</h2>
    <h3>Demo data</h3><p className="muted">Harmless Benchtop Cable Trainer scenario. Seeding is idempotent.</p>
    <button className="btn" onClick={seed}>Seed demo procedure</button>{note && <div className="notice ok" role="status">{note}</div>}
    <h3>Offline storage</h3><p>{pending} event(s) pending synchronization. Queued events and the active job survive reloads and airplane mode.</p>
    <button className="btn secondary" onClick={clearCache}>Clear downloaded procedure cache</button>
    <h3>Identity (demo)</h3><p className="muted">Signed in as the <strong>{role}</strong> demo role (top bar). This build uses header-based demo identity — the server still enforces reviewer-only approval, but it is not production authentication.</p>
    <h3>Privacy</h3><p className="muted">The Meta API key lives only on the backend and never reaches this browser. Recordings are sent for transcription only when connected and only after you press Record. Delete local data any time by clearing site storage; server records follow your team retention policy.</p>
    <h3>Diagnostics</h3><p className="muted">Check the real API, database, and AI status. No secrets are shown.</p>
    <button className="btn secondary" onClick={checkHealth}>Check connection</button>{health && <div className="notice info" role="status">{health}</div>}
  </div>;
}


