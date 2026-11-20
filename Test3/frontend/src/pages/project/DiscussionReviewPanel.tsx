import type { ReviewBallot } from "../../api/types";

export type DiscussionReviewPanelProps = { ballots: ReviewBallot[]; dissentItems: string[] };

const GATE_LABELS: Record<string, string> = {
  coverage: "覆盖",
  conflicts_closed_or_recorded: "冲突已关闭或记录",
  evidence_complete: "证据完整",
};

export function DiscussionReviewPanel({ ballots, dissentItems }: DiscussionReviewPanelProps) {
  return (
    <div className="surface review-panel" data-testid="discussion-review-panel" style={{ padding: 16 }}>
      <div className="section-title">
        <span>讨论互评</span>
        <span className="hint">结论只由硬门槛、异议与轮次决定；分数仅作记录</span>
      </div>

      {ballots.length === 0 && <p className="muted">还没有评审票。</p>}
      {ballots.map((ballot) => (
        <div className="review-ballot" key={`${ballot.reviewer_bot_id}-${ballot.proposal_id}`}>
          <div className="mono">
            {ballot.reviewer_bot_id} → {ballot.proposal_id}
          </div>
          <ul className="review-gates">
            {Object.entries(ballot.hard_gate_results).map(([gate, passed]) => (
              <li key={gate} className={passed ? "gate-pass" : "gate-fail"}>
                <span>{GATE_LABELS[gate] || gate}</span>
                <span>{passed ? "通过" : "未通过"}</span>
              </li>
            ))}
          </ul>
          {Object.keys(ballot.score_justification).length > 0 && (
            <ul className="review-justification">
              {Object.entries(ballot.score_justification).map(([dimension, reason]) => (
                <li key={dimension}>
                  <span className="mono">{dimension}</span>：{reason}
                </li>
              ))}
            </ul>
          )}
          {ballot.dissent_items.length > 0 && (
            <div className="review-dissent">评审异议：{ballot.dissent_items.join("；")}</div>
          )}
        </div>
      ))}

      <div className="section-title" style={{ marginTop: 14 }}>
        <span>保留异议</span>
        <span className="hint mono">{dissentItems.length}</span>
      </div>
      {dissentItems.length === 0 ? (
        <p className="muted">当前没有保留异议。</p>
      ) : (
        <ul className="dissent-list">
          {dissentItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default DiscussionReviewPanel;