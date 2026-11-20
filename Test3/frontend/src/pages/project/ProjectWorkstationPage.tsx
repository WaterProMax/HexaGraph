import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { DefectRecord, GrantStatus, ReviewBallot, RunTask } from "../../api/types";
import type { LoadState } from "../../components/AppShell";
import { LEFT_PANEL_ID, WorkstationSplitter } from "../../components/WorkstationSplitter";
import { useWorkstationLayout } from "../../workstationLayout";
import { DefectList } from "./DefectList";
import { DiscussionReviewPanel } from "./DiscussionReviewPanel";
import { GrantStatusBanner } from "./GrantStatusBanner";

export type WorkstationTab = "details" | "monitor" | "activity" | "graph";

export type WorkstationTask = { code: string; title: string; progress: number; status: string };

export type ProjectWorkstationProps = {
  projectId: string;
  loadState: LoadState;
  tasks: Array<{ code: string; title: string; progress: number; status: string }>;
  dirtyRef: { current: boolean };
  initialTab?: WorkstationTab;
  errorText?: string;
  runId?: string;
  grantErrorCategory?: string | null;
  grantStatus?: GrantStatus;
  ballots?: ReviewBallot[];
  dissentItems?: string[];
  defects?: DefectRecord[];
};

const TAB_LABELS: Array<{ key: WorkstationTab; label: string }> = [
  { key: "details", label: "详情" },
  { key: "monitor", label: "执行监控" },
  { key: "activity", label: "活动" },
  { key: "graph", label: "任务图" },
];

export function progressForState(state: string): number {
  if (state === "done") return 100;
  if (state === "running" || state === "verifying") return 40;
  return 0;
}

export function mapTasks(tasks: RunTask[]): WorkstationTask[] {
  return (Array.isArray(tasks) ? tasks : []).map((task) => ({
    code: String(task.code),
    title: String(task.card?.title || task.code),
    progress: progressForState(String(task.state)),
    status: String(task.state),
  }));
}

export function ProjectWorkstation({
  projectId,
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
}: ProjectWorkstationProps) {
  const layout = useWorkstationLayout();
  const [tab, setTab] = useState<WorkstationTab>(initialTab);
  const [selected, setSelected] = useState<string>(tasks[0]?.code || "");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!tasks.some((task) => task.code === selected)) setSelected(tasks[0]?.code || "");
  }, [tasks, selected]);

  const current = useMemo(() => tasks.find((task) => task.code === selected), [tasks, selected]);

  if (loadState === "loading") {
    return (
      <div className="page">
        <div className="well muted" data-testid="ws-loading" style={{ padding: "14px 16px" }}>
          正在加载项目工作台…
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
      <div className="page-head">
        <h1>项目工作台</h1>
        <p className="mono">{projectId}</p>
      </div>
      <GrantStatusBanner errorCategory={grantErrorCategory} status={grantStatus} />
      {loadState === "empty" || tasks.length === 0 ? (
        <div className="well muted" data-testid="ws-empty" style={{ padding: "14px 16px" }}>
          这个项目还没有可展示的任务。先在项目里创建一次运行。
        </div>
      ) : null}

      <div className={layout.bodyClassName} style={layout.bodyStyle} ref={layout.bodyRef} data-testid="project-workstation">
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
                className={`task-tree-item ${task.code === selected ? "active" : ""}`}
                onClick={() => {
                  setSelected(task.code);
                  setTab("details");
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
                <>
                  <div className="section-title">
                    <span data-testid="detail-task-code" className="mono">
                      {current.code}
                    </span>
                    <span className="hint">{current.status}</span>
                  </div>
                  <p style={{ marginTop: 0 }}>{current.title}</p>
                  <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <span className="muted">任务备注</span>
                    <textarea
                      aria-label="任务备注"
                      rows={3}
                      value={note}
                      onChange={(event) => {
                        setNote(event.target.value);
                        dirtyRef.current = true;
                      }}
                    />
                  </label>
                </>
              ) : (
                <div className="muted">选择左侧任务查看详情。</div>
              )}
            </section>
          )}

          {tab === "monitor" && (
            <section className="surface" data-testid="panel-monitor" style={{ padding: 16 }}>
              <div className="section-title">
                <span>执行监控</span>
                <span className="hint mono">{runId || "未绑定运行"}</span>
              </div>
              <div className="grid-list">
                {tasks.length === 0 && <div className="muted">没有任务可监控。</div>}
                {tasks.map((task) => (
                  <div className="list-card" key={task.code}>
                    <span className="mono">{task.code}</span>
                    <span className={`chip status-${task.status}`}>{task.status}</span>
                    <span className="hint">{task.progress}%</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16 }}>
                <DiscussionReviewPanel ballots={ballots} dissentItems={dissentItems} />
              </div>
              <div style={{ marginTop: 16 }}>
                <DefectList
                  defects={defects}
                  onLocateTask={(code) => {
                    setSelected(code);
                    setTab("details");
                  }}
                />
              </div>
            </section>
          )}

          {tab === "activity" && (
            <section className="surface" data-testid="panel-activity" style={{ padding: 16 }}>
              <div className="section-title">
                <span>活动</span>
              </div>
              {runId ? (
                <p className="muted">
                  事件流属于运行 <span className="mono">{runId}</span>；
                  <Link to={`/runs/${runId}`} className="chip" style={{ marginLeft: 8 }}>
                    打开运行时间线
                  </Link>
                </p>
              ) : (
                <p className="muted">还没有绑定运行。</p>
              )}
            </section>
          )}

          {tab === "graph" && (
            <section className="surface" data-testid="panel-graph" style={{ padding: 16 }}>
              <div className="section-title">
                <span>任务图</span>
              </div>
              {tasks.length === 0 ? (
                <p className="muted">没有任务。</p>
              ) : (
                <ul className="task-graph-list">
                  {tasks.map((task) => (
                    <li key={task.code}>
                      <span className="mono">{task.code}</span> {task.title} · {task.status}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </section>
      </div>
    </div>
  );
}

export type ProjectWorkstationPageProps = { projectId?: string; actorBotId?: string; grantErrorCategory?: string | null };

export default function ProjectWorkstationPage({ projectId = "", actorBotId, grantErrorCategory = null }: ProjectWorkstationPageProps) {
  const params = useParams();
  const id = projectId || params.projectId || "";
  const dirtyRef = useMemo(() => ({ current: false }), []);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorText, setErrorText] = useState("");
  const [tasks, setTasks] = useState<WorkstationTask[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [grantStatus, setGrantStatus] = useState<GrantStatus | undefined>();
  const [derivedGrantError, setDerivedGrantError] = useState<string | null>(null);
  const [defects, setDefects] = useState<DefectRecord[]>([]);
  const [ballots, setBallots] = useState<ReviewBallot[]>([]);
  const [dissentItems, setDissentItems] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const runs = await api.runs();
      const owned = (Array.isArray(runs) ? runs : []).filter((run: any) => String(run.project_id) === String(id));
      if (owned.length === 0) {
        setTasks([]);
        setLoadState("empty");
        return;
      }
      const latest = owned[owned.length - 1];
      setRunId(String(latest.id));
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
      let actor = actorBotId;
      if (!actor) {
        // Discussion/defect reads need an explicit actor; the project leader is
        // the natural default. A missing membership simply hides those panels.
        try {
          const members = await api.memberships(String(id));
          const items = Array.isArray(members?.items) ? members.items : [];
          actor = items.find((member: any) => member.is_leader)?.bot_id;
        } catch {
          actor = undefined;
        }
      }
      if (actor) {
        try {
          const listed = await api.defects(String(latest.id), actor);
          setDefects(Array.isArray(listed?.items) ? listed.items : []);
        } catch {
          setDefects([]);
        }
        try {
          const sessions = await api.discussionSessions(String(id), actor);
          const session = (Array.isArray(sessions?.items) ? sessions.items : [])[0];
          if (session?.session_id) {
            const reviews = await api.discussionReviews(String(session.session_id), actor);
            const items = Array.isArray(reviews?.items) ? reviews.items : [];
            setBallots(items);
            setDissentItems(
              items.flatMap((ballot: ReviewBallot) => (Array.isArray(ballot.dissent_items) ? ballot.dissent_items : [])),
            );
          }
        } catch {
          setBallots([]);
          setDissentItems([]);
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
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <ProjectWorkstation
      projectId={id}
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
    />
  );
}