export interface Step {
  id: string;
  step_order: number;
  title: string;
  instruction: string;
  expected_result?: string | null;
  required_tools: string[];
  evidence_refs: string[];
  visual_refs: string[];
  verification_notes?: string | null;
}

export interface Version {
  id: string;
  procedure_id: string;
  version_number: number;
  status: "draft" | "pending_review" | "approved" | "rejected" | "superseded";
  summary: string;
  prerequisites: string;
  source_evidence: Record<string, unknown>;
  ai_model?: string | null;
  ai_simulated?: boolean;
  created_by: string;
  reviewed_by?: string | null;
  review_comment?: string | null;
  steps: Step[];
}

export interface ProcSummary {
  id: string;
  title: string;
  favorite: boolean;
  updated_at?: string | null;
  asset_type?: string | null;
  versions: { id: string; version_number: number; status: string }[];
  approved_version_id: string | null;
  has_pending_review: boolean;
}

export interface JobEventRec {
  event_id: string;
  session_id: string;
  step_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  sync_status: "pending" | "synced";
}

export interface LocalJob {
  id: string;
  procedure_id: string;
  procedure_version_id: string;
  title: string;
  current: number; // 0-based step index
  stepStates: Record<string, "done" | "skipped" | "blocked">;
  started_at: string;
  finished: boolean;
  finish_outcome?: string;
}

export type View = "home" | "library" | "detail" | "capture" | "review" | "job" | "history" | "manuals" | "settings" | "activity";
export type Role = "technician" | "expert" | "reviewer";
