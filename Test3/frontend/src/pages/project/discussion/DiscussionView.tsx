import { useCallback, useEffect, useId, useRef, useState } from "react";
import { CommentOutlined, SendOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { api } from "../../../api/client";
import type { BotInstance } from "../../../api/types";
import type { TeamMember } from "../TeamStrip";
import { ApprovalBanner } from "./ApprovalBanner";
import { DiscussionChat } from "./DiscussionChat";
import { IdeaComposer, MAX_IDEA_LENGTH } from "./IdeaComposer";
import { DiscussionControls, ScorePanel } from "./ScorePanel";
import { SpecApprovalDialog } from "./SpecApprovalDialog";
import { SpecViewer } from "./SpecViewer";
import { StageBar } from "./StageBar";
import { deriveStage, type DiscussionStage } from "./deriveStage";
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

  const [approvalOpen, setApprovalOpen] = useState(false);
  const [specOpen, setSpecOpen] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [supplement, setSupplement] = useState("");
  const [planState, setPlanState] = useState<{ sessionId: string; status: PlanStatus }>();
  const headingId = useId();
  const actionBusyRef = useRef(false);

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
    if (stage !== "approved") setSpecOpen(false);
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

  const withSession = async (action: (sessionId: string) => Promise<unknown>) => {
    if (!session || actionBusyRef.current) return;
    actionBusyRef.current = true;
    setActionBusy(true);
    setActionError("");
    try {
      await action(session.session_id);
      refresh();
      return true;
    } catch (err) {
      setActionError(actionErrorText(err));
    } finally {
      actionBusyRef.current = false;
      setActionBusy(false);
    }
  };

  const pause = () => withSession((id) => api.pauseDiscussion(id, actorBotId));
  const resume = (skipBotIds?: string[]) =>
    withSession((id) => api.resumeDiscussion(id, { skip_bot_ids: skipBotIds }, actorBotId));
  const terminate = () => withSession((id) => api.terminateDiscussion(id, actorBotId));

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
              {stage === "terminated" ? "已结束" : session?.paused ? "已暂停" : stage === "approval" ? "等待确认" :
                stage === "approved" ? "规格已确认" : stage === "idea" ? "待开始" : "讨论中"}
            </span>
            {session && CHAT_STAGES.includes(stage) && (
              <DiscussionControls
                session={session}
                busy={actionBusy || stage === "terminated"}
                onPause={pause}
                onResume={resume}
                onTerminate={terminate}
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
              if (value && await withSession((id) => api.supplementDiscussion(id, value, actorBotId))) {
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
                <p className="disc-readonly-note" role="status">讨论已终止，消息和评分仍可查看。</p>
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

      {stage === "approved" && (
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
