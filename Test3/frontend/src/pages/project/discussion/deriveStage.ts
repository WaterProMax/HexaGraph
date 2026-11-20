import type { DiscussionSession } from "../../../api/types";

export type DiscussionStage =
  | "idea"
  | "independent"
  | "review"
  | "leader"
  | "approval"
  | "approved"
  | "terminated";

/**
 * Maps a session status to the workflow stage shown by the UI.
 *
 * `rejected` falls back to `idea` because the page immediately creates a new
 * session after a rejection; the old session is only kept for its timeline.
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
    case "round_n_revise":
      return "review";
    case "converged_pending_human":
      return session.decision_package ? "approval" : "leader";
    case "approved":
      return "approved";
    case "terminated":
    case "budget_exhausted":
      return "terminated";
    case "rejected":
      return "idea";
    default:
      return "idea";
  }
}