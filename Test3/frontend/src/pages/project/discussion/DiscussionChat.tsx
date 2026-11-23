import { useEffect, useRef, type UIEvent } from "react";
import { CommentOutlined } from "@ant-design/icons";
import type {
  BotInstance,
  DiscussionSession,
  DiscussionTimelineItem,
} from "../../../api/types";
import type { DiscussionStage } from "./deriveStage";
import { MessageBubble } from "./MessageBubble";

export type DiscussionChatProps = {
  timeline: DiscussionTimelineItem[];
  bots: BotInstance[];
  stage: DiscussionStage;
  session: DiscussionSession | null;
  loadProposalBody: (proposalId: string, sessionId?: string) => Promise<string>;
  sessions?: DiscussionSession[];
  emptyText?: string;
};

/** How far (px) the user may scroll away from the bottom before we stop following. */
export const STICK_THRESHOLD_PX = 120;

export function timelineItemKey(item: DiscussionTimelineItem): string {
  return item.type === "divider"
    ? `divider:${item.key}`
    : `message:${item.message.session_id}:${item.message.seq}`;
}

export function DiscussionChat({
  timeline, bots, session, sessions = [], loadProposalBody, emptyText = "还没有消息",
}: DiscussionChatProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottom = useRef(true);
  const lastKey = timeline.length > 0 ? timelineItemKey(timeline[timeline.length - 1]) : "";

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickToBottom.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lastKey, timeline.length]);

  function handleScroll(event: UIEvent<HTMLDivElement>) {
    const el = event.currentTarget;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distance <= STICK_THRESHOLD_PX;
  }

  return (
    <div
      className="disc-chat"
      data-testid="disc-chat"
      ref={scrollRef}
      onScroll={handleScroll}
      role="log"
      aria-live="polite"
      aria-label="讨论消息"
      tabIndex={0}
    >
      {timeline.length === 0 ? (
        <div className="disc-chat-empty">
          <CommentOutlined aria-hidden />
          <p>{emptyText}</p>
        </div>
      ) : (
        timeline.map((item) => {
          const sourceId = item.type === "message" ? item.message.session_id : undefined;
          const source = !sourceId || sourceId === session?.session_id
            ? session : sessions.find((entry) => entry.session_id === sourceId) ?? null;
          return (
            <div className="disc-chat-item" key={timelineItemKey(item)} data-item-type={item.type}>
              <MessageBubble
                item={item}
                bots={bots}
                session={source}
                loadProposalBody={(proposalId) => loadProposalBody(proposalId, sourceId)}
              />
            </div>
          );
        })
      )}
    </div>
  );
}

export default DiscussionChat;
