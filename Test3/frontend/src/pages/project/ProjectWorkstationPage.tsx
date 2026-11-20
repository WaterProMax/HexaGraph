import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { BotInstance, DefectRecord, GrantStatus, ReviewBallot, RunTask } from "../../api/types";
import type { LoadState } from "../../components/AppShell";
import { LEFT_PANEL_ID, WorkstationSplitter } from "../../components/WorkstationSplitter";
import { useWorkstationLayout } from "../../workstationLayout";
import { DefectList } from "./DefectList";
import { DiscussionReviewPanel } from "./DiscussionReviewPanel";
import { DiscussionView } from "./discussion/DiscussionView";
import { GrantStatusBanner } from "./GrantStatusBanner";
import { InviteBotsDialog } from "./InviteBotsDialog";
import { ManageMembersDialog } from "./ManageMembersDialog";
import { ProjectMemoryPanel } from "./ProjectMemoryPanel";
import { TeamStrip, type TeamMember } from "./TeamStrip";

export type WorkstationTab = "details" | "monitor" | "activity" | "graph";

export type WorkstationTask = { code: string; title: string; progress: number; status: string };

export type ProjectWorkstationProps = {
  projectId: string;
  /** Shown as the page title; falls back to a generic title until it loads. */
  projectName?: string;
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
  team?: {
    members: TeamMember[];
    onInvite: () => void;
    onManage: () => void;
  };
  memoryPanel?: ReactNode;
  bots?: BotInstance[];
  /** Replaces the empty-run notice and the whole task body (project without any run yet). */
  discussionPanel?: ReactNode;
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
  discussionPanel,
}: ProjectWorkstationProps) {
  const layout = useWorkstationLayout();
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
        <h1>{projectName || "项目工作台"}</h1>
      </div>
      <GrantStatusBanner errorCategory={grantErrorCategory} status={grantStatus} />
      {team && (
        <TeamStrip
          members={team.members}
          onInvite={team.onInvite}
          onManage={team.onManage}
        />
      )}
      {!discussionPanel && (loadState === "empty" || tasks.length === 0) ? (
        <div className="well muted" data-testid="ws-empty" style={{ padding: "14px 16px" }}>
          这个项目还没有可展示的任务。先在项目里创建一次运行。
        </div>
      ) : null}

      {discussionPanel && (
        <div className="ws-discussion" data-testid="ws-discussion">
          {discussionPanel}
        </div>
      )}

      {!discussionPanel && (
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
              {memoryPanel && <div style={{ marginTop: 16 }}>{memoryPanel}</div>}
              <div style={{ marginTop: 16 }}>
                <DiscussionReviewPanel ballots={ballots} dissentItems={dissentItems} bots={bots} />
              </div>
              <div style={{ marginTop: 16 }}>
                <DefectList defects={defects} onLocateTask={locateTask} />
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
      )}
    </div>
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
  const [grantStatus, setGrantStatus] = useState<GrantStatus | undefined>();
  const [derivedGrantError, setDerivedGrantError] = useState<string | null>(null);
  const [defects, setDefects] = useState<DefectRecord[]>([]);
  const [ballots, setBallots] = useState<ReviewBallot[]>([]);
  const [dissentItems, setDissentItems] = useState<string[]>([]);
  /** `null` until the run list is read; `false` means the project has no run yet. */
  const [hasRun, setHasRun] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProjectName("");
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
    setLoadState("loading");
    setHasRun(null);
    try {
      // Team + bots load first: a project with no run yet must still be able to invite bots.
      let memberRows: TeamMember[] = [];
      try {
        const [memberRes, botRes] = await Promise.all([api.memberships(String(id)), api.bots()]);
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
        setHasRun(false);
        setTasks([]);
        setLoadState("empty");
        return;
      }
      setHasRun(true);
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
      if (effectiveActor) {
        try {
          const listed = await api.defects(String(latest.id), effectiveActor);
          setDefects(Array.isArray(listed?.items) ? listed.items : []);
        } catch {
          setDefects([]);
        }
        try {
          const sessions = await api.discussionSessions(String(id), effectiveActor);
          const session = (Array.isArray(sessions?.items) ? sessions.items : [])[0];
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
      discussionPanel={
        hasRun === false ? (
          <DiscussionView
            projectId={id}
            actorBotId={actor}
            members={teamMembers}
            bots={allBots}
            onInvite={() => setInviteOpen(true)}
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