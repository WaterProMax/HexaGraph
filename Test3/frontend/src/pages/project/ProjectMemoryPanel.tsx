import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { LoadState } from "../../components/AppShell";
import type { MemoryRecord } from "../../api/types";

export type ProjectMemoryPanelProps = {
  projectId: string;
  actorBotId: string;
  isLeader: boolean;
};

const EMPTY_SHA = "0".repeat(64);

export function ProjectMemoryPanel({ projectId, actorBotId, isLeader }: ProjectMemoryPanelProps) {
  const [state, setState] = useState<LoadState>("loading");
  const [items, setItems] = useState<MemoryRecord[]>([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!actorBotId) {
      setState("empty");
      return;
    }
    setState("loading");
    setError("");
    try {
      const res = await api.memories({ project_id: projectId, visibility: "project" }, actorBotId);
      const list: MemoryRecord[] = Array.isArray(res?.items) ? res.items : [];
      setItems(list);
      setState(list.length === 0 ? "empty" : "ready");
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setState("forbidden");
      else {
        setError(err?.message || "项目记忆加载失败");
        setState("error");
      }
    }
  }, [actorBotId, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!text.trim() || !actorBotId) return;
    setBusy(true);
    try {
      await api.createMemory(
        {
          owner_bot_id: actorBotId,
          project_id: projectId,
          visibility: "project",
          sources: [{ kind: "note", ref: "ui", sha: EMPTY_SHA }],
          body: { text: text.trim() },
          title: title.trim() || text.trim().slice(0, 24),
        },
        actorBotId,
      );
      setTitle("");
      setText("");
      await load();
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setState("forbidden");
      else {
        setError(err?.message || "保存项目记忆失败");
        setState("error");
      }
    } finally {
      setBusy(false);
    }
  };

  const publish = async (memory: MemoryRecord) => {
    setBusy(true);
    try {
      await api.publishMemory(memory.mem_id, memory.version, actorBotId);
      await load();
    } catch (err: any) {
      setError(err?.message || "晋升失败");
      setState("error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="surface project-memory-panel" data-testid="project-memory-panel">
      <div className="section-title">
        <span>项目共享记忆（project）</span>
        <span className="hint mono">{items.length}</span>
      </div>
      <p className="muted">成员可读；晋升为 published 需要 Leader 人工操作。</p>

      {state === "loading" && <div className="well muted" data-testid="project-memory-loading">正在加载项目记忆…</div>}
      {state === "error" && (
        <div className="well" data-testid="project-memory-error">
          项目记忆加载失败：{error}
        </div>
      )}
      {state === "forbidden" && (
        <div className="well" data-testid="project-memory-forbidden">
          当前身份不是项目成员，无法读取项目记忆（403 memory_forbidden）。
        </div>
      )}
      {state === "empty" && (
        <div className="well muted" data-testid="project-memory-empty">
          还没有项目记忆。
        </div>
      )}

      {items.length > 0 && (
        <ul className="memory-list">
          {items.map((memory) => (
            <li key={`${memory.mem_id}-${memory.version}`} className="memory-item">
              <span className="memory-title">{memory.title || memory.mem_id.slice(0, 8)}</span>
              <span className={`chip status-${memory.status}`}>{memory.status}</span>
              <span className="hint mono">v{memory.version}</span>
              {isLeader && memory.status === "pending" && (
                <button
                  type="button"
                  className="chip"
                  disabled={busy}
                  data-testid={`publish-memory-${memory.mem_id}`}
                  onClick={() => publish(memory)}
                >
                  晋升为 published
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {(state === "ready" || state === "empty") && actorBotId && (
        <div className="memory-compose">
          <input aria-label="项目记忆标题" placeholder="标题（可选）" value={title} onChange={(event) => setTitle(event.target.value)} />
          <textarea
            aria-label="项目记忆内容"
            rows={2}
            placeholder="写进项目共享记忆；不要放密钥明文"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="button" className="chip" disabled={busy || !text.trim()} onClick={create}>
            新建 project 记忆
          </button>
        </div>
      )}
    </div>
  );
}

export default ProjectMemoryPanel;