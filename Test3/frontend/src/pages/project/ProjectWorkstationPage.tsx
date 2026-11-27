import { TeamOutlined, UserAddOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type {
  BotInstance,
  DefectRecord,
  DiscussionSession,
  GrantStatus,
  ReviewBallot,
  RunTask,
  TaskAssignment,
} from "../../api/types";
import type { LoadState } from "../../components/AppShell";
import { LEFT_PANEL_ID, WorkstationSplitter } from "../../components/WorkstationSplitter";
import { useRunEvents } from "../../hooks/useRunEvents";
import { mapTaskState } from "../../workstationGraph";
import { useWorkstationLayout } from "../../workstationLayout";
import { AgentEvaluationPanel } from "./AgentEvaluationPanel";
import { ApprovedSpecPanel, type ApprovedSpecStatus } from "./ApprovedSpecPanel";
import { DefectList } from "./DefectList";
import { DiscussionReviewPanel } from "./DiscussionReviewPanel";
import { DiscussionView } from "./discussion/DiscussionView";
import { GrantStatusBanner } from "./GrantStatusBanner";
import { InputConstraintsPanel, type TaskInputConstraints } from "./InputConstraintsPanel";
import { InviteBotsDialog } from "./InviteBotsDialog";
import { ManageMembersDialog } from "./ManageMembersDialog";
import { ProjectMemoryPanel } from "./ProjectMemoryPanel";
import { RequirementTracePanel } from "./RequirementTracePanel";
import { RunMonitorPanel } from "./RunMonitorPanel";
import { RunEventTimeline } from "./RunEventTimeline";
import { TaskDependencyGraph } from "./TaskDependencyGraph";
import { TaskAssignmentBoard } from "./TaskAssignmentBoard";
import { TeamStrip, type TeamMember } from "./TeamStrip";
import { isStaticProjectId, loadStaticSnapshot } from "../../static/staticProject";

export type WorkstationTab = "details" | "assignment" | "monitor" | "evaluation" | "activity" | "graph";

const EMPTY_SESSIONS: DiscussionSession[] = [];

/**
 * Task row shown on the project main path. Besides the progress summary it keeps
 * the persisted, read-only task-card inputs (role / depends_on / write_set /
 * acceptance / description / module / parent / points / budget) and the frozen
 * context state of the last attempt so 详情 and 任务图 show real input instead of
 * an in-memory note.
 */
export type WorkstationTask = TaskInputConstraints & {
  progress: number;
  /** Raw backend task state (e.g. running / done / ready); never re-encoded. */
  status: string;
  /** Task-level revision: the CAS source for control and assignment writes. */
  revision?: number;
  /** A1 dispatch overlay; null when unassigned. Execution stays role-scoped. */
  assignment?: TaskAssignment | null;
};

export type ProjectWorkstationProps = {
  projectId: string;
  /** Shown as the page title; falls back to a generic title until it loads. */
  projectName?: string;
  loadState: LoadState;
  tasks: WorkstationTask[];
  dirtyRef: { current: boolean };
  initialTab?: WorkstationTab;
  errorText?: string;
  runId?: string;
  grantErrorCategory?: string | null;
  grantStatus?: GrantStatus;
  ballots?: ReviewBallot[];
  dissentItems?: string[];
  defects?: DefectRecord[];
  team?: {
    members: TeamMember[];
    onInvite: () => void;
    onManage: () => void;
  };
  memoryPanel?: ReactNode;
  bots?: BotInstance[];
  /** Full discussion sessions for the read-only approved-spec panel. */
  sessions?: DiscussionSession[];
  /** The project discussion remains available alongside existing runs. */
  discussionPanel?: ReactNode;
  onShowDiscussion?: () => void;
  onShowTasks?: () => void;
  onRefresh?: () => void;
  /** Local actor header used by task-scoped memory panels. */
  actorBotId?: string;
  actorIsLeader?: boolean;
  /** Run status from the run view; done/terminated makes the dispatch board read-only. */
  runStatus?: string;
};

const TAB_LABELS: Array<{ key: WorkstationTab; label: string }> = [
  { key: "details", label: "详情" },
  { key: "assignment", label: "任务派发" },
  { key: "monitor", label: "执行监控" },
  { key: "evaluation", label: "Agent 评测" },
  { key: "activity", label: "活动" },
  { key: "graph", label: "任务图" },
];

export function progressForState(state: string): number {
  if (state === "done") return 100;
  if (state === "running" || state === "verifying") return 40;
  return 0;
}

/**
 * Map the backend task list without inventing states. Card/attempt fields are
 * copied only when the payload actually carries them, so a minimal task row
 * stays minimal instead of gaining misleading defaults.
 */
export function mapTasks(tasks: RunTask[]): WorkstationTask[] {
  return (Array.isArray(tasks) ? tasks : []).map((task) => {
    const card = (task.card || {}) as Record<string, unknown>;
    const attempt =
      task && typeof (task as Record<string, unknown>).attempt === "object" && (task as Record<string, unknown>).attempt
        ? ((task as Record<string, unknown>).attempt as Record<string, unknown>)
        : null;
    const mapped: WorkstationTask = {
      code: String(task.code),
      title: String(card.title || task.code),
      progress: progressForState(String(task.state)),
      status: String(task.state),
    };
    if (typeof task.revision === "number") mapped.revision = task.revision;
    if ("assignment" in task) {
      const assignment = (task as Record<string, unknown>).assignment;
      mapped.assignment =
        assignment && typeof assignment === "object" ? (assignment as TaskAssignment) : null;
    }
    if (Array.isArray(card.depends_on)) mapped.dependsOn = card.depends_on.map(String);
    if (typeof card.role === "string") mapped.role = card.role;
    if (Array.isArray(card.write_set)) mapped.writeSet = card.write_set.map(String);
    if (typeof card.description === "string") mapped.description = card.description;
    if (typeof card.module === "string") mapped.module = card.module;
    if (typeof card.parent === "string") mapped.parent = card.parent;
    if (typeof card.points === "number") mapped.points = card.points;
    if (Array.isArray(card.acceptance)) {
      mapped.acceptance = card.acceptance.map((item: any) => ({
        cmd: Array.isArray(item?.cmd) ? item.cmd.map(String) : item?.cmd != null ? String(item.cmd) : undefined,
        passCriteria: item?.pass_criteria != null ? String(item.pass_criteria) : undefined,
        fromCriterion: item?.from_criterion != null ? String(item.from_criterion) : undefined,
      }));
    }
    if (card.budget && typeof card.budget === "object") {
      const budget = card.budget as Record<string, unknown>;
      mapped.budget = {
        max_tool_steps: typeof budget.max_tool_steps === "number" ? budget.max_tool_steps : undefined,
        max_tokens: typeof budget.max_tokens === "number" ? budget.max_tokens : undefined,
        max_seconds: typeof budget.max_seconds === "number" ? budget.max_seconds : undefined,
      };
    }
    if (attempt) {
      if (typeof attempt.context_injected === "boolean") mapped.contextInjected = attempt.context_injected;
      if (typeof attempt.execution_path === "string") mapped.executionPath = attempt.execution_path;
      if (typeof attempt.skill_bundle_hash === "string") mapped.skillBundleHash = attempt.skill_bundle_hash;
    }
    return mapped;
  });
}

/** Full event timeline embedded in the 活动 tab (no 20-row cap; one event source). */
function ActivityTimeline({ runId }: { runId: string }) {
  const { events, connection, connectionError, reconnect } = useRunEvents(runId);
  const [taskFilter, setTaskFilter] = useState("");
  return (
    <div data-testid="activity-timeline">
      <RunEventTimeline
        events={events}
        connection={connection}
        connectionError={connectionError}
        reconnect={reconnect}
        taskFilter={taskFilter}
        onTaskFilterChange={setTaskFilter}
      />
    </div>
  );
}

export function ProjectWorkstation({
  projectId,
  projectName = "",
  loadState,
  tasks,
  dirtyRef,
  initialTab = "details",
  errorText = "",
  runId,
  grantErrorCategory = null,
  grantStatus,
  ballots = [],
  dissentItems = [],
  defects = [],
  team,
  memoryPanel,
  bots = [],
  sessions = EMPTY_SESSIONS,
  discussionPanel,
  onShowDiscussion,
  onShowTasks,
  onRefresh,
  actorBotId,
  actorIsLeader = false,
  runStatus = "",
}: ProjectWorkstationProps) {
  const layout = useWorkstationLayout();
  const [specStatus, setSpecStatus] = useState<ApprovedSpecStatus | null>(null);
  const [highlight, setHighlight] = useState("");
  const highlightTimer = useRef<number | null>(null);
  useEffect(() => () => {
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
  }, []);
  const locateTask = (code: string) => {
    setSelected(code);
    setTab("details");
    setHighlight(code);
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => setHighlight(""), 1800);
  };
  const [tab, setTab] = useState<WorkstationTab>(initialTab);
  const [selected, setSelected] = useState<string>(tasks[0]?.code || "");
  const [note, setNote] = useState("");
  const [titleMenuOpen, setTitleMenuOpen] = useState(false);
  const titleMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!titleMenuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!titleMenuRef.current?.contains(event.target as Node)) setTitleMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTitleMenuOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [titleMenuOpen]);

  useEffect(() => {
    if (!tasks.some((task) => task.code === selected)) setSelected(tasks[0]?.code || "");
  }, [tasks, selected]);

  const current = useMemo(() => tasks.find((task) => task.code === selected), [tasks, selected]);
  const leader = team?.members.find((member) => member.is_leader);
  const memberNames = (team?.members || []).map((member) => member.display_name).join("、");
  const specLabel =
    specStatus?.kind === "discussion"
      ? `已批准规格：第 ${specStatus.version} 次讨论`
      : specStatus?.kind === "artifact"
        ? `已批准规格：SPEC 工件${specStatus.baseline ? `（基线 v${specStatus.baseline}）` : ""}`
        : specStatus?.kind === "none"
          ? "尚未生成已批准规格"
          : "规格：读取中";
  const showFullSpec = () => {
    // The full body is already on screen; this only scrolls the read-only panel into view.
    const node = document.querySelector('[data-testid="approved-spec-panel"]') as HTMLElement | null;
    node?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  };
  // 详情 / 任务图 are full-width views: the 540-row task tree next to them was pure noise, so task
  // switching lives in the panel header instead (the tree stays on 活动 where it navigates).
  const soloWorkspace = tab === "details" || tab === "assignment" || tab === "monitor" || tab === "evaluation" || tab === "graph";

  if (loadState === "loading") {
    return (
      <div className="page ws-page">
        <div className="ws-page-bar">
          <div className="page-head">
            <h1>{projectName || "项目工作台"}</h1>
          </div>
        </div>
        <div className="ws-page-skeleton" data-testid="ws-loading" role="status">
          <div className="ws-skeleton-panel" />
          <div className="ws-skeleton-side" />
          <span className="ws-skeleton-label">正在加载项目工作台…</span>
        </div>
      </div>
    );
  }
  if (loadState === "error") {
    return (
      <div className="page">
        <div className="well" data-testid="ws-error" style={{ padding: "14px 16px" }}>
          工作台加载失败：{errorText || "未知错误"}
        </div>
      </div>
    );
  }
  if (loadState === "forbidden") {
    return (
      <div className="page">
        <div className="well" data-testid="ws-forbidden" style={{ padding: "14px 16px" }}>
          没有查看该项目工作台的权限（403）。
        </div>
      </div>
    );
  }

  return (
    <div className="page ws-page">
      <div className="ws-page-bar">
        <div className="page-head ws-title-menu" ref={titleMenuRef}>
          <h1 className="ws-title-heading">
            <button
              type="button"
              className="ws-title-trigger"
              aria-haspopup="menu"
              aria-expanded={titleMenuOpen}
              aria-label={`${projectName || "项目工作台"} 项目操作`}
              onClick={() => setTitleMenuOpen((open) => !open)}
            >
              {projectName || "项目工作台"}
            </button>
          </h1>
          {team && (
            <TeamStrip
              members={team.members}
              onInvite={team.onInvite}
              onManage={team.onManage}
              showActions={false}
            />
          )}
          {titleMenuOpen && team && (
            <div className="ws-title-actions" role="menu" aria-label="项目操作">
              <button
                type="button"
                role="menuitem"
                className="ws-title-action"
                onClick={() => {
                  setTitleMenuOpen(false);
                  team.onInvite();
                }}
              >
                <span className="ws-title-action-icon is-accent" aria-hidden="true">
                  <UserAddOutlined />
                </span>
                <span>邀请更多 Bot</span>
              </button>
              <button
                type="button"
                role="menuitem"
                className="ws-title-action"
                onClick={() => {
                  setTitleMenuOpen(false);
                  team.onManage();
                }}
              >
                <span className="ws-title-action-icon" aria-hidden="true">
                  <TeamOutlined />
                </span>
                <span>管理项目成员</span>
              </button>
            </div>
          )}
        </div>
        <div className="ws-page-bar-actions">
          {runId && onShowDiscussion && onShowTasks && (
            <nav className="disc-project-nav" aria-label="项目工作区">
              <button type="button" aria-pressed={Boolean(discussionPanel)} onClick={onShowDiscussion}>项目讨论</button>
              <button type="button" aria-pressed={!discussionPanel} onClick={onShowTasks}>开发任务</button>
            </nav>
          )}
        </div>
      </div>
      <GrantStatusBanner errorCategory={grantErrorCategory} status={grantStatus} />
      {!discussionPanel && tasks.length > 0 && (
        <div className="demo-context" data-testid="demo-context">
          <span className="demo-context-leader" data-testid="context-leader">
            Leader：{leader ? leader.display_name : "尚未设置"}
          </span>
          <span className="demo-context-members" data-testid="context-members">
            成员：{memberNames || "暂无成员"}
          </span>
          <span className="demo-context-spec" data-testid="context-spec">
            {specLabel}
          </span>
          {onShowDiscussion && (
            <button
              type="button"
              className="chip"
              data-testid="context-back-to-discussion"
              onClick={onShowDiscussion}
            >
              回到项目讨论
            </button>
          )}
        </div>
      )}
      {!discussionPanel && (loadState === "empty" || tasks.length === 0) ? (
        <div className="well muted" data-testid="ws-empty" style={{ padding: "14px 16px" }}>
          {runId ? (
            <>先完成项目讨论与规格确认；任务就绪后在这里划分并派发给项目成员。<Link to={`/workstation/${runId}`}>打开运行工作台（次入口）</Link></>
          ) : (
            "确认需求规格并完成设计规格确认后，Leader 会生成任务计划，随后可在「任务派发」把任务分给项目成员。"
          )}
        </div>
      ) : null}

      {discussionPanel && (
        <div className="ws-discussion" data-testid="ws-discussion">
          {discussionPanel}
        </div>
      )}

      {!discussionPanel && (
      <div className={`${layout.bodyClassName} ${soloWorkspace ? "ws-body-solo" : ""}`.trim()} style={layout.bodyStyle} ref={layout.bodyRef} data-testid="project-workstation">
        {!soloWorkspace && (
          <>
            <aside className="ws-left" id={LEFT_PANEL_ID} ref={layout.leftRef} tabIndex={-1} aria-label="任务树">
              <div className="section-title">
                <span>任务</span>
                <span className="hint mono">{tasks.length}</span>
              </div>
              <div className="task-tree" data-testid="task-tree" role="tree">
                {tasks.length === 0 && <div className="muted">没有任务</div>}
                {tasks.map((task) => (
                  <button
                    type="button"
                    key={task.code}
                    role="treeitem"
                    aria-selected={task.code === selected}
                    className={`task-tree-item ${task.code === selected ? "active" : ""} ${task.code === highlight ? "highlight" : ""}`}
                    onClick={() => {
                      locateTask(task.code);
                    }}
                  >
                    <span className="mono">{task.code}</span>
                    <span className="task-tree-title">{task.title}</span>
                    <span className={`chip status-${task.status}`}>{task.status}</span>
                    <span
                      className="task-progress"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={task.progress}
                      aria-label={`${task.code} 进度`}
                    >
                      {task.progress}%
                    </span>
                  </button>
                ))}
              </div>
            </aside>

            <WorkstationSplitter layout={layout} />
          </>
        )}

        <section className="ws-main">
          <div className="subnav" role="tablist" aria-label="工作台面板">
            {TAB_LABELS.map((item) => (
              <button
                type="button"
                key={item.key}
                role="tab"
                aria-selected={tab === item.key}
                data-testid={`tab-${item.key}`}
                className={`chip ${tab === item.key ? "active" : ""}`}
                onClick={() => setTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === "details" && (
            <section className="surface" data-testid="panel-details" style={{ padding: 16 }}>
              {current ? (
                <div className="ws-details-grid" data-testid="details-spec-split">
                  {/* 完整已批准规格与当前任务约束同屏：正文不再需要先回「项目讨论」才看得见。 */}
                  <div className="ws-details-spec" data-testid="details-spec-column">
                    <ApprovedSpecPanel sessions={sessions} runId={runId} onStatusChange={setSpecStatus} />
                  </div>
                  <div className="ws-details-main" data-testid="details-constraints-column">
                    <div className="section-title" style={{ gap: 10, flexWrap: "wrap" }}>
                      <span data-testid="detail-task-code" className="mono">
                        {current.code}
                      </span>
                      <span className="hint">{current.status}</span>
                      <TaskPicker label="切换任务" tasks={tasks} value={current.code} onPick={locateTask} />
                    </div>
                    {/* 主内容：持久化的任务输入与约束（角色、依赖、写入范围、验收、SPEC、上下文注入）。 */}
                    <InputConstraintsPanel
                      task={current}
                      runId={runId}
                      actorBotId={actorBotId}
                      grantStatus={grantStatus}
                      grantErrorCategory={grantErrorCategory}
                      onShowFullSpec={showFullSpec}
                    />
                    {/* 次要内容：未持久化的页面备注，明确标注不进入任务上下文。 */}
                    <div
                      data-testid="task-note-secondary"
                      data-secondary="true"
                      style={{ marginTop: 20, paddingTop: 12, borderTop: "1px solid rgba(82,115,140,.18)" }}
                    >
                      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <span className="muted">任务备注（仅本页内存，未持久化、不进入任务上下文）</span>
                        <textarea
                          aria-label="任务备注"
                          rows={2}
                          value={note}
                          onChange={(event) => {
                            setNote(event.target.value);
                            dirtyRef.current = true;
                          }}
                        />
                      </label>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="muted">还没有任务；生成任务计划后可在上方下拉选择查看。</div>
              )}
            </section>
          )}

          {tab === "assignment" && (
            <section className="surface" data-testid="panel-assignment" style={{ padding: 16 }}>
              {/* A2/A3：编排之后的划分与派发主路径；群聊与 Leader 复用既有成员/讨论。 */}
              <TaskAssignmentBoard
                runId={runId}
                tasks={tasks}
                members={team?.members || []}
                actorBotId={actorBotId}
                actorIsLeader={actorIsLeader}
                runStatus={runStatus}
                onRefresh={onRefresh}
                onLocateTask={locateTask}
                onShowDiscussion={onShowDiscussion}
                onInvite={team?.onInvite}
                onManage={team?.onManage}
              />
            </section>
          )}

          {tab === "monitor" && (
            <section className="surface" data-testid="panel-monitor" style={{ padding: 16 }}>
              <RunMonitorPanel
                runId={runId}
                tasks={tasks}
                onLocateTask={locateTask}
                onRefresh={onRefresh}
                actorBotId={actorBotId}
                actorIsLeader={actorIsLeader}
              />
              {memoryPanel && <div style={{ marginTop: 16 }}>{memoryPanel}</div>}
              <div style={{ marginTop: 16 }}>
                <DiscussionReviewPanel ballots={ballots} dissentItems={dissentItems} bots={bots} />
              </div>
              <div style={{ marginTop: 16 }}>
                <DefectList defects={defects} onLocateTask={locateTask} />
              </div>
            </section>
          )}

          {tab === "evaluation" && (
            <section className="surface" data-testid="panel-evaluation" style={{ padding: 16 }}>
              <AgentEvaluationPanel runId={runId} />
            </section>
          )}

          {tab === "activity" && (
            <section className="surface" data-testid="panel-activity" style={{ padding: 16 }}>
              <div className="section-title">
                <span>活动</span>
                {runId && <span className="hint mono">运行 {runId}</span>}
              </div>
              {runId ? (
                <>
                  {/* I5：复用 GET /api/runs/{run_id}/trace 的需求/规格项 → 任务编排追溯（非执行步骤图）。 */}
                  {/* Newest activity first: the trace matrix can hold hundreds of rows. */}
                  <ActivityTimeline runId={runId} />
                  <div style={{ marginTop: 16 }}>
                    <RequirementTracePanel runId={runId} />
                  </div>
                  <p className="muted" style={{ marginBottom: 0 }}>
                    完整记录已在上方；深链接：
                    <Link to={`/runs/${runId}/timeline`} className="chip" style={{ marginLeft: 8 }}>
                      在运行详情打开时间线（深链接）
                    </Link>
                    <Link to={`/workstation/${runId}`} className="chip" style={{ marginLeft: 8 }}>
                      完整工作台（次入口）
                    </Link>
                  </p>
                </>
              ) : (
                <p className="muted">还没有绑定运行。</p>
              )}
            </section>
          )}

          {tab === "graph" && (
            <section className="surface" data-testid="panel-graph" style={{ padding: 16 }}>
              <div className="section-title" style={{ gap: 10, flexWrap: "wrap" }}>
                <span>任务图</span>
                <span className="hint">点选节点联动详情；下拉可定位任务</span>
                {/* 任务图是满宽画布：定位任务用头部下拉，不再依赖左侧任务树。 */}
                <TaskPicker label="定位任务" tasks={tasks} value={selected} onPick={setSelected} />
              </div>
              {/* 与 /workstation/:id 共用同一个分层依赖图组件；不再是纯文本列表。 */}
              <TaskDependencyGraph
                tasks={tasks.map((task) => ({
                  id: task.code,
                  code: task.code,
                  title: task.title,
                  status: mapTaskState(task.status),
                  rawState: task.status,
                  subtitle: [task.role, task.module, task.points != null ? `${task.points}pt` : ""]
                    .filter(Boolean)
                    .join(" · ") || undefined,
                  kind: "task",
                  dependsOn: task.dependsOn || [],
                  assignee: task.assignment ? task.assignment.assignee_display_name : null,
                }))}
                selected={selected}
                onSelect={(code) => setSelected(code)}
                kind="tasks"
                fitKey={runId || ""}
                style={{
                  // 满宽后让画布吃掉剩余视口高度，而不是固定 440px 的小窗。
                  height: "calc(100vh - 240px)",
                  minHeight: 420,
                  border: "1px solid #d8e8f2",
                  borderRadius: "var(--glass-radius-panel, 24px)",
                  background: "var(--glass-surface, rgba(246,253,255,.78))",
                  boxShadow: "var(--glass-shadow)",
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                  overflow: "hidden",
                }}
              />
            </section>
          )}
        </section>
      </div>
      )}
    </div>
  );
}

/** Header task picker for the full-width 详情 / 任务图 panels (replaces the removed side tree). */
function TaskPicker({
  label,
  tasks,
  value,
  onPick,
}: {
  label: string;
  tasks: WorkstationTask[];
  value: string;
  onPick: (code: string) => void;
}) {
  return (
    <label
      className="muted"
      style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12 }}
    >
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => {
          if (event.target.value) onPick(event.target.value);
        }}
        style={{
          minWidth: 280,
          maxWidth: 460,
          height: 32,
          padding: "0 8px",
          borderRadius: "var(--glass-radius-field, 14px)",
          border: "1px solid rgba(82,115,140,.28)",
          background: "var(--glass-field, rgba(255,255,255,.72))",
          color: "var(--glass-ink, #122d42)",
          fontSize: 12.5,
        }}
      >
        {tasks.map((task) => (
          <option key={task.code} value={task.code}>
            {task.code} {task.title}
          </option>
        ))}
      </select>
    </label>
  );
}

export type ProjectWorkstationPageProps = { projectId?: string; grantErrorCategory?: string | null };

/** Acting identity for discussion/defect/memory reads: the leader, else the first member. */
function defaultActor(members: TeamMember[]): string {
  return members.find((member) => member.is_leader)?.bot_id || members[0]?.bot_id || "";
}

export default function ProjectWorkstationPage({ projectId = "", grantErrorCategory = null }: ProjectWorkstationPageProps) {
  const params = useParams();
  const id = projectId || params.projectId || "";
  // 静态演示项目：只读快照，直接展示拆分后的开发任务 tabs，不提供讨论/写操作入口。
  const isStatic = isStaticProjectId(id);
  const dirtyRef = useMemo(() => ({ current: false }), []);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [allBots, setAllBots] = useState<BotInstance[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorText, setErrorText] = useState("");
  const [tasks, setTasks] = useState<WorkstationTask[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [runStatus, setRunStatus] = useState<string>("");
  const [grantStatus, setGrantStatus] = useState<GrantStatus | undefined>();
  const [derivedGrantError, setDerivedGrantError] = useState<string | null>(null);
  const [defects, setDefects] = useState<DefectRecord[]>([]);
  const [ballots, setBallots] = useState<ReviewBallot[]>([]);
  const [dissentItems, setDissentItems] = useState<string[]>([]);
  const [sessions, setSessions] = useState<DiscussionSession[]>([]);
  const [showDiscussion, setShowDiscussion] = useState(!isStatic);

  useEffect(() => {
    let cancelled = false;
    api
      .projects()
      .then((list: any) => {
        const found = (Array.isArray(list) ? list : []).find((item: any) => String(item.id) === String(id));
        if (!cancelled && found?.name) setProjectName(String(found.name));
      })
      .catch(() => {
        // The generic title stays when the name cannot be read.
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const load = useCallback(async () => {
    try {
      // Team + bots load first: a project with no run yet must still be able to invite bots.
      let memberRows: TeamMember[] = [];
      try {
        const [memberRes, botRes] = await Promise.all([
          api.memberships(String(id)),
          // 静态项目的 Bot 目录同样来自快照，与真实 Bot 列表完全解耦。
          isStatic ? loadStaticSnapshot().then((snap) => snap.bots) : api.bots(),
        ]);
        const bots: BotInstance[] = Array.isArray(botRes?.items) ? botRes.items : [];
        const botMap = new Map(bots.map((bot) => [bot.bot_id, bot]));
        memberRows = (Array.isArray(memberRes?.items) ? memberRes.items : []).flatMap((member: any) => {
          const bot = botMap.get(member.bot_id);
          if (!bot) return [];
          return [
            {
              bot_id: member.bot_id,
              display_name: bot.display_name,
              role_template: bot.role_template,
              status: bot.status,
              role_in_project: member.role_in_project,
              is_leader: Boolean(member.is_leader),
            },
          ];
        });
        setTeamMembers(memberRows);
        setAllBots(bots);
      } catch {
        setTeamMembers([]);
      }
      // Discussion/defect reads need an explicit actor: the leader, else the first member.
      const effectiveActor = defaultActor(memberRows);
      const runs = await api.runs();
      const owned = (Array.isArray(runs) ? runs : []).filter((run: any) => String(run.project_id) === String(id));
      if (owned.length === 0) {
        setRunId("");
        setRunStatus("");
        setTasks([]);
        setSessions([]);
        setLoadState("empty");
        return;
      }
      const latest = owned[owned.length - 1];
      setRunId(String(latest.id));
      setRunStatus(String(latest.status || ""));
      const raw = await api.tasks(String(latest.id));
      const mapped = mapTasks(raw);
      setTasks(mapped);

      // Read-only P6 panels. Failures here must never blank the workstation.
      try {
        const grants = await api.executionGrants(String(latest.id));
        const items = Array.isArray(grants?.items) ? grants.items : [];
        const active = items[items.length - 1];
        if (active?.status) setGrantStatus(active.status as GrantStatus);
        // A stale grant means the signed baseline changed; surface the same
        // category the schedule API would return.
        setDerivedGrantError(active?.status === "stale" ? "baseline_stale" : null);
      } catch {
        setGrantStatus(undefined);
      }
      if (effectiveActor) {
        try {
          const listed = await api.defects(String(latest.id), effectiveActor);
          setDefects(Array.isArray(listed?.items) ? listed.items : []);
        } catch {
          setDefects([]);
        }
        try {
          const listed = await api.discussionSessions(String(id), effectiveActor);
          const sessionItems: DiscussionSession[] = Array.isArray(listed?.items) ? listed.items : [];
          setSessions(sessionItems);
          const session = sessionItems[0];
          if (session?.session_id) {
            const reviews = await api.discussionReviews(String(session.session_id), effectiveActor);
            const items = Array.isArray(reviews?.items) ? reviews.items : [];
            setBallots(items);
            setDissentItems(
              items.flatMap((ballot: ReviewBallot) => (Array.isArray(ballot.dissent_items) ? ballot.dissent_items : [])),
            );
          }
        } catch {
          setBallots([]);
          setDissentItems([]);
          setSessions([]);
        }
      }
      setLoadState(mapped.length === 0 ? "empty" : "ready");
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setLoadState("forbidden");
      else {
        setErrorText(err?.message || "工作台加载失败");
        setLoadState("error");
      }
    }
  }, [id, isStatic]);

  useEffect(() => {
    void load();
  }, [load]);

  const actor = defaultActor(teamMembers);

  return (
    <>
    <ProjectWorkstation
      projectId={id}
      projectName={projectName}
      loadState={loadState}
      tasks={tasks}
      dirtyRef={dirtyRef}
      errorText={errorText}
      runId={runId}
      grantErrorCategory={grantErrorCategory || derivedGrantError}
      grantStatus={grantStatus}
      ballots={ballots}
      dissentItems={dissentItems}
      defects={defects}
      team={{
        members: teamMembers,
        onInvite: () => setInviteOpen(true),
        onManage: () => setDialogOpen(true),
      }}
      bots={allBots}
      sessions={sessions}
      onRefresh={load}
      onShowDiscussion={isStatic ? undefined : () => setShowDiscussion(true)}
      onShowTasks={
        isStatic
          ? undefined
          : () => {
              setShowDiscussion(false);
              void load();
            }
      }
      actorBotId={actor}
      actorIsLeader={Boolean(teamMembers.find((member) => member.bot_id === actor)?.is_leader)}
      runStatus={runStatus}
      discussionPanel={
        !isStatic && showDiscussion ? (
          <DiscussionView
            projectId={id}
            actorBotId={actor}
            members={teamMembers}
            bots={allBots}
            onInvite={() => setInviteOpen(true)}
            onPlanReady={load}
          />
        ) : undefined
      }
      memoryPanel={
        <ProjectMemoryPanel
          projectId={id}
          actorBotId={actor}
          isLeader={Boolean(teamMembers.find((member) => member.bot_id === actor)?.is_leader)}
        />
      }
    />
    {inviteOpen && (
      <InviteBotsDialog
        projectId={id}
        members={teamMembers}
        allBots={allBots}
        onClose={() => setInviteOpen(false)}
        onChanged={load}
      />
    )}
    {dialogOpen && (
      <ManageMembersDialog
        projectId={id}
        members={teamMembers}
        onClose={() => setDialogOpen(false)}
        onInvite={() => {
          setDialogOpen(false);
          setInviteOpen(true);
        }}
        onChanged={load}
      />
    )}
    </>
  );
}
