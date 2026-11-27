import type { DiscussionStage } from "./deriveStage";

export type { DiscussionStage };

const STEPS = ["想法", "独立方案", "互评", "Leader 审核", "你的审批", "设计规格", "任务拆解"] as const;

const STAGE_STEP: Record<Exclude<DiscussionStage, "terminated">, number> = {
  idea: 0,
  independent: 1,
  revise: 1,
  review: 2,
  leader: 3,
  approval: 4,
  design: 5,
  approved: 6,
};

export type StageBarProps = {
  stage: DiscussionStage;
  /** Current session round, used for the subtitle on the independent / revise / review steps. */
  round?: number;
  planReady?: boolean;
  planFailed?: boolean;
};

function stageSubtitle(stage: DiscussionStage, round: number): string | null {
  switch (stage) {
    case "independent":
      return `第 ${round} 轮 · 独立方案`;
    case "revise":
      return `第 ${round} 轮 · 修改方案`;
    case "review":
      return `第 ${round} 轮 · 互评`;
    default:
      return null;
  }
}

/**
 * Discussion progress bar. `deriveStage` decides the stage; this component only
 * maps it to the seven fixed steps and marks done / current / terminated.
 */
export function StageBar({ stage, round, planReady = false, planFailed = false }: StageBarProps) {
  const terminated = stage === "terminated";
  const currentIndex = terminated ? -1 : STAGE_STEP[stage];
  const lastIndex = STEPS.length - 1;
  const subtitle = stageSubtitle(stage, round ?? 1);

  return (
    <div
      className={`disc-stage-bar${terminated ? " is-terminated" : ""}`}
      data-testid="disc-stage-bar"
      data-stage={stage}
    >
      <h2 className="disc-stage-heading">讨论进度</h2>
      <ol className="disc-stage-list" aria-label="讨论流程">
        {STEPS.map((label, index) => {
          const lastStep = stage === "approved" && index === lastIndex;
          const done = index < currentIndex || (lastStep && planReady);
          const current = index === currentIndex && !done;
          const waiting = lastStep && !planReady;
          const state = done ? "done" : current ? "current" : "pending";
          return (
            <li
              key={label}
              className={`disc-stage-step is-${state}`}
              data-status={state}
              aria-current={current ? "step" : undefined}
              title={done ? `${label}（已完成）` : label}
            >
              <span className="disc-stage-mark" aria-hidden="true">
                {done ? "✓" : index + 1}
              </span>
              <span className="disc-stage-label">{label}</span>
              {current && subtitle && (
                <span className="disc-stage-subtitle" data-testid="disc-stage-subtitle">
                  {subtitle}
                </span>
              )}
              {waiting && <span className="disc-stage-note">{planFailed ? "生成失败，等待重试" : "生成任务与依赖"}</span>}
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
