import { useEffect, useRef, useState } from "react";
import { Button } from "antd";
import type { BotCreate, BotInstance, BotPatch, BotSkillBinding, SkillDefinition } from "../../api/types";
import { BotAvatar } from "../../components/BotAvatar";
import type { LoadState } from "../../components/AppShell";
import { AVATAR_EMOJI_CHOICES, AVATAR_PALETTE, fileToAvatarDataUrl, type BotAvatarPreset } from "../../lib/botAvatar";

export type ProviderOption = { slot: string; model: string };

export type BotFormProps = {
  mode: "create" | "edit";
  initial?: BotInstance;
  providerOptions: ProviderOption[];
  loadState: LoadState;
  onSubmit: (draft: BotCreate | BotPatch) => void | Promise<void>;
  onArchive?: () => void | Promise<void>;
  /** Import a skill from a GitHub URL; resolves to the stored definition. */
  onImportSkill?: (url: string) => Promise<SkillDefinition>;
  /** Create mode only: the dialog's ✕ close button and Esc key. */
  onCancel?: () => void;
  /** Create mode only: avatar chosen before the bot exists (stored after create). */
  avatarDraft?: BotAvatarPreset;
  onAvatarChange?: (preset: BotAvatarPreset) => void;
};

const ROLE_PRESETS = [
  { key: "leader", label: "Leader", role: "leader", slot: "flagship", duty: "统筹任务、裁决冲突、代表项目对外" },
  { key: "pm", label: "产品经理", role: "pm", slot: "flagship", duty: "拆解需求、定义验收口径" },
  { key: "backend", label: "后端工程师", role: "backend", slot: "coder", duty: "实现服务、数据层与接口" },
  { key: "qa", label: "测试运维", role: "qa", slot: "coder", duty: "用例、回归验证与发布检查" },
  { key: "coder", label: "通用工程师", role: "coder", slot: "coder", duty: "通用实现与日常改动" },
];

export type ProviderCatalogEntry = {
  id: string;
  label: string;
  baseUrl: string;
  /** Default env var name recorded as secret_ref. */
  secretEnv: string;
  models: string[];
};

/** Domestic OpenAI-compatible providers (base URLs and model ids checked against vendor docs, Nov 2026). */
export const PROVIDER_CATALOG: ProviderCatalogEntry[] = [
  { id: "dashscope", label: "阿里云百炼", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", secretEnv: "DASHSCOPE_API_KEY", models: ["qwen3.7-plus", "qwen3-coder-flash"] },
  { id: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com", secretEnv: "DEEPSEEK_API_KEY", models: ["deepseek-flash", "deepseek-v4-pro"] },
  { id: "moonshot", label: "Kimi · 月之暗面", baseUrl: "https://api.moonshot.cn/v1", secretEnv: "MOONSHOT_API_KEY", models: ["kimi-k3.1-pro", "kimi-k3.1-pro-highspeed", "kimi-k3"] },
  { id: "zhipu", label: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4", secretEnv: "ZHIPU_API_KEY", models: ["glm-5.3"] },
  { id: "volcengine", label: "火山方舟 · 豆包", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", secretEnv: "ARK_API_KEY", models: ["doubao-2.0-pro-256k"] },
  { id: "minimax", label: "MiniMax", baseUrl: "https://api.minimaxi.com/v1", secretEnv: "MINIMAX_API_KEY", models: ["MiniMax-M3"] },
  { id: "siliconflow", label: "硅基流动", baseUrl: "https://api.siliconflow.cn/v1", secretEnv: "SILICONFLOW_API_KEY", models: ["deepseek-ai/DeepSeek-V3"] },
  { id: "hunyuan", label: "腾讯混元", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1", secretEnv: "HUNYUAN_API_KEY", models: [] },
  { id: "qianfan", label: "百度千帆", baseUrl: "https://qianfan.baidubce.com/v2", secretEnv: "QIANFAN_API_KEY", models: [] },
  { id: "stepfun", label: "阶跃星辰", baseUrl: "https://api.stepfun.com/v1", secretEnv: "STEPFUN_API_KEY", models: [] },
];

const CUSTOM_MODEL = "__custom__";
/** Stand-in shown for a stored key; the real key never reaches the browser. */
const KEY_MASK = "••••••••••••";

export function BotForm({
  mode,
  initial,
  providerOptions,
  loadState,
  onSubmit,
  onArchive,
  onCancel,
  onImportSkill,
  avatarDraft,
  onAvatarChange,
}: BotFormProps) {
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [roleTemplate, setRoleTemplate] = useState(initial?.role_template ?? "coder");
  const [providerRef, setProviderRef] = useState(initial?.provider_ref ?? "");
  const [model, setModel] = useState(initial?.model ?? "");
  const [slot, setSlot] = useState(initial?.slot ?? "");
  const [secretRef, setSecretRef] = useState(initial?.secret_ref ?? "");
  const [bindings, setBindings] = useState<BotSkillBinding[]>(initial?.skill_bindings ?? []);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [avatarError, setAvatarError] = useState("");
  const hadKey = Boolean(initial?.has_api_key);
  const [apiKey, setApiKey] = useState(hadKey ? KEY_MASK : "");
  const [customModel, setCustomModel] = useState(false);
  const [skillUrl, setSkillUrl] = useState("");
  const [skillError, setSkillError] = useState("");
  const [importing, setImporting] = useState(false);
  const photoInput = useRef<HTMLInputElement>(null);

  const busy = loadState === "loading";
  const isCreate = mode === "create";

  useEffect(() => {
    if (!isCreate || !onCancel) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isCreate, onCancel]);
  const firstProvider = providerOptions[0];
  const effectiveSlot = slot || firstProvider?.slot || "";
  const effectiveProvider = providerRef || PROVIDER_CATALOG[0].id;
  const effectiveModel = model || (effectiveProvider === "dashscope" ? firstProvider?.model : "") || "";
  const providerChoices = PROVIDER_CATALOG.some((item) => item.id === effectiveProvider)
    ? PROVIDER_CATALOG
    : [...PROVIDER_CATALOG, { id: effectiveProvider, label: effectiveProvider, baseUrl: "", secretEnv: "", models: [] }];
  const providerEntry = providerChoices.find((item) => item.id === effectiveProvider) ?? providerChoices[0];
  // 百炼 models come from the workbench's own model config when available.
  const modelChoices =
    providerEntry.id === "dashscope" && providerOptions.length > 0
      ? Array.from(new Set(providerOptions.map((item) => item.model)))
      : providerEntry.models;
  const modelIsListed = modelChoices.includes(effectiveModel);
  const showCustomModel = customModel || !modelIsListed;
  const effectiveSecret = secretRef || providerEntry.secretEnv;

  const pickProvider = (id: string) => {
    setProviderRef(id);
    setSecretRef("");
    const entry = PROVIDER_CATALOG.find((item) => item.id === id);
    const list =
      id === "dashscope" && providerOptions.length > 0
        ? providerOptions.map((item) => item.model)
        : (entry?.models ?? []);
    setCustomModel(list.length === 0);
    pickModel(id, list[0] ?? "");
  };

  const pickModel = (providerId: string, nextModel: string) => {
    setModel(nextModel);
    if (providerId === "dashscope") {
      const match = providerOptions.find((item) => item.model === nextModel);
      if (match) setSlot(match.slot);
    }
  };

  const importFromGithub = async () => {
    const url = skillUrl.trim();
    if (!url || !onImportSkill || importing) return;
    setImporting(true);
    setSkillError("");
    try {
      const skill = await onImportSkill(url);
      const next = { skill_id: skill.skill_id, pinned_version: skill.version };
      setBindings((current) =>
        current.some((item) => item.skill_id === next.skill_id && item.pinned_version === next.pinned_version)
          ? current
          : [...current, next],
      );
      setSkillUrl("");
    } catch (error) {
      setSkillError(error instanceof Error ? error.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const submit = () => {
    const base = {
      display_name: displayName,
      provider_ref: providerRef || "dashscope",
      model: effectiveModel,
      slot: effectiveSlot,
      secret_ref: effectiveSecret,
      tool_policy: initial?.tool_policy ?? [],
      skill_bindings: bindings,
      token_budget: initial?.token_budget ?? 40000,
    };
    const key = apiKey === KEY_MASK ? "" : apiKey.trim();
    const keyField = key ? { api_key: key } : {};
    if (mode === "create") {
      void onSubmit({ ...base, role_template: roleTemplate, ...keyField } satisfies BotCreate);
    } else {
      void onSubmit({ ...base, ...keyField } satisfies BotPatch);
    }
  };

  const onPhotoPicked = async (file: File | undefined) => {
    if (!file) return;
    try {
      const imageDataUrl = await fileToAvatarDataUrl(file);
      setAvatarError("");
      onAvatarChange?.({ ...avatarDraft, imageDataUrl });
    } catch (error) {
      setAvatarError(error instanceof Error ? error.message : "图片上传失败");
    }
  };

  const applyRole = (preset: (typeof ROLE_PRESETS)[number]) => {
    setRoleTemplate(preset.role);
    const match = providerOptions.find(
      (option) => option.slot === preset.role || option.slot === preset.slot,
    );
    if (match) {
      setSlot(match.slot);
      setModel(match.model);
    }
  };

  const modelFields = (
    <>
      <label>
        <span>供应商</span>
        <select aria-label="供应商" value={effectiveProvider} onChange={(event) => pickProvider(event.target.value)}>
          {providerChoices.map((item) => (
            <option key={item.id} value={item.id}>
              {item.baseUrl ? `${item.label} · ${item.baseUrl}` : item.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>API Key</span>
        <input
          type="password"
          value={apiKey}
          onFocus={(event) => {
            if (apiKey === KEY_MASK) event.target.select();
          }}
          onChange={(event) => {
            const next = event.target.value;
            // Editing the placeholder dots must never leak them into a real key.
            setApiKey(apiKey === KEY_MASK && next !== KEY_MASK ? next.replace(/•/g, "") : next);
          }}
          placeholder={hadKey ? "留空则保持不变" : "粘贴你的 API Key"}
          aria-label="API Key"
          autoComplete="new-password"
          spellCheck={false}
        />
      </label>
      <label>
        <span>模型</span>
        {modelChoices.length > 0 && (
          <select
            aria-label="模型"
            value={showCustomModel ? CUSTOM_MODEL : effectiveModel}
            onChange={(event) => {
              if (event.target.value === CUSTOM_MODEL) {
                setCustomModel(true);
                return;
              }
              setCustomModel(false);
              pickModel(effectiveProvider, event.target.value);
            }}
          >
            {modelChoices.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
            <option value={CUSTOM_MODEL}>自定义模型…</option>
          </select>
        )}
        {showCustomModel && (
          <input
            value={modelIsListed ? "" : effectiveModel}
            onChange={(event) => setModel(event.target.value)}
            placeholder="输入模型 ID"
            aria-label="自定义模型 ID"
            spellCheck={false}
          />
        )}
      </label>
    </>
  );

  const bindingList = (
    <ul className="bot-skill-list" aria-label="已绑定 Skill">
      {bindings.map((item) => (
        <li key={`${item.skill_id}@${item.pinned_version}`}>
          <span className="mono">
            {item.skill_id}@{item.pinned_version}
          </span>
          <button
            type="button"
            className="chip"
            onClick={() => setBindings((current) => current.filter((entry) => entry !== item))}
          >
            移除
          </button>
        </li>
      ))}
    </ul>
  );

  const githubImport = (
    <>
      <div className="bot-skill-import">
        <input
          value={skillUrl}
          onChange={(event) => setSkillUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void importFromGithub();
            }
          }}
          placeholder="粘贴 GitHub 地址，例如 https://github.com/owner/repo"
          aria-label="GitHub 地址"
          autoComplete="off"
          spellCheck={false}
        />
        <Button type="primary" loading={importing} disabled={!skillUrl.trim()} onClick={() => void importFromGithub()}>
          添加
        </Button>
      </div>
      {skillError && (
        <div className="bot-field-error" role="alert">
          {skillError}
        </div>
      )}
      {bindings.length === 0 ? (
        <div className="bot-skill-empty" data-testid="skill-empty">
          还没有额外的 Skill
        </div>
      ) : (
        bindingList
      )}
    </>
  );

  const skillSection = (
    <>
      <div className="section-title" style={{ marginTop: 4 }}>
        <span>额外 Skill</span>
      </div>
      {githubImport}
    </>
  );

  if (isCreate) {
    return (
      <div
        className="surface bot-create-dialog"
        data-testid="bot-form"
        role="dialog"
        aria-modal="true"
        aria-label="创建新 Bot"
      >
        <button type="button" className="bot-create-close" aria-label="关闭" onClick={onCancel}>
          ✕
        </button>
        {step === 1 && (
          <div className="bot-identity" data-testid="bot-identity">
            <div className="bot-identity-cover">
              <button
                type="button"
                className="bot-identity-upload"
                aria-label="上传头像照片"
                title="上传头像照片"
                onClick={() => photoInput.current?.click()}
              >
                <BotAvatar
                  bot={{
                    bot_id: "new-bot",
                    display_name: displayName.trim() || "新 Bot",
                    role_template: roleTemplate,
                    status: "active",
                  }}
                  size={96}
                  title="封面预览"
                  preset={avatarDraft}
                />
                <span className="bot-identity-upload-badge" aria-hidden>
                  📷
                </span>
              </button>
              <input
                ref={photoInput}
                type="file"
                accept="image/*"
                hidden
                data-testid="avatar-upload"
                aria-label="头像文件"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  void onPhotoPicked(file);
                }}
              />
              {avatarError && (
                <span className="bot-identity-error" role="alert">
                  {avatarError}
                </span>
              )}
            </div>
            <input
              className="bot-identity-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="给你的 Bot 起个名字"
              aria-label="显示名"
              maxLength={40}
              autoFocus
            />
            <div className="bot-identity-picks">
              <div className="bot-identity-pick">
                <div className="avatar-emoji-row">
                  {AVATAR_EMOJI_CHOICES.map((emoji) => (
                    <button
                      key={emoji}
                      type="button"
                      className={`avatar-swatch ${avatarDraft?.emoji === emoji ? "active" : ""}`}
                      aria-label={`头像 ${emoji}`}
                      onClick={() => onAvatarChange?.({ ...avatarDraft, emoji, imageDataUrl: undefined })}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              </div>
              <div className="bot-identity-pick">
                <div className="avatar-color-row">
                  {AVATAR_PALETTE.map((color) => (
                    <button
                      key={color}
                      type="button"
                      className={`avatar-color ${avatarDraft?.color === color ? "active" : ""}`}
                      style={{ background: color }}
                      aria-label={`颜色 ${color}`}
                      onClick={() => onAvatarChange?.({ ...avatarDraft, color, imageDataUrl: undefined })}
                    />
                  ))}
                </div>
              </div>
            </div>
            <div className="section-title" style={{ marginTop: 8 }}>
              <span>职责</span>
            </div>
            <div className="bot-duty-grid" data-testid="bot-duty-grid">
              {ROLE_PRESETS.map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  data-testid={`duty-${preset.key}`}
                  aria-pressed={roleTemplate === preset.role}
                  className={`duty-card ${roleTemplate === preset.role ? "active" : ""}`}
                  onClick={() => applyRole(preset)}
                >
                  <span className="duty-label">{preset.label}</span>
                  <span className="duty-role mono">{preset.role}</span>
                  <span className="duty-desc">{preset.duty}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 2 && (
          <>
            <div className="bot-form-grid bot-form-stack">{modelFields}</div>
          </>
        )}

        {step === 3 && (
          <>
            <div className="bot-step-summary" data-testid="bot-step-summary">
              <BotAvatar
                bot={{
                  bot_id: "new-bot",
                  display_name: displayName.trim() || "新 Bot",
                  role_template: roleTemplate,
                  status: "active",
                }}
                size={44}
                title="封面预览"
                preset={avatarDraft}
              />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="bot-list-name">{displayName.trim() || "未命名 Bot"}</div>
                <div className="mono muted">
                  {roleTemplate} · {effectiveSlot || "未选槽位"} · {effectiveModel || "未选模型"}
                </div>
              </div>
              <span className="chip">{bindings.length} 个 Skill</span>
            </div>
            {skillSection}
          </>
        )}

        <div className="bot-form-actions bot-create-actions">
          <span style={{ flex: 1 }} />
          <Button size="small" onClick={() => setStep((current) => (current > 1 ? ((current - 1) as 1 | 2 | 3) : current))} disabled={step === 1}>
            上一步
          </Button>
          {step < 3 ? (
            <Button
              size="small"
              type="primary"
              onClick={() => setStep((current) => (current < 3 ? ((current + 1) as 1 | 2 | 3) : current))}
              disabled={(step === 1 && !displayName.trim()) || (step === 2 && !effectiveModel.trim())}
            >
              下一步
            </Button>
          ) : (
            <Button size="small" type="primary" onClick={submit} disabled={busy || !displayName.trim()}>
              创建 Bot
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="surface bot-edit-panel" data-testid="bot-form">
      <div className="bot-form-grid bot-form-stack">
        <label>
          <span>显示名</span>
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} aria-label="显示名" />
        </label>
        <label>
          <span>角色</span>
          <select value={roleTemplate} disabled aria-label="角色模板" data-testid="role-template-select">
            {!ROLE_PRESETS.some((preset) => preset.role === roleTemplate) && (
              <option value={roleTemplate}>{roleTemplate}</option>
            )}
            {ROLE_PRESETS.map((preset) => (
              <option key={preset.key} value={preset.role}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
        {modelFields}
      </div>

      {skillSection}

      <div className="bot-form-actions bot-edit-actions">
        <Button type="primary" onClick={submit} disabled={busy || !displayName.trim()}>
          保存修改
        </Button>
        {onArchive && (
          <Button danger onClick={() => setConfirmArchive(true)}>
            归档 Bot
          </Button>
        )}
        {confirmArchive && (
          <span className="bot-archive-confirm" data-testid="bot-archive-confirm">
            归档后该 Bot 不再参与新运行，确认归档？
            <Button size="small" danger onClick={() => onArchive?.()}>
              确认归档
            </Button>
            <Button size="small" onClick={() => setConfirmArchive(false)}>
              取消
            </Button>
          </span>
        )}
      </div>
    </div>
  );
}

export default BotForm;
