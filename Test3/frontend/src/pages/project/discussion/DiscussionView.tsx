import { useCallback, useEffect, useId, useRef, useState } from "react";
import { CommentOutlined, SendOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../../api/client";
import type { BotInstance } from "../../../api/types";
import type { TeamMember } from "../TeamStrip";
import { ApprovalBanner } from "./ApprovalBanner";
import { DiscussionChat } from "./DiscussionChat";
import { IdeaComposer, MAX_IDEA_LENGTH } from "./IdeaComposer";
import { DiscussionControls, ScorePanel, type DiscussionPendingAction } from "./ScorePanel";
import { SpecApprovalDialog } from "./SpecApprovalDialog";
import { SpecViewer } from "./SpecViewer";
import { StageBar } from "./StageBar";
import { deriveStage, discussionControlFlags, type DiscussionStage } from "./deriveStage";
import { useDiscussionSession } from "./useDiscussionSession";

export type DiscussionViewProps = {
  projectId: string;
  /** Acting identity for every discussion request; may be empty before the team loads. */
  actorBotId: string;
  members: TeamMember[];
  bots: BotInstance[];
  onInvite: () => void;
  onPlanReady?: () => void;
};

/** Stages with a discussion control bar and score panel. */
const CHAT_STAGES: DiscussionStage[] = [
  "independent",
  "revise",
  "review",
  "leader",
  "approval",
  "terminated",
];

export const UNSEALED_BODY_TEXT = "正文尚未解封";

function actionErrorText(err: unknown): string {
  const message = (err as { message?: unknown } | null)?.message;
  return typeof message === "string" && message.trim() ? message : "操作失败，请稍后重试";
}

/**
 * Map a control failure to honest Chinese feedback. The discussion routes only
 * expose some categories directly (`budget_exhausted`); others arrive as
 * `invalid_status` with the real reason in the detail text, so we inspect the
 * message instead of pretending a category exists.
 */
function classifyControlError(err: unknown): { text: string; refresh: boolean } {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return { text: "没有权限执行该操作：只有本场讨论的 Leader 可以控制。", refresh: false };
    }
    if (err.status === 409) {
      const detail = `${err.message || ""} ${err.summary || ""}`.toLowerCase();
      if (err.category === "budget_exhausted" || detail.includes("budget_exhausted")) {
        return { text: "轮数或预算已用尽，本次操作未执行。", refresh: true };
      }
      if (detail.includes("manual_end_not_finalized")) {
        return { text: "本轮人工结束仍在安全停止中，请等待安全检查点完成后再试。", refresh: true };
      }
      if (err.category === "revision_conflict" || detail.includes("revision_conflict")) {
        return { text: "控制版本冲突，已刷新最新状态，请重试。", refresh: true };
      }
      return { text: "当前讨论状态不允许该操作，已刷新最新状态。", refresh: true };
    }
    if (err.status >= 500) {
      return { text: "控制请求未成功（服务器错误），请稍后重试。", refresh: false };
    }
  }
  return { text: actionErrorText(err), refresh: false };
}

type PlanStatus = "running" | "failed" | "ready";

function DiscussionPlan({ sessionId, actorBotId, onStatusChange }: {
  sessionId: string;
  actorBotId: string;
  onStatusChange: (status: PlanStatus) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ runId: string; error: string } | null>(null);
  const statusRef = useRef(onStatusChange);
  statusRef.current = onStatusChange;

  useEffect(() => {
    let active = true;
    setResult(null);
    if (!actorBotId) return;
    statusRef.current("running");
    const generate = async () => {
      try {
        const plan = await api.planDiscussion(sessionId, actorBotId);
        if (!plan?.run_id) throw new Error("后端未返回任务计划，请重试。");
        if (active) {
          setResult({ runId: plan.run_id, error: "" });
          statusRef.current("ready");
        }
      } catch (err) {
        if (active) {
          setResult({ runId: "", error: actionErrorText(err) });
          statusRef.current("failed");
        }
      }
    };
    void generate();
    return () => { active = false; };
  }, [sessionId, actorBotId, attempt]);

  if (!actorBotId) return <p>请设置项目 Leader。</p>;
  if (!result) return <p className="disc-spec-waiting" role="status">Leader 正在拆解任务和编排依赖…</p>;
  if (result.error) return (
    <div className="disc-plan-result">
      <p role="alert" className="disc-view-error">{result.error}</p>
      <button type="button" className="disc-button-secondary" onClick={() => setAttempt((previous) => previous + 1)}>
        重新生成任务计划
      </button>
    </div>
  );
  return (
    <>
      <Link className="disc-btn disc-plan-link" to={`/workstation/${result.runId}`}>
        查看任务编排
      </Link>
      <Link className="disc-btn" to={`/workstation/${result.runId}?view=architecture`}>
        查看架构图
      </Link>
    </>
  );
}

/**
 * 第 5 步：SPEC 批准后，架构师把需求规格展开成设计规格（检查 + 双评审），
 * 由用户确认 DESIGN 基线；批准后后端接着做 Leader 任务拆解（第 6 步）。
 * 设计与评审产物来自运行快照，不在浏览器里缓存。
 */
function DiscussionDesign({
  sessionId,
  actorBotId,
  runIdHint,
  onApproved,
}: {
  sessionId: string;
  actorBotId: string;
  runIdHint: string;
  onApproved: () => void;
}) {
  const [runId, setRunId] = useState(runIdHint);
  const [run, setRun] = useState<any | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"" | "approve" | "reject">("");
  const [rejectReason, setRejectReason] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    if (!actorBotId) return;
    const load = async () => {
      try {
        let id = runIdHint;
        if (!id) {
          const result = await api.designDiscussion(sessionId, actorBotId);
          if (!result?.run_id) throw new Error("后端未返回设计运行，请重试。");
          id = result.run_id;
        }
        if (!active) return;
        setRunId(id);
        const snapshot = await api.run(id);
        if (active) setRun(snapshot);
      } catch (err) {
        if (active) setError(actionErrorText(err));
      }
    };
    void load();
    return () => { active = false; };
  }, [sessionId, actorBotId, runIdHint, attempt]);

  const gates: any[] = Array.isArray(run?.gates) ? run.gates : [];
  const pendingGate = gates.find((gate) => gate.status === "pending" && gate.kind === "DESIGN基线确认");
  const failedGate = gates.find((gate) => gate.status === "pending" && gate.kind === "文档检查失败");

  // 设计生成是长任务：运行已建立但关卡未出现时轮询快照，直到可确认或失败。
  useEffect(() => {
    if (!runId || pendingGate || failedGate) return;
    const timer = setInterval(async () => {
      try {
        const snapshot = await api.run(runId);
        setRun(snapshot);
      } catch {
        // 下一次轮询重试；错误不打断等待提示。
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [runId, pendingGate, failedGate]);

  const approve = async () => {
    if (!pendingGate || busy) return;
    setBusy("approve");
    setError("");
    try {
      await api.resolveGate(pendingGate.id, "approve", {});
      onApproved();
    } catch (err) {
      setError(actionErrorText(err));
    } finally {
      setBusy("");
    }
  };

  const reject = async () => {
    if (!pendingGate || busy || !rejectReason.trim()) return;
    setBusy("reject");
    setError("");
    try {
      await api.resolveGate(pendingGate.id, "reject", { reason: rejectReason.trim() });
      const snapshot = await api.run(runId);
      setRun(snapshot);
      setRejectReason("");
    } catch (err) {
      setError(actionErrorText(err));
    } finally {
      setBusy("");
    }
  };

  if (!actorBotId) return <p>请设置项目 Leader。</p>;
  if (error && !pendingGate) {
    return (
      <div className="disc-plan-result">
        <p role="alert" className="disc-view-error">{error}</p>
        <button type="button" className="disc-button-secondary" onClick={() => setAttempt((previous) => previous + 1)}>
          重新整理设计规格
        </button>
      </div>
    );
  }
  if (busy === "approve") {
    return <p className="disc-spec-waiting" role="status" data-testid="disc-design-wait">设计已确认，Leader 正在拆解任务和编排依赖…</p>;
  }
  if (!run || (!pendingGate && !failedGate)) {
    return <p className="disc-spec-waiting" role="status" data-testid="disc-design-wait">架构师正在整理设计规格，双评审背靠背打分中…</p>;
  }
  if (failedGate) {
    return (
      <div className="disc-plan-result">
        <p role="alert" className="disc-view-error">设计规格未通过检查或评审，未进入任务拆解。</p>
        <Link className="disc-btn disc-plan-link" to={`/workstation/${runId}`}>去工作台处理</Link>
      </div>
    );
  }

  const design = run?.artifacts?.design || pendingGate.payload?.design || {};
  const modules: any[] = Array.isArray(design.modules) ? design.modules : [];
  const interfaces: any[] = Array.isArray(design.interfaces) ? design.interfaces : [];
  const reviews: any[] = Array.isArray(run?.artifacts?.design_reviews) ? run.artifacts.design_reviews : [];

  return (
    <div className="disc-design-review" data-testid="disc-design-review">
      <p className="disc-design-heading">设计规格待你确认</p>
      <ul className="disc-design-modules" aria-label="设计模块">
        {modules.map((module) => (
          <li key={module.code}>
            <span className="mono">{module.code}</span>
            <span className="disc-design-module-name" title={module.responsibility}>{module.name}</span>
          </li>
        ))}
      </ul>
      <p className="disc-design-meta">
        模块 {modules.length} 个 · 接口 {interfaces.length} 个
        {reviews.length > 0 && ` · 评审 ${reviews.map((sheet) => `${sheet.reviewer} ${sheet.score} 分`).join(" / ")}`}
      </p>
      {error && <p role="alert" className="disc-view-error">{error}</p>}
      {busy === "reject" ? (
        <p className="disc-spec-waiting" role="status">已驳回，架构师正在按意见重写设计…</p>
      ) : (
        <>
          <label className="disc-design-reject-field">
            <span>驳回意见（驳回时必填）</span>
            <textarea
              aria-label="设计驳回意见"
              rows={2}
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="写明需要修改的设计问题"
            />
          </label>
          <div className="disc-design-actions">
            <button type="button" className="disc-btn disc-plan-link" onClick={approve} disabled={Boolean(busy)}>
              批准设计基线
            </button>
            <button
              type="button"
              className="disc-button-secondary"
              onClick={reject}
              disabled={Boolean(busy) || !rejectReason.trim()}
            >
              驳回重写
            </button>
          </div>
        </>
      )}
      <Link className="disc-design-full-link" to={`/workstation/${runId}?view=architecture`}>
        在工作台查看完整设计与评审
      </Link>
    </div>
  );
}

/**
 * Composes the whole discussion flow: progress bar, idea composer, chat + score panel,
 * approval dialog and the approved-spec summary. All state comes from the server-backed
 * `useDiscussionSession` hook; nothing is cached in browser storage.
 */
export function DiscussionView({
  projectId,
  actorBotId,
  members,
  bots,
  onInvite,
  onPlanReady,
}: DiscussionViewProps) {
  const { loading, error, session, sessions, messages, timeline, reviews, connection, refresh } =
    useDiscussionSession(projectId, actorBotId);
  const stage = deriveStage(session);
  const controlFlags = discussionControlFlags(session, actorBotId);
  const activeSessionId = session?.session_id ?? "";

  const [approvalOpen, setApprovalOpen] = useState(false);
  const [specOpen, setSpecOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<DiscussionPendingAction | null>(null);
  const [actionError, setActionError] = useState("");
  const [supplement, setSupplement] = useState("");
  const [planState, setPlanState] = useState<{ sessionId: string; status: PlanStatus }>();
  const headingId = useId();
  const actionBusyRef = useRef(false);
  const actionBusy = pendingAction !== null;
  // Latest session id, compared after every await so a response for a previous
  // project/session can never write an error, refresh, or clear a new draft.
  const sessionIdRef = useRef(activeSessionId);
  sessionIdRef.current = activeSessionId;

  useEffect(() => {
    // Switching sessions abandons the old action UI; the old promise still
    // resolves, but its guarded handlers will no longer touch this session.
    actionBusyRef.current = false;
    setPendingAction(null);
    setActionError("");
  }, [activeSessionId]);

  // Auto-open the approval dialog once per approval stage; a user close must not reopen it.
  const autoOpenedRef = useRef<string | null>(null);
  useEffect(() => {
    if (stage !== "approval" || !session) {
      autoOpenedRef.current = null;
      return;
    }
    if (autoOpenedRef.current === session.session_id) return;
    autoOpenedRef.current = session.session_id;
    setApprovalOpen(true);
  }, [stage, session]);

  useEffect(() => {
    if (stage !== "approval") setApprovalOpen(false);
    if (stage !== "approved" && stage !== "design") setSpecOpen(false);
  }, [stage]);

  const proposalCache = useRef(new Map<string, Promise<string>>());
  const sessionId = session?.session_id ?? "";
  const loadProposalBody = useCallback(
    (proposalId: string, sourceId = sessionId): Promise<string> => {
      if (!sourceId) return Promise.resolve(UNSEALED_BODY_TEXT);
      const key = `${actorBotId}:${sourceId}:${proposalId}`;
      const cached = proposalCache.current.get(key);
      if (cached) return cached;
      const pending = api
        .discussionProposals(sourceId, actorBotId)
        .then((result) => {
          const items = Array.isArray(result?.items) ? result.items : [];
          const found = items.find((item) => item?.proposal_id === proposalId);
          if (!found?.body_md) proposalCache.current.delete(key);
          return found?.body_md ?? UNSEALED_BODY_TEXT;
        })
        .catch((err) => {
          proposalCache.current.delete(key);
          throw err;
        });
      proposalCache.current.set(key, pending);
      return pending;
    },
    [sessionId, actorBotId],
  );

  const withSession = async (
    action: (sessionId: string) => Promise<unknown>,
    pending: DiscussionPendingAction,
  ) => {
    if (!session || actionBusyRef.current) return false;
    const requestSessionId = session.session_id;
    actionBusyRef.current = true;
    setPendingAction(pending);
    setActionError("");
    try {
      await action(requestSessionId);
      if (sessionIdRef.current !== requestSessionId) return false;
      refresh();
      return true;
    } catch (err) {
      if (sessionIdRef.current !== requestSessionId) return false;
      const { text, refresh: shouldRefresh } = classifyControlError(err);
      if (shouldRefresh) refresh();
      setActionError(text);
      return false;
    } finally {
      actionBusyRef.current = false;
      if (sessionIdRef.current === requestSessionId) setPendingAction(null);
    }
  };

  const pause = () =>
    withSession((id) => {
      const revision = session?.control_revision;
      return revision === undefined
        ? api.pauseDiscussion(id, actorBotId)
        : api.pauseDiscussion(id, actorBotId, revision);
    }, "pause");
  const resume = (skipBotIds?: string[]) =>
    withSession((id) => {
      const revision = session?.control_revision;
      return api.resumeDiscussion(
        id,
        {
          skip_bot_ids: skipBotIds,
          ...(revision === undefined ? {} : { expected_revision: revision }),
        },
        actorBotId,
      );
    }, "resume");
  const terminate = () =>
    withSession((id) => api.terminateDiscussion(id, actorBotId), "terminate");
  const requireRevision = (): number => {
    const revision = session?.control_revision;
    if (revision === undefined) throw new Error("控制版本缺失，请刷新后重试");
    return revision;
  };
  const endRound = (reason: string) =>
    withSession(
      (id) =>
        api.endDiscussionRound(
          id,
          { expected_revision: requireRevision(), reason, confirm: true },
          actorBotId,
        ),
      "end-round",
    );
  const startRound = async () => {
    if (!session || actionBusyRef.current) return false;
    const requestSessionId = session.session_id;
    const revision = session.control_revision;
    if (revision === undefined) {
      setActionError("控制版本缺失，请刷新后重试。");
      return false;
    }
    actionBusyRef.current = true;
    setPendingAction("start-round");
    setActionError("");
    try {
      try {
        await api.startDiscussionRound(
          requestSessionId,
          { expected_revision: revision },
          actorBotId,
        );
      } catch (err) {
        if (sessionIdRef.current !== requestSessionId) return false;
        const { text, refresh: shouldRefresh } = classifyControlError(err);
        if (shouldRefresh) refresh();
        setActionError(text);
        return false;
      }
      if (sessionIdRef.current !== requestSessionId) return false;
      try {
        // rounds/start only prepares the round; the driver starts explicitly.
        await api.runDiscussion(requestSessionId, actorBotId);
      } catch {
        if (sessionIdRef.current !== requestSessionId) return false;
        // The round already exists: never re-issue rounds/start and create a
        // second one; refresh the true state and let the user retry /run.
        setActionError("新轮已创建，但未能成功启动；已刷新真实状态，请稍后重试启动。");
        refresh();
        return false;
      }
      if (sessionIdRef.current !== requestSessionId) return false;
      refresh();
      return true;
    } finally {
      actionBusyRef.current = false;
      if (sessionIdRef.current === requestSessionId) setPendingAction(null);
    }
  };

  useEffect(() => {
    if (!session?.pause_requested || session.paused) return;
    const timer = window.setInterval(() => refresh(), 1500);
    return () => window.clearInterval(timer);
  }, [refresh, session?.pause_requested, session?.paused]);

  const activeMembers = members.filter((member) => member.status === "active");
  const participantBotIds = activeMembers.map((member) => member.bot_id);
  const hasLeader = activeMembers.some((member) => member.is_leader);
  const canSupplement = Boolean(session && CHAT_STAGES.includes(stage) && stage !== "terminated");

  return (
    <section className="disc-view" data-testid="disc-view" data-stage={stage} aria-labelledby={headingId}>
      {loading && !session && (
        <p className="disc-view-status" role="status" data-testid="disc-loading">
          正在加载讨论…
        </p>
      )}
      {error && (
        <p className="disc-view-error" role="alert" data-testid="disc-error">
          讨论加载失败：{error}
        </p>
      )}
      {connection === "error" && (
        <p className="disc-connection-hint" role="status" data-testid="disc-connection-hint">
          实时连接不可用，正在尝试重连或轮询
        </p>
      )}
      {actionError && (
        <p className="disc-view-error" role="alert" data-testid="disc-action-error">
          {actionError}
        </p>
      )}

      {stage === "approval" && (
        <ApprovalBanner round={session?.current_round} onOpen={() => setApprovalOpen(true)} />
      )}

      <div className="disc-layout" data-testid="disc-layout">
        <section className="disc-conversation glass-panel" aria-labelledby={headingId}>
          <header className="disc-conversation-head">
            <h2 id={headingId}><CommentOutlined aria-hidden /> 项目讨论</h2>
            <span className="disc-tag is-muted">
              {stage === "terminated"
                ? controlFlags.budgetExhausted
                  ? "预算已用尽"
                  : "已结束"
                : controlFlags.manual
                  ? controlFlags.settledManual
                    ? "人工结束本轮"
                    : "正在结束本轮"
                  : session?.paused
                    ? "已暂停"
                    : stage === "approval"
                      ? "等待确认"
                      : stage === "approved"
                        ? "规格已确认"
                        : stage === "idea"
                          ? "待开始"
                          : "讨论中"}
            </span>
            {session && CHAT_STAGES.includes(stage) && (
              <DiscussionControls
                session={session}
                busy={actionBusy}
                canControl={controlFlags.canControl}
                pendingAction={pendingAction}
                onPause={pause}
                onResume={resume}
                onTerminate={terminate}
                onEndRound={endRound}
                onStartRound={startRound}
              />
            )}
          </header>
          <DiscussionChat
            timeline={timeline}
            bots={bots}
            stage={stage}
            session={session}
            sessions={sessions}
            loadProposalBody={loadProposalBody}
            emptyText={stage === "idea" ? "你想让团队做什么？" : undefined}
          />
          {stage === "idea" && !loading && !error && (
            <IdeaComposer
              key={sessionId || projectId}
              projectId={projectId}
              actorBotId={actorBotId}
              participantBotIds={participantBotIds}
              memberCount={activeMembers.length}
              hasLeader={hasLeader}
              draft={session?.status === "draft" ? session : undefined}
              onInvite={onInvite}
              onStarted={refresh}
            />
          )}
          {canSupplement && (
            <form className="disc-composer disc-supplement" onSubmit={async (event) => {
              event.preventDefault();
              const value = supplement.trim();
              if (value && await withSession((id) => api.supplementDiscussion(id, value, actorBotId), "supplement")) {
                setSupplement("");
              }
            }}>
              <label className="disc-composer-field">
                <span className="disc-composer-label">补充信息</span>
                <textarea
                  className="disc-composer-input"
                  rows={2}
                  maxLength={MAX_IDEA_LENGTH}
                  value={supplement}
                  onChange={(event) => setSupplement(event.target.value)}
                  placeholder="补充范围、约束或验收条件"
                  disabled={actionBusy}
                />
              </label>
              <div className="disc-composer-actions">
                <span className="disc-composer-hint">提交后会中断当前讨论，Agent 将按补充后的需求重新讨论。</span>
                <button type="submit" className="disc-btn disc-plan-link" disabled={actionBusy || !supplement.trim()}>
                  <SendOutlined aria-hidden /> 发送补充
                </button>
              </div>
            </form>
          )}
        </section>
        <aside className="disc-side" aria-label="讨论进度和产物">
          <StageBar
            stage={stage}
            round={session?.current_round}
            planReady={planState?.sessionId === sessionId && planState.status === "ready"}
            planFailed={planState?.sessionId === sessionId && planState.status === "failed"}
          />
          {session && CHAT_STAGES.includes(stage) && (
            <>
              {stage === "terminated" && (
                <p className="disc-readonly-note" role="status" data-testid="disc-readonly-note">
                  {controlFlags.budgetExhausted
                    ? "轮数或预算已用尽，讨论已停止；消息和评分仍可查看，可查看历史或使用补充入口。"
                    : "讨论已终止，消息和评分仍可查看。"}
                </p>
              )}
              <ScorePanel
                session={session}
                reviews={reviews}
                messages={messages}
                bots={bots}
                busy={actionBusy || stage === "terminated"}
                showControls={false}
                onPause={pause}
                onResume={resume}
                onTerminate={terminate}
              />
            </>
          )}
          {stage === "design" && (
            <section className="disc-spec-summary glass-panel" data-testid="disc-design-summary">
              <DiscussionDesign
                key={sessionId}
                sessionId={sessionId}
                actorBotId={actorBotId}
                runIdHint={session?.workflow?.run_id || ""}
                onApproved={refresh}
              />
              <button type="button" className="disc-button-secondary disc-design-spec-link" onClick={() => setSpecOpen(true)}>
                查看需求规格
              </button>
            </section>
          )}
          {stage === "approved" && (
            <section className="disc-spec-summary glass-panel" data-testid="disc-spec-summary">
              <div className="disc-spec-summary-actions">
                <DiscussionPlan
                  key={sessionId}
                  sessionId={sessionId}
                  actorBotId={actorBotId}
                  onStatusChange={(status) => {
                    setPlanState({ sessionId, status });
                    if (status === "ready") onPlanReady?.();
                  }}
                />
                <button type="button" className="disc-button-secondary" onClick={() => setSpecOpen(true)}>
                  查看需求规格
                </button>
              </div>
            </section>
          )}
        </aside>
      </div>

      {(stage === "approved" || stage === "design") && (
        <SpecViewer open={specOpen} onClose={() => setSpecOpen(false)} sessions={sessions} />
      )}

      {stage === "approval" && session && (
        <SpecApprovalDialog
          open={approvalOpen}
          projectId={projectId}
          actorBotId={actorBotId}
          session={session}
          sessions={sessions}
          reviews={reviews}
          onClose={() => setApprovalOpen(false)}
          onApproved={() => {
            setApprovalOpen(false);
            refresh();
          }}
          onRestarted={() => {
            setApprovalOpen(false);
            refresh();
          }}
        />
      )}
    </section>
  );
}

export default DiscussionView;
