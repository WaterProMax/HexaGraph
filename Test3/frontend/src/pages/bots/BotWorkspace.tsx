import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { BotInstance, BotPatch, MemoryRecord, SkillDefinition } from "../../api/types";
import type { LoadState } from "../../components/AppShell";
import { BotAvatar } from "../../components/BotAvatar";
import { BotAvatarPicker } from "../../components/BotAvatarPicker";
import { BotForm, type ProviderOption } from "./BotForm";

export type BotTab = "config" | "memory" | "projects";

export type BotWorkspaceProps = {
  bot: BotInstance;
  providerOptions: ProviderOption[];
  skillOptions: SkillDefinition[];
  loadState: LoadState;
  onSave: (draft: BotPatch) => void | Promise<void>;
  onArchive: () => void | Promise<void>;
};

const TABS: Array<{ key: BotTab; label: string }> = [
  { key: "config", label: "配置与模型" },
  { key: "memory", label: "个人记忆" },
  { key: "projects", label: "所属项目" },
];

const EMPTY_SHA = "0".repeat(64);

function BotMemoryTab({ bot }: { bot: BotInstance }) {
  const [state, setState] = useState<LoadState>("loading");
  const [items, setItems] = useState<MemoryRecord[]>([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
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
    try {
      await api.createMemory(
        {
          owner_bot_id: bot.bot_id,
          visibility: "private",
          sources: [{ kind: "note", ref: "ui", sha: EMPTY_SHA }],
          body: { text: text.trim() },
          title: title.trim() || text.trim().slice(0, 24),
        },
        bot.bot_id,
      );
      setTitle("");
      setText("");
      await load();
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setState("forbidden");
      else {
        setError(err?.message || "保存记忆失败");
        setState("error");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="surface bot-memory-tab" data-testid="bot-panel-memory" style={{ padding: 16 }}>
      <div className="section-title">
        <span>个人记忆（private）</span>
        <span className="hint mono">{bot.bot_id.slice(0, 8)}</span>
      </div>
      <p className="muted">只对当前 Bot 可见；需要 X-Bot-Id 等于该 Bot。项目共享记忆在项目工作台里。</p>

      {state === "loading" && <div className="well muted" data-testid="bot-memory-loading">正在加载记忆…</div>}
      {state === "error" && (
        <div className="well" data-testid="bot-memory-error">
          记忆加载失败：{error}
        </div>
      )}
      {state === "forbidden" && (
        <div className="well" data-testid="bot-memory-forbidden">
          没有查看该 Bot 记忆的权限（403 memory_forbidden）。
        </div>
      )}
      {state === "empty" && (
        <div className="well muted" data-testid="bot-memory-empty">
          还没有个人记忆。
        </div>
      )}

      {items.length > 0 && (
        <ul className="memory-list">
          {items.map((memory) => (
            <li key={`${memory.mem_id}-${memory.version}`} className="memory-item">
              <span className="memory-title">{memory.title || memory.mem_id.slice(0, 8)}</span>
              <span className={`chip status-${memory.status}`}>{memory.status}</span>
              <span className="hint mono">v{memory.version}</span>
            </li>
          ))}
        </ul>
      )}

      {(state === "ready" || state === "empty") && (
        <div className="memory-compose">
          <input
            aria-label="记忆标题"
            placeholder="标题（可选）"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <textarea
            aria-label="记忆内容"
            rows={3}
            placeholder="写下这个 Bot 的个人笔记；不要放密钥明文"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="button" className="chip" onClick={create} disabled={saving || !text.trim()}>
            {saving ? "保存中…" : "保存为 pending"}
          </button>
        </div>
      )}
    </section>
  );
}

function BotProjectsTab({ bot }: { bot: BotInstance }) {
  const [state, setState] = useState<LoadState>("loading");
  const [rows, setRows] = useState<Array<{ id: string; name: string; role: string; leader: boolean }>>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setState("loading");
      try {
        const projects = await api.projects();
        const list: any[] = Array.isArray(projects) ? projects : [];
        const resolved = await Promise.all(
          list.map(async (project) => {
            try {
              const members = await api.memberships(String(project.id));
              const mine = (Array.isArray(members?.items) ? members.items : []).find(
                (member: any) => member.bot_id === bot.bot_id,
              );
              return mine
                ? { id: String(project.id), name: String(project.name), role: String(mine.role_in_project), leader: Boolean(mine.is_leader) }
                : null;
            } catch {
              return null;
            }
          }),
        );
        if (cancelled) return;
        const clean = resolved.filter(Boolean) as Array<{ id: string; name: string; role: string; leader: boolean }>;
        setRows(clean);
        setState(clean.length === 0 ? "empty" : "ready");
      } catch (err: any) {
        if (cancelled) return;
        setError(err?.message || "项目加载失败");
        setState("error");
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [bot.bot_id]);

  return (
    <section className="surface" data-testid="bot-panel-projects" style={{ padding: 16 }}>
      <div className="section-title">
        <span>所属项目</span>
        <span className="hint mono">{rows.length}</span>
      </div>
      {state === "loading" && <div className="well muted">正在读取项目成员关系…</div>}
      {state === "error" && <div className="well">项目加载失败：{error}</div>}
      {state === "empty" && <div className="well muted">这个 Bot 还没有加入任何项目。</div>}
      {rows.length > 0 && (
        <ul className="bot-project-list">
          {rows.map((row) => (
            <li key={row.id}>
              <Link to={`/projects/${row.id}`} className="bot-project-row">
                <span className="bot-project-name">{row.name}</span>
                <span className="chip">{row.role}</span>
                {row.leader && <span className="chip status-published">Leader</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function BotWorkspace({ bot, providerOptions, skillOptions, loadState, onSave, onArchive }: BotWorkspaceProps) {
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
            skillOptions={skillOptions}
            loadState={loadState}
            onSubmit={onSave}
            onArchive={onArchive}
          />
        </section>
      )}
      {tab === "memory" && <BotMemoryTab bot={bot} />}
      {tab === "projects" && <BotProjectsTab bot={bot} />}
    </div>
  );
}

export default BotWorkspace;