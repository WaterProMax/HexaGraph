import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { BotInstance, BotPatch, MemoryRecord, SkillDefinition } from "../../api/types";
import type { LoadState } from "../../components/AppShell";
import { BotAvatar } from "../../components/BotAvatar";
import { BotAvatarPicker } from "../../components/BotAvatarPicker";
import { BotForm, type ProviderOption } from "./BotForm";

export type BotTab = "config" | "memory";

export type BotWorkspaceProps = {
  bot: BotInstance;
  providerOptions: ProviderOption[];
  onImportSkill?: (url: string) => Promise<SkillDefinition>;
  loadState: LoadState;
  onSave: (draft: BotPatch) => void | Promise<void>;
  onArchive: () => void | Promise<void>;
};

const TABS: Array<{ key: BotTab; label: string }> = [
  { key: "config", label: "配置与模型" },
  { key: "memory", label: "个人记忆" },
];

const EMPTY_SHA = "0".repeat(64);

function memoryText(memory: MemoryRecord): string {
  const text = (memory.body as { text?: unknown })?.text;
  if (typeof text === "string") return text;
  if (!memory.body || Object.keys(memory.body).length === 0) return memory.title;
  return JSON.stringify(memory.body ?? {}, null, 2);
}

function BotMemoryTab({ bot }: { bot: BotInstance }) {
  const [state, setState] = useState<LoadState>("loading");
  const [items, setItems] = useState<MemoryRecord[]>([]);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    setError("");
    try {
      const res = await api.memories({ owner_bot_id: bot.bot_id, visibility: "private" }, bot.bot_id);
      const list: MemoryRecord[] = Array.isArray(res?.items) ? res.items : [];
      setItems(list);
      setState(list.length === 0 ? "empty" : "ready");
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setState("forbidden");
      else {
        setError(err?.message || "记忆加载失败");
        setState("error");
      }
    }
  }, [bot.bot_id]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!text.trim()) return;
    setSaving(true);
    setFormError("");
    try {
      await api.createMemory(
        {
          owner_bot_id: bot.bot_id,
          visibility: "private",
          sources: [{ kind: "note", ref: "ui", sha: EMPTY_SHA }],
          body: { text: text.trim() },
          title: text.trim().slice(0, 24),
        },
        bot.bot_id,
      );
      setText("");
      await load();
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setState("forbidden");
      else setFormError(err instanceof ApiError && err.category === "secret_in_body" ? "内容里含有密钥，不能保存" : err?.message || "添加失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="bot-memory-box" data-testid="bot-panel-memory">
      <div className="bot-memory-scroll">
        {state === "loading" && <div className="bot-memory-state" data-testid="bot-memory-loading">正在加载…</div>}
        {state === "error" && (
          <div className="bot-memory-state" data-testid="bot-memory-error">
            加载失败：{error}
          </div>
        )}
        {state === "forbidden" && (
          <div className="bot-memory-state" data-testid="bot-memory-forbidden">
            没有查看该 Bot 记忆的权限
          </div>
        )}
        {state === "empty" && (
          <div className="bot-memory-state" data-testid="bot-memory-empty">
            暂无记忆
          </div>
        )}

        {items.map((memory) => (
          <article key={`${memory.mem_id}-${memory.version}`} className="bot-memory-entry">
            <p className="bot-memory-entry-body">{memoryText(memory)}</p>
          </article>
        ))}
      </div>

      {(state === "ready" || state === "empty") && (
        <div className="bot-memory-add">
          {formError && <span className="bot-memory-form-error" role="alert">{formError}</span>}
          <textarea
            aria-label="记忆内容"
            rows={2}
            placeholder="添加一条记忆"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="button" className="chip" onClick={create} disabled={saving || !text.trim()}>
            {saving ? "整理中…" : "添加"}
          </button>
        </div>
      )}
    </section>
  );
}

export function BotWorkspace({ bot, providerOptions, onImportSkill, loadState, onSave, onArchive }: BotWorkspaceProps) {
  const [tab, setTab] = useState<BotTab>("config");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [, setAvatarVersion] = useState(0);

  return (
    <div className="bot-workspace" data-testid="bot-workspace">
      <header className="bot-workspace-head">
        <BotAvatar bot={bot} size={56} />
        <div className="bot-workspace-title">
          <h1>{bot.display_name}</h1>
          <p className="mono muted">
            {bot.role_template} · {bot.model} · {bot.slot}
          </p>
        </div>
        <span className={`chip status-${bot.status}`}>{bot.status}</span>
        <Link to={`/bots/${bot.bot_id}/chat`} className="chip" data-testid="bot-open-chat">
          对话
        </Link>
        <button type="button" className="chip" data-testid="bot-avatar-change" onClick={() => setPickerOpen((open) => !open)}>
          更换头像
        </button>
      </header>

      {pickerOpen && (
        <BotAvatarPicker
          bot={bot}
          onChanged={() => setAvatarVersion((value) => value + 1)}
          onClose={() => setPickerOpen(false)}
        />
      )}

      <div className="subnav" role="tablist" aria-label="Bot 工作区">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            data-testid={`bot-tab-${item.key}`}
            className={`chip ${tab === item.key ? "active" : ""}`}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "config" && (
        <section data-testid="bot-panel-config">
          <BotForm
            mode="edit"
            initial={bot}
            providerOptions={providerOptions}
            onImportSkill={onImportSkill}
            loadState={loadState}
            onSubmit={onSave}
            onArchive={onArchive}
          />
        </section>
      )}
      {tab === "memory" && <BotMemoryTab bot={bot} />}
    </div>
  );
}

export default BotWorkspace;