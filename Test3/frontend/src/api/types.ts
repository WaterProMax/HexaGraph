/**
 * Contract types (contracts C.4). Field names match the backend exactly; do not
 * invent parallel shapes. Secret values never appear here — `secret_ref` is an
 * environment-variable name only.
 */

export type GrantStatus = "active" | "stale" | "revoked" | "consumed";

export type BotSkillBinding = {
  skill_id: string;
  pinned_version: string;
};

export type BotInstance = {
  bot_id: string;
  display_name: string;
  role_template: string;
  provider_ref: string;
  model: string;
  slot: string;
  secret_ref: string;
  tool_policy: string[];
  skill_bindings: BotSkillBinding[];
  token_budget: number | null;
  status: "active" | "archived";
  /** Read-only: a provider key is stored server-side (the key itself is never returned). */
  has_api_key?: boolean;
};

export type BotCreate = {
  display_name: string;
  role_template: string;
  provider_ref: string;
  model: string;
  slot: string;
  secret_ref: string;
  tool_policy?: string[];
  skill_bindings?: BotSkillBinding[];
  token_budget?: number | null;
  /** Write-only provider key; the server stores it encrypted and never returns it. */
  api_key?: string;
};

export type BotPatch = {
  display_name?: string;
  provider_ref?: string;
  model?: string;
  slot?: string;
  secret_ref?: string;
  tool_policy?: string[];
  skill_bindings?: BotSkillBinding[];
  token_budget?: number | null;
  /** Write-only; omit to keep the stored key, empty string removes it. */
  api_key?: string;
};

export type SkillDefinition = {
  skill_id: string;
  version: string;
  description_md: string;
  allowed_tool_refs: string[];
};

export type ExecutionGrant = {
  grant_id: string;
  run_id: string;
  execution_profile: "granted_v1";
  task_codes: string[];
  approved_baseline_hashes: Record<string, string>;
  repo_remote: string;
  repo_owner: string;
  repo_name: string;
  base_branch: string;
  feature_branch: string;
  allowed_tool_refs: string[];
  status: GrantStatus;
  github_pr_url: string | null;
  created_at: string;
};

export type ExecutionProfile = {
  run_id: string;
  execution_profile: string;
  approved_baseline_hashes: Record<string, string>;
  execution_safety_ready: boolean;
};

export type ReviewBallot = {
  reviewer_bot_id: string;
  proposal_id: string;
  scores: Record<string, number>;
  score_justification: Record<string, string>;
  hard_gate_results: Record<string, boolean>;
  dissent_items: string[];
};

export type DecisionPackage = {
  decision_id: string;
  session_id: string;
  requirement_snapshot_hash: string;
  proposal_ids: string[];
  dissent_items: string[];
  hard_gate_summary: Record<string, boolean>;
  body_md: string;
  sha256: string;
};

export type DiscussionSession = {
  session_id: string;
  project_id: string;
  leader_bot_id: string;
  participant_bot_ids: string[];
  status: string;
  current_round: number;
  budget: { max_rounds: number; max_tokens: number | null; max_wallclock_seconds: number | null };
  requirement_snapshot_hash: string;
  decision_package: DecisionPackage | null;
};

export type ModuleAcceptance = {
  acceptance_id: string;
  run_id: string;
  module_id: string;
  task_codes: string[];
  status: "pending" | "accepted" | "rejected";
  evidence_uris: string[];
  reviewer: string;
  comment: string;
};

export type DefectRecord = {
  defect_id: string;
  run_id: string;
  task_code: string;
  module_id: string;
  related_requirement_id: string | null;
  evidence_uris: string[];
  status: "open" | "reopened" | "resolved";
  detail: string;
};

/** P2–P5 error body: `{"error_category", "detail"}`. */
export type ErrorBody = {
  error_category?: string;
  detail?: string;
};

/** Mirrors `GET /api/runs/{run_id}/tasks` elements (state enum, not `succeeded`). */
export type RunTask = {
  code: string;
  state: string;
  card?: { title?: string; depends_on?: string[]; [key: string]: unknown };
  evidence?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};
/** Memory (C.4 / C.5.5). Bodies never contain secret plaintext. */
export type MemorySource = { kind: string; ref: string; sha: string };

export type MemoryVisibility = "private" | "project" | "run";
export type MemoryStatus = "pending" | "published" | "superseded";

export type MemoryRecord = {
  mem_id: string;
  owner_bot_id: string;
  project_id: string | null;
  visibility: MemoryVisibility;
  version: number;
  status: MemoryStatus;
  sources: MemorySource[];
  body: Record<string, unknown>;
  title: string;
  run_id: string | null;
  promoted_by?: string | null;
  promoted_at?: string | null;
};

export type MemoryCreate = {
  owner_bot_id: string;
  project_id?: string | null;
  visibility: MemoryVisibility;
  sources: MemorySource[];
  body: Record<string, unknown>;
  title?: string;
  run_id?: string | null;
};

export type ProjectMembership = {
  project_id: string;
  bot_id: string;
  role_in_project: string;
  is_leader: boolean;
};

export type MembershipCreate = {
  bot_id: string;
  role_in_project: string;
  is_leader?: boolean;
};

/** One turn of a bot chat; the history lives in the browser. */
export type ChatMessage = { role: "user" | "assistant"; content: string };

/** Reply of `POST /bots/{id}/chat`; `files_omitted` appears when library files did not fit. */
export type ChatReply = { reply: string; model: string; files_omitted?: number };

/** A text file in a bot's library (the content stays on the server). */
export type BotFile = { file_id: string; filename: string; chars: number; created_at: string };

export type BotFileLibrary = { items: BotFile[]; used_chars: number; budget_chars: number };
