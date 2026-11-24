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
  onInvite: () => void;
  onManage: () => void;
  showActions?: boolean;
};

export function TeamStrip({ members, onInvite, onManage, showActions = true }: TeamStripProps) {
  return (
    <div className="team-strip" data-testid="team-strip">
      {members.length > 0 && (
        <div className="team-avatars" aria-label="项目成员">
          {members.map((member) => (
            <span className={`team-member ${member.is_leader ? "is-leader" : ""}`} key={member.bot_id}>
              <BotAvatar bot={member} size={26} />
            </span>
          ))}
        </div>
      )}
      {showActions && (
        <>
          <button type="button" className="chip primary" data-testid="invite-bots" onClick={onInvite}>
            邀请 Bot
          </button>
          <button type="button" className="chip" data-testid="manage-members" onClick={onManage}>
            管理项目成员
          </button>
        </>
      )}
    </div>
  );
}

export default TeamStrip;