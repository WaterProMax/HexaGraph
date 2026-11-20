import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { BotInstance } from "../../api/types";
import { BotAvatar } from "../../components/BotAvatar";
import type { TeamMember } from "./TeamStrip";

export type ManageMembersDialogProps = {
  projectId: string;
  members: TeamMember[];
  allBots: BotInstance[];
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

function errorCategory(err: unknown): string {
  if (err instanceof ApiError) return err.category || `HTTP ${err.status}`;
  return (err as any)?.message || "unknown_error";
}

export function ManageMembersDialog({ projectId, members, allBots, onClose, onChanged }: ManageMembersDialogProps) {
  const [role, setRole] = useState("dev");
  const [candidate, setCandidate] = useState("");
  const [makeLeader, setMakeLeader] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const available = useMemo(
    () => allBots.filter((bot) => bot.status === "active" && !members.some((member) => member.bot_id === bot.bot_id)),
    [allBots, members],
  );

  const add = async () => {
    if (!candidate) return;
    setBusy(true);
    setError("");
    try {
      await api.addMembership(projectId, { bot_id: candidate, role_in_project: role || "dev", is_leader: makeLeader });
      setCandidate("");
      setMakeLeader(false);
      await onChanged();
    } catch (err) {
      setError(errorCategory(err));
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  const remove = async (botId: string) => {
    setBusy(true);
    setError("");
    try {
      await api.removeMembership(projectId, botId);
      await onChanged();
    } catch (err) {
      setError(errorCategory(err));
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  /**
   * The backend has no PATCH / leader transfer.  Keep every existing member:
   * drop the old leader, add it back as a regular member, then re-add the
   * target with is_leader=true.  Any failure reloads the list and surfaces the
   * error category instead of silently losing a member.
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
      setError(errorCategory(err));
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
          <span>管理项目成员</span>
          <button type="button" className="chip" aria-label="关闭成员管理" onClick={onClose}>
            关闭
          </button>
        </div>

        {error && (
          <div className="well members-error" role="alert">
            操作失败：{error}
          </div>
        )}

        <ul className="members-list">
          {members.length === 0 && <li className="muted">还没有成员。</li>}
          {members.map((member) => (
            <li key={member.bot_id} className="members-row">
              <BotAvatar bot={member} size={28} />
              <span className="members-name">{member.display_name}</span>
              <span className="chip">{member.role_in_project}</span>
              {member.is_leader && <span className="chip status-published">Leader</span>}
              <button
                type="button"
                className="chip"
                disabled={busy || member.is_leader}
                aria-label={`将 ${member.display_name} 设为 Leader`}
                onClick={() => promote(member.bot_id)}
              >
                设为 Leader
              </button>
              <button
                type="button"
                className="chip"
                disabled={busy}
                aria-label={`移出 ${member.display_name}`}
                onClick={() => remove(member.bot_id)}
              >
                移出
              </button>
            </li>
          ))}
        </ul>

        <div className="members-add">
          <div className="section-title">
            <span>添加成员</span>
          </div>
          <select aria-label="添加 Bot" value={candidate} onChange={(event) => setCandidate(event.target.value)}>
            <option value="">选择 Bot</option>
            {available.map((bot) => (
              <option key={bot.bot_id} value={bot.bot_id}>
                {bot.display_name} · {bot.role_template}
              </option>
            ))}
          </select>
          <input aria-label="项目角色" value={role} onChange={(event) => setRole(event.target.value)} placeholder="dev" />
          <label className="members-leader-toggle">
            <input type="checkbox" checked={makeLeader} onChange={(event) => setMakeLeader(event.target.checked)} />
            设为 Leader
          </label>
          <button type="button" className="chip" disabled={busy || !candidate} onClick={add} aria-label="添加成员">
            添加成员
          </button>
        </div>
      </div>
    </div>
  );
}

export default ManageMembersDialog;