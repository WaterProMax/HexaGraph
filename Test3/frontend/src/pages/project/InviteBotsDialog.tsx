import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { BotInstance } from "../../api/types";
import { BotAvatar } from "../../components/BotAvatar";
import { roleLabel } from "../../lib/botRole";
import { memberErrorText } from "./memberErrors";
import type { TeamMember } from "./TeamStrip";

export type InviteBotsDialogProps = {
  projectId: string;
  members: TeamMember[];
  allBots: BotInstance[];
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

/**
 * Multi-select invite: the backend adds one member per request, so this posts
 * the selected bots one by one.  A failure never rolls back members that were
 * already added; the failed rows stay in the list with their reason.
 */
export function InviteBotsDialog({ projectId, members, allBots, onClose, onChanged }: InviteBotsDialogProps) {
  const [selected, setSelected] = useState<string[]>([]);
  const [leaderId, setLeaderId] = useState("");
  const [busy, setBusy] = useState(false);
  const [failures, setFailures] = useState<Record<string, string>>({});

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const available = useMemo(
    () => allBots.filter((bot) => bot.status === "active" && !members.some((member) => member.bot_id === bot.bot_id)),
    [allBots, members],
  );
  const hasLeader = members.some((member) => member.is_leader);

  // Members added by a previous (partially failed) submit leave the list.
  const picked = selected.filter((id) => available.some((bot) => bot.bot_id === id));
  const allSelected = available.length > 0 && picked.length === available.length;
  const effectiveLeader = !hasLeader && picked.includes(leaderId) ? leaderId : "";

  const toggle = (botId: string) => {
    setSelected((current) => (current.includes(botId) ? current.filter((id) => id !== botId) : [...current, botId]));
    if (leaderId === botId) setLeaderId("");
  };

  const toggleAll = () => {
    if (allSelected) {
      setSelected([]);
      setLeaderId("");
    } else {
      setSelected(available.map((bot) => bot.bot_id));
    }
  };

  const toggleLeader = (botId: string) => setLeaderId((current) => (current === botId ? "" : botId));

  const invite = async () => {
    if (picked.length === 0 || busy) return;
    setBusy(true);
    const nextFailures: Record<string, string> = {};
    for (const botId of picked) {
      const bot = available.find((item) => item.bot_id === botId);
      if (!bot) continue;
      try {
        await api.addMembership(projectId, {
          bot_id: botId,
          role_in_project: bot.role_template || "dev",
          is_leader: effectiveLeader === botId,
        });
      } catch (err) {
        nextFailures[botId] = memberErrorText(err);
      }
    }
    setFailures(nextFailures);
    setSelected(Object.keys(nextFailures));
    try {
      await onChanged();
    } finally {
      setBusy(false);
    }
    if (Object.keys(nextFailures).length === 0) onClose();
  };

  const failedCount = Object.keys(failures).length;

  return (
    <div className="members-dialog-backdrop" onClick={busy ? undefined : onClose}>
      <div
        className="surface members-dialog invite-dialog"
        data-testid="invite-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="邀请 Bot"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-title">
          <span>邀请 Bot 加入项目</span>
          <button type="button" className="chip" aria-label="关闭邀请" disabled={busy} onClick={onClose}>
            关闭
          </button>
        </div>

        {failedCount > 0 && (
          <div className="well members-error" role="alert">
            有 {failedCount} 个 Bot 邀请失败，其余已加入。可以修正后重试。
          </div>
        )}

        {available.length === 0 ? (
          <div className="well muted invite-empty" data-testid="invite-empty">
            没有可邀请的 Bot：所有可用的 Bot 都已经在项目里了。
            <Link to="/bots/new" onClick={onClose}>
              去新建 Bot
            </Link>
          </div>
        ) : (
          <>
            <label className="invite-all">
              <input type="checkbox" aria-label="全选" checked={allSelected} disabled={busy} onChange={toggleAll} />
              全选（{available.length}）
            </label>
            <ul className="members-list invite-list">
              {available.map((bot) => {
                const checked = picked.includes(bot.bot_id);
                return (
                  <li key={bot.bot_id} className={`members-row invite-row ${checked ? "is-selected" : ""}`}>
                    <label className="invite-pick">
                      <input
                        type="checkbox"
                        aria-label={`邀请 ${bot.display_name}`}
                        checked={checked}
                        disabled={busy}
                        onChange={() => toggle(bot.bot_id)}
                      />
                      <BotAvatar bot={bot} size={28} nativeTitle={false} />
                      <span className="members-name">{bot.display_name}</span>
                      <span className="chip">{roleLabel(bot.role_template)}</span>
                    </label>
                    {failures[bot.bot_id] && (
                      <span className="invite-fail" role="status">
                        {failures[bot.bot_id]}
                      </span>
                    )}
                    {!hasLeader && checked && (
                      <label className="members-leader-toggle">
                        <input
                          type="checkbox"
                          aria-label={`将 ${bot.display_name} 设为 Leader`}
                          checked={effectiveLeader === bot.bot_id}
                          disabled={busy}
                          onChange={() => toggleLeader(bot.bot_id)}
                        />
                        设为 Leader
                      </label>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}

        <div className="invite-actions">
          <button
            type="button"
            className="chip primary"
            data-testid="invite-submit"
            disabled={busy || picked.length === 0}
            onClick={invite}
          >
            {busy ? "邀请中…" : `邀请 ${picked.length} 个 Bot`}
          </button>
        </div>
      </div>
    </div>
  );
}

export default InviteBotsDialog;
