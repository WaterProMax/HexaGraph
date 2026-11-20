import type { BotInstance } from "../../api/types";
import { BotAvatar } from "../../components/BotAvatar";

export type TeamMember = {
  bot_id: string;
  display_name: string;
  role_template: string;
  status: BotInstance["status"];
  role_in_project: string;
  is_leader: boolean;
};

export type TeamStripProps = {
  members: TeamMember[];
  actorBotId: string;
  onActorChange: (botId: string) => void;
  onManage: () => void;
};

export function TeamStrip({ members, actorBotId, onActorChange, onManage }: TeamStripProps) {
  return (
    <div className="team-strip" data-testid="team-strip">
      <div className="team-avatars" aria-label="项目成员">
        {members.length === 0 && <span className="muted">尚未加入 Bot</span>}
        {members.map((member) => (
          <span className={`team-member ${member.is_leader ? "is-leader" : ""}`} key={member.bot_id}>
            <BotAvatar bot={member} size={30} />
            {member.is_leader && <span className="team-leader-mark">Leader</span>}
          </span>
        ))}
      </div>
      {members.length > 0 && (
        <label className="team-actor">
          <span className="muted">当前操作身份</span>
          <select
            data-testid="actor-bot-select"
            aria-label="当前操作身份"
            value={actorBotId}
            onChange={(event) => onActorChange(event.target.value)}
          >
            {members.map((member) => (
              <option key={member.bot_id} value={member.bot_id}>
                {member.display_name}
                {member.is_leader ? " · Leader" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <button type="button" className="chip" data-testid="manage-members" onClick={onManage}>
        管理项目成员
      </button>
    </div>
  );
}

export default TeamStrip;