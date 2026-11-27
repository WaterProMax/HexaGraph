import type { DiscussionSession } from "../../../api/types";

export type DiscussionStage =
  | "idea"
  | "independent"
  | "revise"
  | "review"
  | "leader"
  | "approval"
  | "design"
  | "approved"
  | "terminated";

/**
 * Maps a session status to the workflow stage shown by the UI.
 *
 * `rejected` falls back to `idea` because the page immediately creates a new
 * session after a rejection; the old session is only kept for its timeline.
 *
 * An approved SPEC enters the design stage (第 5 步) first; only after the
 * DESIGN baseline is approved does the UI move on to task splitting (第 6 步).
 * Sessions without a workflow projection (older payloads/tests) keep the
 * legacy approved → task-split mapping.
 */
export function deriveStage(session: DiscussionSession | null): DiscussionStage {
  if (!session) return "idea";
  switch (session.status) {
    case "draft":
      return "idea";
    case "grouping":
    case "round1_independent":
      return "independent";
    case "cross_review":
      return "review";
    case "round_n_revise":
      return "revise";
    case "converged_pending_human":
      return session.decision_package ? "approval" : "leader";
    case "approved":
      return session.workflow && session.workflow.design_approved === false ? "design" : "approved";
    case "terminated":
    case "budget_exhausted":
      return "terminated";
    case "rejected":
      return "idea";
    default:
      return "idea";
  }
}

export type DiscussionControlFlags = {
  /** Only the session's leader may use the write controls. */
  canControl: boolean;
  /** A finished discussion never offers recoverable controls again. */
  terminal: boolean;
  /** A manual end marker exists; it is not proof that the safe stop finished. */
  manual: boolean;
  /** Manual end + converged + safely paused + no decision package + revision. */
  settledManual: boolean;
  /** The next round fits in the known round budget. */
  roundsAvailable: boolean;
  manualPending: boolean;
  budgetExhausted: boolean;
};

const TERMINAL_STATUSES = new Set(["terminated", "budget_exhausted", "approved", "rejected"]);

/**
 * Single derivation for the discussion button matrix. It deliberately keeps
 * `settledManual` separate from a bare `manual` marker: `round_end_reason.kind
 * === "manual"` can arrive before the backend finished the safe stop, and
 * `rounds/start` would then fail with `manual_end_not_finalized`.
 */
export function discussionControlFlags(
  session: DiscussionSession | null,
  actorBotId = "",
): DiscussionControlFlags {
  if (!session) {
    return {
      canControl: false,
      terminal: false,
      manual: false,
      settledManual: false,
      roundsAvailable: false,
      manualPending: false,
      budgetExhausted: false,
    };
  }
  const terminal = TERMINAL_STATUSES.has(session.status);
  const manual = session.round_end_reason?.kind === "manual";
  const settledManual =
    manual &&
    session.status === "converged_pending_human" &&
    session.paused &&
    !session.pause_requested &&
    !session.decision_package;
  const roundsAvailable = session.current_round < session.budget.max_rounds;
  return {
    canControl: Boolean(actorBotId) && session.leader_bot_id === actorBotId,
    terminal,
    manual,
    settledManual,
    roundsAvailable,
    manualPending: manual && !settledManual && !terminal,
    budgetExhausted: session.status === "budget_exhausted",
  };
}