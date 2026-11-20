import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { BotAvatar } from "../../components/BotAvatar";
import { roleLabel } from "../../lib/botRole";
import { memberErrorText } from "./memberErrors";
import type { TeamMember } from "./TeamStrip";

export type ManageMembersDialogProps = {
  projectId: string;
  members: TeamMember[];
  onClose: () => void;
  onInvite: () => void;
  onChanged: () => void | Promise<void>;
};

/** Manage existing members (leader / remove). Adding bots goes through the invite dialog. */
export function ManageMembersDialog({ projectId, members, onClose, onInvite, onChanged }: ManageMembersDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const remove = async (botId: string) => {
    setBusy(true);
    setError("");
    try {
      await api.removeMembership(projectId, botId);
      await onChanged();
    } catch (err) {
      setError(memberErrorText(err));
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  /**
   * The backend has no PATCH / leader transfer.  Keep every existing member:
   * drop the old leader, add it back as a regular member, then re-add the
   * target with is_leader=true.  Any failure reloads the list and surfaces the
   * error instead of silently losing a member.
   */
  const promote = async (targetBotId: string) => {
    const oldLeader = members.find((member) => member.is_leader);
    const target = members.find((member) => member.bot_id === targetBotId);
    if (!target || oldLeader?.bot_id === targetBotId) return;
    setBusy(true);
    setError("");
    try {
      if (oldLeader) {
        await api.removeMembership(projectId, oldLeader.bot_id);
        await api.addMembership(projectId, {
          bot_id: oldLeader.bot_id,
          role_in_project: oldLeader.role_in_project,
          is_leader: false,
        });
      }
      await api.removeMembership(projectId, target.bot_id);
      await api.addMembership(projectId, {
        bot_id: target.bot_id,
        role_in_project: target.role_in_project,
        is_leader: true,
      });
      await onChanged();
    } catch (err) {
      setError(memberErrorText(err));
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="members-dialog-backdrop" onClick={onClose}>
      <div
        className="surface members-dialog"
        data-testid="members-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="管理项目成员"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-title">
          <span>
            管理项目成员
            <span className="hint members-count">{members.length} 人</span>
          </span>
          <button type="button" className="chip" aria-label="关闭成员管理" onClick={onClose}>
            关闭
          </button>
        </div>

        {error && (
          <div className="well members-error" role="alert">
            操作失败：{error}
          </div>
        )}

        {members.length === 0 ? (
          <div className="well muted members-empty" data-testid="members-empty">
            项目里还没有成员，邀请 Bot 加入后才能开始协作。
          </div>
        ) : (
          <ul className="members-list">
            {members.map((member) => (
              <li key={member.bot_id} className="members-row">
                <BotAvatar bot={member} size={34} nativeTitle={false} />
                <div className="members-info">
                  <span className="members-name">
                    {member.display_name}
                    {member.is_leader && <span className="members-badge">Leader</span>}
                  </span>
                  <span className="members-sub">{roleLabel(member.role_in_project)}</span>
                </div>
                <div className="members-actions">
                  {!member.is_leader && (
                    <button
                      type="button"
                      className="chip"
                      disabled={busy}
                      aria-label={`将 ${member.display_name} 设为 Leader`}
                      onClick={() => promote(member.bot_id)}
                    >
                      设为 Leader
                    </button>
                  )}
                  <button
                    type="button"
                    className="chip danger"
                    disabled={busy}
                    aria-label={`移出 ${member.display_name}`}
                    onClick={() => remove(member.bot_id)}
                  >
                    移出
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="members-footer">
          <span className="muted">想加入更多 Bot？</span>
          <button type="button" className="chip primary" data-testid="members-invite-more" disabled={busy} onClick={onInvite}>
            邀请更多 Bot
          </button>
        </div>
      </div>
    </div>
  );
}

export default ManageMembersDialog;
