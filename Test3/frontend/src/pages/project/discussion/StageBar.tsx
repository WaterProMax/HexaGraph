export type DiscussionStage =
  | "idea"
  | "independent"
  | "review"
  | "leader"
  | "approval"
  | "approved"
  | "terminated";

const STEPS = ["想法", "独立方案", "互评", "Leader 审核", "你的审批", "任务拆解"] as const;

const STAGE_STEP: Record<Exclude<DiscussionStage, "terminated">, number> = {
  idea: 0,
  independent: 1,
  review: 2,
  leader: 3,
  approval: 4,
  approved: 5,
};

export type StageBarProps = {
  stage: DiscussionStage;
};

/**
 * Discussion progress bar. `deriveStage` decides the stage; this component only
 * maps it to the six fixed steps and marks done / current / terminated.
 */
export function StageBar({ stage }: StageBarProps) {
  const terminated = stage === "terminated";
  const currentIndex = terminated ? -1 : STAGE_STEP[stage];
  const lastIndex = STEPS.length - 1;

  return (
    <div
      className={`disc-stage-bar${terminated ? " is-terminated" : ""}`}
      data-testid="disc-stage-bar"
      data-stage={stage}
    >
      <ol className="disc-stage-list" aria-label="讨论流程">
        {STEPS.map((label, index) => {
          const done = index < currentIndex;
          const current = index === currentIndex;
          const waiting = stage === "approved" && index === lastIndex;
          const state = done ? "done" : current ? "current" : "pending";
          return (
            <li
              key={label}
              className={`disc-stage-step is-${state}`}
              data-status={state}
              aria-current={current ? "step" : undefined}
              title={done ? `${label}（已完成）` : waiting ? `${label}（等待任务拆解）` : label}
            >
              <span className="disc-stage-mark" aria-hidden="true">
                {done ? "✓" : index + 1}
              </span>
              <span className="disc-stage-label">{label}</span>
              {waiting && <span className="disc-stage-note">等待任务拆解</span>}
            </li>
          );
        })}
      </ol>
      {terminated && (
        <p className="disc-stage-terminated" role="status">
          讨论已终止
        </p>
      )}
    </div>
  );
}

export default StageBar;