export interface Gate {
  id: string;
  kind: string;
  status: string;
  payload: { missing?: string[]; errors?: string[]; pass?: boolean };
}

export interface Run {
  id: string;
  project_id: string;
  idea: string;
  stage: string;
  status: string;
  revision: number;
  paused: boolean;
  gates: Gate[];
  provenance?: { mode?: string; generation?: string; generation_label?: string; execution_label?: string };
}

export interface TaskCard {
  code: string;
  title: string;
  description: string;
  points: number;
  depends_on: string[];
  write_set: string[];
  outputs: string[];
  acceptance: { cmd: string[] }[];
}

export interface RuntimeTask {
  id: string;
  code: string;
  state: string;
  revision: number;
  card: TaskCard;
  last_error?: string;
  evidence?: { cmd?: string[]; exit_code?: number; output?: string }[];
}

export interface Proposal {
  elevator: string;
  implementation: string;
  estimate_total: number;
  features: { name: string; points: number }[];
  risks: { code: string; verification: string; fallback: string }[];
}

export interface Artifacts {
  steward_error?: string;
  idea_card?: { approach: string; features: string[] };
  issues?: { code: string; text: string; status: string; conclusion: string }[];
  utterances?: { seq: number; role: string; body: string }[];
  steward_comparison?: { candidates: { id: string; focus: string; proposal: Proposal }[]; errors: string[] };
  proposal?: Proposal;
  reviews?: { reviewer: string; dimension: string; score: number; opinions: { text: string; blocking: boolean }[] }[];
  spec?: { features: { code: string; title: string; acceptance: string[] }[] };
  design?: { modules: { code: string; name: string; responsibility: string }[] };
  plan?: { tasks: TaskCard[]; capacity: number };
  plan_errors?: string[];
  baseline_PLAN?: string;
  acceptance?: { features: { code: string; result: string; reason?: string }[]; nonfunc: { code: string; result: string; reason?: string }[] };
  build_tag?: string;
  release_dir?: string;
}

export interface Schedule {
  rows: { code: string; start: number; end: number }[];
  span: number;
  concurrency: number;
  critical: string[];
}

export interface Experience {
  id: string;
  run_id: string;
  title: string;
  lesson: string;
  status: "candidate" | "published" | "rejected";
}

export type Perform = (action: () => Promise<unknown>) => void;
