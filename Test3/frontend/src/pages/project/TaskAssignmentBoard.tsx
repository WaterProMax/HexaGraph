import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { TaskAssignment } from "../../api/types";
import { TeamStrip, type TeamMember } from "./TeamStrip";

/**
 * A2/A3: the classroom dispatch board on the project main path
 * (`/projects/:id` → 开发任务 → 任务派发).
 *
 * The Leader picks which project member is responsible for each task block.
 * This is an annotation overlay only: execution and role memory stay
 * role-scoped (coder/tester), the scheduler is unchanged, and an unassigned
 * task still runs by role.  The group chat reuses the existing project
 * discussion — this board never creates a second chat.
 */

export type AssignmentBoardTask = {
  code: string;
  title: string;
  role?: string;
  dependsOn?: string[];
  status: string;
  revision?: number;
  assignment?: TaskAssignment | null;
};

export type TaskAssignmentBoardProps = {
  runId?: string;
  tasks: AssignmentBoardTask[];
  members?: TeamMember[];
  actorBotId?: string;
  /** Defaults to false: an unknown actor never gets write controls. */
  actorIsLeader?: boolean;
  /** Run status from the run view; done/terminated makes the board read-only. */
  runStatus?: string;
  onRefresh?: () => void;
  onLocateTask?: (code: string) => void;
  onShowDiscussion?: () => void;
  onInvite?: () => void;
  onManage?: () => void;
  /** Controlled selection for the classroom grid; the board itself stays internal otherwise. */
  selected?: string;
  onSelect?: (code: string) => void;
  /** Dense rows for the classroom grid; interactions are unchanged. */
  compact?: boolean;
};

const READ_ONLY_RUN_STATES = new Set(["done", "terminated"]);

export function TaskAssignmentBoard({
  runId,
  tasks,
  members = [],
  actorBotId,
  actorIsLeader = false,
  runStatus = "",
  onRefresh,
  onLocateTask,
  onShowDiscussion,
  onInvite,
  onManage,
  selected,
  onSelect,
  compact = false,
}: TaskAssignmentBoardProps) {
  const [rows, setRows] = useState<AssignmentBoardTask[]>(tasks);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<Record<string, boolean>>({});
  // A scope token isolates late responses: switching run/project invalidates
  // every in-flight write so an old answer cannot overwrite the new selection.
  const scopeRef = useRef(0);
  useEffect(() => {
    scopeRef.current += 1;
    setRows(tasks);
    setNotice("");
    setPending({});
  }, [runId, tasks]);

  const runReadOnly = READ_ONLY_RUN_STATES.has(runStatus);
  const canWrite = Boolean(actorIsLeader && actorBotId && runId) && !runReadOnly;
  const leader = members.find((member) => member.is_leader);
  const teamReady = members.length >= 2 && Boolean(leader);
  const unassigned = rows.filter((row) => !row.assignment).length;

  async function submit(task: AssignmentBoardTask, value: string) {
    if (!canWrite || !runId || !actorBotId) return;
    const scope = scopeRef.current;
    setPending((current) => ({ ...current, [task.code]: true }));
    setNotice("");
    try {
      const updated = await api.assignTask(
        runId,
        task.code,
        { assignee_bot_id: value || null, expected_revision: Number(task.revision ?? 0) },
        actorBotId,
      );
      if (scope !== scopeRef.current) return;
      const record = (updated || {}) as Record<string, unknown>;
      const assignment = (record.assignment as TaskAssignment | null) ?? null;
      const revision = typeof record.revision === "number" ? record.revision : Number(task.revision ?? 0) + 1;
      setRows((current) => current.map((row) => (row.code === task.code ? { ...row, assignment, revision } : row)));
      onRefresh?.();
    } catch (err) {
      if (scope !== scopeRef.current) return;
      if (err instanceof ApiError && err.status === 409 && err.category === "revision_conflict") {
        setNotice("派发冲突：该任务已被更新，已刷新服务器派发，请重试。");
        // Refresh only the server-owned overlay/revision; never report the
        // failed write as a success.
        try {
          const fresh = await api.tasks(runId);
          if (scope !== scopeRef.current) return;
          const freshRows = Array.isArray(fresh) ? fresh : [];
          setRows((current) =>
            current.map((row) => {
              const server = freshRows.find((item: any) => String(item?.code) === row.code);
              if (!server) return row;
              return {
                ...row,
                assignment: (server.assignment as TaskAssignment | null) ?? null,
                revision: typeof server.revision === "number" ? server.revision : row.revision,
              };
            }),
          );
        } catch {
          // The conflict notice stays; the next refresh retries the read.
        }
      } else if (err instanceof ApiError && err.status === 409 && err.category === "run_busy") {
        setNotice("运行正忙：执行批次占用写锁，请稍后重试派发。");
      } else {
        setNotice(err instanceof Error ? err.message : "派发失败，请重试。");
      }
    } finally {
      if (scope === scopeRef.current) {
        setPending((current) => ({ ...current, [task.code]: false }));
      }
    }
  }

  const teamHeader = (
    <>
      <div className="assignment-team" data-testid="assignment-team">
        <TeamStrip members={members} onInvite={onInvite || (() => {})} onManage={onManage || (() => {})} showActions={false} />
        <span className="chip" data-testid="assignment-leader">
          {leader ? `Leader：${leader.display_name}` : "尚未设置 Leader"}
        </span>
        <span className="muted" data-testid="assignment-member-names">
          {members.length > 0 ? members.map((member) => member.display_name).join("、") : "暂无成员"}
        </span>
        {onShowDiscussion && (
          <button type="button" className="chip" data-testid="assignment-back-to-discussion" onClick={onShowDiscussion}>
            回到项目讨论
          </button>
        )}
      </div>
      {!teamReady && (
        <div className="well" data-testid="assignment-team-guidance" style={{ padding: "10px 12px", marginBottom: 10 }}>
          <span>先邀请 Bot：项目至少需要 2 名成员并设置 Leader，才能开始讨论。</span>
          {onInvite && (
            <button type="button" className="chip primary" data-testid="assignment-invite" style={{ marginLeft: 8 }} onClick={onInvite}>
              邀请更多 Bot
            </button>
          )}
          {onManage && (
            <button type="button" className="chip" data-testid="assignment-manage" style={{ marginLeft: 8 }} onClick={onManage}>
              管理项目成员
            </button>
          )}
        </div>
      )}
    </>
  );

  if (!runId || rows.length === 0) {
    return (
      <div data-testid="assignment-board" className={`assignment-board${compact ? " is-compact" : ""}`}>
        <div className="assignment-head">
          <h2 className="assignment-title">任务派发</h2>
        </div>
        {teamHeader}
        <div className="well muted assignment-empty" data-testid="assignment-empty">
          确认需求规格并完成设计规格确认后，才会出现可划分的任务。
        </div>
      </div>
    );
  }

  return (
    <div data-testid="assignment-board" className={`assignment-board${compact ? " is-compact" : ""}`}>
      <div className="assignment-head">
        <h2 className="assignment-title">任务派发</h2>
        <span className="assignment-count" data-testid="assignment-unassigned-count">
          还有 {unassigned} 项未派发{compact ? "" : "（不阻断按角色自动调度）"}
        </span>
      </div>
      <div className="assignment-body">
        {teamHeader}
        <p className="assignment-note" data-testid="assignment-semantics-note">
          角色决定执行槽位与角色记忆；派发对象只用于课上标明由哪位项目 Agent 负责，不会改记忆主语，也不会改成按该 Bot 的密钥执行。未派发的任务将按角色自动调度。
        </p>
        {notice && (
          <div className="well assignment-error" role="alert" data-testid="assignment-error">
            {notice}
          </div>
        )}
        {runReadOnly && <p className="assignment-note">运行已结束，派发记录只读。</p>}
        <table className="assignment-table">
        <thead>
          <tr>
            <th>{compact ? "编号" : "任务代码"}</th>
            <th>标题</th>
            <th title="角色决定执行槽位与记忆主语">{compact ? "角色" : "角色（执行与记忆主语）"}</th>
            <th>依赖</th>
            <th title="派发对象（项目成员，课上可见）">{compact ? "派发对象" : "派发对象（项目成员，课上可见）"}</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.code}
              data-testid={`assignment-row-${row.code}`}
              data-selected={selected === row.code ? "true" : undefined}
              className={selected === row.code ? "is-selected" : undefined}
              onClick={(event) => {
                // In the classroom grid a row click only moves the shared selection;
                // controls inside the row keep their own behaviour.
                if ((event.target as HTMLElement).closest("select, button, a, input, textarea")) return;
                onSelect?.(row.code);
              }}
            >
              <td className="mono">
                {onSelect || onLocateTask ? (
                  <button
                    type="button"
                    className="chip"
                    onClick={() => (onSelect ?? onLocateTask)!(row.code)}
                  >
                    {row.code}
                  </button>
                ) : (
                  row.code
                )}
              </td>
              <td>{row.title}</td>
              <td>{row.role || "未标注"}</td>
              <td className="mono">{(row.dependsOn || []).join("、") || "—"}</td>
              <td data-testid={`assignment-assignee-${row.code}`}>
                <select
                  data-testid={`assignment-select-${row.code}`}
                  aria-label={`派发 ${row.code}`}
                  value={row.assignment?.assignee_bot_id ?? ""}
                  disabled={!canWrite || Boolean(pending[row.code])}
                  onChange={(event) => void submit(row, event.target.value)}
                >
                  <option value="">尚未派发</option>
                  {members.map((member) => (
                    <option key={member.bot_id} value={member.bot_id}>
                      {member.display_name}
                      {member.is_leader ? "（Leader）" : ""}
                    </option>
                  ))}
                </select>
                <span className="muted assignment-assignee-name">
                  {row.assignment ? row.assignment.assignee_display_name : "尚未派发（将按角色自动调度）"}
                </span>
              </td>
              <td>
                <span className={`chip status-${row.status}`}>{row.status}</span>
              </td>
            </tr>
          ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default TaskAssignmentBoard;