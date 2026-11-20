import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  ArrowUpOutlined,
  ClearOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { BotInstance, ChatMessage } from "../../api/types";
import { BotAvatar } from "../../components/BotAvatar";

const STORAGE_PREFIX = "hexagraph.botChat.v1:";
const STORED_LIMIT = 100;

function readHistory(botId: string): ChatMessage[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + botId);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter(
          (item): item is ChatMessage =>
            item &&
            (item.role === "user" || item.role === "assistant") &&
            typeof item.content === "string",
        )
      : [];
  } catch {
    return [];
  }
}

function writeHistory(botId: string, messages: ChatMessage[]) {
  try {
    window.localStorage.setItem(
      STORAGE_PREFIX + botId,
      JSON.stringify(messages.slice(-STORED_LIMIT)),
    );
  } catch {
    // storage may be unavailable; the conversation just won't survive a reload
  }
}

/** 和单个 Bot 对话；历史保存在浏览器里，Bot 的个人记忆由后端注入。 */
export default function BotChatPage() {
  const { id = "" } = useParams();
  const [bot, setBot] = useState<BotInstance | null>(null);
  const [loadError, setLoadError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    setBot(null);
    setLoadError("");
    setError("");
    setDraft("");
    setMessages(readHistory(id));
    api
      .bot(id)
      .then((res) => {
        if (!cancelled) setBot(res as BotInstance);
      })
      .catch((err: any) => {
        if (!cancelled)
          setLoadError(
            err instanceof ApiError && err.status === 404
              ? "找不到这个 Bot"
              : err?.message || "加载失败",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, sending]);

  useEffect(() => {
    const node = composer.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 168)}px`;
  }, [draft, bot]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending || !bot) return;
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setDraft("");
    setError("");
    setSending(true);
    try {
      const res = await api.chatBot(id, history.slice(-40));
      const next = [
        ...history,
        { role: "assistant" as const, content: res.reply },
      ];
      setMessages(next);
      writeHistory(id, next);
    } catch (err: any) {
      // 失败时把这句话放回输入框，历史里不留悬空的用户消息
      setMessages(messages);
      setDraft(text);
      setError(
        err instanceof ApiError && err.category === "secret_in_body"
          ? "消息里含有密钥，不能发送"
          : err?.message || "发送失败，请重试",
      );
    } finally {
      setSending(false);
    }
  }, [draft, sending, bot, messages, id]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  };

  const clear = () => {
    setMessages([]);
    setError("");
    writeHistory(id, []);
  };

  if (loadError) {
    return (
      <div className="page bot-page" data-testid="bot-chat">
        <div
          className="well"
          data-testid="bot-chat-error"
          style={{ padding: "14px 16px" }}
        >
          {loadError}
        </div>
      </div>
    );
  }
  if (!bot) {
    return (
      <div className="page bot-page" data-testid="bot-chat">
        <div className="well muted" style={{ padding: "14px 16px" }}>
          正在加载…
        </div>
      </div>
    );
  }

  const archived = bot.status === "archived";
  return (
    <div className="bot-chat" data-testid="bot-chat">
      <header className="bot-chat-top">
        <span className="bot-chat-title">
          <BotAvatar bot={bot} size={26} />
          <span className="bot-chat-title-name">{bot.display_name}</span>
        </span>
        <div className="bot-chat-actions">
          <button
            type="button"
            className="bot-chat-icon"
            aria-label="清空对话"
            title="清空对话"
            onClick={clear}
            disabled={messages.length === 0}
          >
            <ClearOutlined />
          </button>
          <Link
            to={`/bots/${bot.bot_id}`}
            className="bot-chat-icon"
            aria-label="配置"
            title="配置"
            data-testid="bot-chat-config"
          >
            <SettingOutlined />
          </Link>
        </div>
      </header>

      <div
        className="bot-chat-scroll"
        ref={scroller}
        data-testid="bot-chat-messages"
      >
        <div className="bot-chat-column">
          {messages.length === 0 && !sending && (
            <div className="bot-chat-empty">
              <BotAvatar bot={bot} size={64} />
              <span>和 {bot.display_name} 说点什么</span>
            </div>
          )}
          {messages.map((message, index) => (
            <div key={index} className={`bot-chat-row ${message.role}`}>
              <div className="bot-chat-bubble">
                {message.role === "assistant" ? (
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                ) : (
                  message.content
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div
              className="bot-chat-row assistant"
              data-testid="bot-chat-pending"
            >
              <div className="bot-chat-bubble pending" aria-label="思考中">
                <span className="bot-chat-dots">
                  <i />
                  <i />
                  <i />
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bot-chat-dock">
        {error && (
          <div className="bot-chat-error" role="alert">
            {error}
          </div>
        )}
        <div className="bot-chat-compose">
          <textarea
            ref={composer}
            aria-label="消息"
            rows={1}
            placeholder={
              archived ? "这个 Bot 已归档" : `给 ${bot.display_name} 发消息`
            }
            value={draft}
            disabled={archived}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            type="button"
            className="bot-chat-send"
            aria-label="发送"
            onClick={() => void send()}
            disabled={archived || sending || !draft.trim()}
          >
            <ArrowUpOutlined />
          </button>
        </div>
      </div>
    </div>
  );
}
