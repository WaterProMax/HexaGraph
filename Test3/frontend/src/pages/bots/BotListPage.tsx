import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { BotInstance, SkillDefinition } from "../../api/types";
import type { LoadState } from "../../components/AppShell";
import { BotAvatar } from "../../components/BotAvatar";
import { BotForm, type ProviderOption } from "./BotForm";
import { BotWorkspace } from "./BotWorkspace";

export type BotListPageProps = { mode?: "list" | "create" | "edit" };

function slotsToOptions(models: any): ProviderOption[] {
  const slots = models?.slots;
  if (!slots || typeof slots !== "object") return [];
  return Object.entries(slots as Record<string, any>).map(([slot, value]) => ({
    slot,
    model: String(value?.model ?? ""),
  }));
}

export default function BotListPage({ mode = "list" }: BotListPageProps) {
  const params = useParams();
  const navigate = useNavigate();
  const botId = params.id || "";
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorText, setErrorText] = useState("");
  const [bots, setBots] = useState<BotInstance[]>([]);
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [initial, setInitial] = useState<BotInstance | undefined>();
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoadState("loading");
    setErrorText("");
    try {
      const [botList, skillList, models] = await Promise.all([api.bots(), api.skills(), api.models()]);
      const items: BotInstance[] = Array.isArray(botList?.items) ? botList.items : [];
      setBots(items);
      setSkills(Array.isArray(skillList?.items) ? skillList.items : []);
      setProviders(slotsToOptions(models));
      if (mode === "edit") {
        const record = botId ? ((await api.bot(botId)) as BotInstance) : undefined;
        setInitial(record);
        setLoadState(record ? "ready" : "empty");
        return;
      }
      if (mode === "create") {
        setLoadState("ready");
        return;
      }
      setLoadState(items.length === 0 ? "empty" : "ready");
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setLoadState("forbidden");
      else {
        setErrorText(err?.message || "Bot 列表加载失败");
        setLoadState("error");
      }
    }
  }, [mode, botId]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  const submit = async (draft: Record<string, unknown>) => {
    try {
      if (mode === "create") await api.createBot(draft as any);
      else if (botId) await api.patchBot(botId, draft as any);
      navigate("/bots");
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) setLoadState("forbidden");
      else {
        setErrorText(err?.message || "保存失败");
        setLoadState("error");
      }
    }
  };

  const archive = async () => {
    if (!botId) return;
    try {
      await api.archiveBot(botId);
      navigate("/bots");
    } catch (err: any) {
      setErrorText(err?.message || "归档失败");
      setLoadState("error");
    }
  };

  return (
    <div className="page">
      <div className="page-head bot-page-head">
        <div>
          <h1>Bot</h1>
          <p>每个 Bot 自带模型与 Skill 版本绑定；密钥只记录环境变量名。</p>
        </div>
        <Link className="chip" to="/bots/new" data-testid="bots-new-link">
          + 新建 Bot
        </Link>
      </div>

      {loadState === "loading" && (
        <div className="well muted" data-testid="bots-loading" style={{ padding: "14px 16px" }}>
          正在加载 Bot…
        </div>
      )}
      {loadState === "error" && (
        <div className="well" data-testid="bots-error" style={{ padding: "14px 16px" }}>
          加载失败：{errorText}
          <button type="button" className="chip" style={{ marginLeft: 12 }} onClick={() => setReloadKey((n) => n + 1)}>
            重试
          </button>
        </div>
      )}
      {loadState === "forbidden" && (
        <div className="well" data-testid="bots-forbidden" style={{ padding: "14px 16px" }}>
          没有查看 Bot 的权限（403）。
        </div>
      )}
      {loadState === "empty" && mode === "list" && (
        <div className="well muted" data-testid="bots-empty" style={{ padding: "14px 16px" }}>
          还没有 Bot。先创建一个，再把它加入项目。
        </div>
      )}

      {(loadState === "ready" || loadState === "empty") && mode === "list" && (
        <>
          <div className="section-title">
            <span>全部 Bot</span>
            <span className="hint mono">{bots.length}</span>
          </div>
          <div className="grid-list">
            {bots.map((bot) => (
              <Link
                className="list-card bot-list-card"
                key={bot.bot_id}
                to={`/bots/${bot.bot_id}`}
                style={{ textDecoration: "none" }}
              >
                <BotAvatar bot={bot} size={40} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="bot-list-name">{bot.display_name}</div>
                  <div className="mono muted">
                    {bot.role_template} · {bot.model} · {bot.slot}
                  </div>
                  <div className="mono muted">
                    {bot.skill_bindings.map((binding) => `${binding.skill_id}@${binding.pinned_version}`).join(", ") ||
                      "未绑定 Skill"}
                  </div>
                </div>
                <span className={`chip status-${bot.status}`}>{bot.status}</span>
              </Link>
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <Link className="chip" to="/bots/new">
              新建 Bot
            </Link>
          </div>
        </>
      )}

      {mode === "create" && (loadState === "ready" || loadState === "empty") && (
        <BotForm
          mode="create"
          providerOptions={providers}
          skillOptions={skills}
          loadState={loadState}
          onSubmit={submit}
        />
      )}
      {mode === "edit" && loadState === "ready" && initial && (
        <BotWorkspace
          bot={initial}
          providerOptions={providers}
          skillOptions={skills}
          loadState={loadState}
          onSave={submit}
          onArchive={archive}
        />
      )}
    </div>
  );
}