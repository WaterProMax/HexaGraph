import { useState } from "react";
import { Button } from "antd";
import type { BotCreate, BotInstance, BotPatch, BotSkillBinding, SkillDefinition } from "../../api/types";
import type { LoadState } from "../../components/AppShell";

export type ProviderOption = { slot: string; model: string };

export type BotFormProps = {
  mode: "create" | "edit";
  initial?: BotInstance;
  providerOptions: ProviderOption[];
  skillOptions: SkillDefinition[];
  loadState: LoadState;
  onSubmit: (draft: BotCreate | BotPatch) => void | Promise<void>;
  onArchive?: () => void | Promise<void>;
};

const ROLE_PRESETS = [
  { key: "leader", label: "Leader", role: "leader", slot: "flagship" },
  { key: "pm", label: "产品经理", role: "pm", slot: "flagship" },
  { key: "backend", label: "后端工程师", role: "backend", slot: "coder" },
  { key: "qa", label: "测试运维", role: "qa", slot: "coder" },
  { key: "coder", label: "通用工程师", role: "coder", slot: "coder" },
];

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function BotForm({ mode, initial, providerOptions, skillOptions, loadState, onSubmit, onArchive }: BotFormProps) {
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [roleTemplate, setRoleTemplate] = useState(initial?.role_template ?? "coder");
  const [providerRef, setProviderRef] = useState(initial?.provider_ref ?? "");
  const [model, setModel] = useState(initial?.model ?? "");
  const [slot, setSlot] = useState(initial?.slot ?? "");
  const [secretRef, setSecretRef] = useState(initial?.secret_ref ?? "");
  const [toolPolicy, setToolPolicy] = useState((initial?.tool_policy ?? []).join(", "));
  const [tokenBudget, setTokenBudget] = useState(String(initial?.token_budget ?? 40000));
  const [bindings, setBindings] = useState<BotSkillBinding[]>(initial?.skill_bindings ?? []);
  const [choice, setChoice] = useState("");
  const [confirmArchive, setConfirmArchive] = useState(false);

  const busy = loadState === "loading";
  const firstProvider = providerOptions[0];
  const effectiveSlot = slot || firstProvider?.slot || "";
  const effectiveModel = model || firstProvider?.model || "";

  const addBinding = () => {
    const option = skillOptions.find((item) => `${item.skill_id}@${item.version}` === choice);
    if (!option) return;
    const next = { skill_id: option.skill_id, pinned_version: option.version };
    setBindings((current) =>
      current.some((item) => item.skill_id === next.skill_id && item.pinned_version === next.pinned_version)
        ? current
        : [...current, next],
    );
    setChoice("");
  };

  const submit = () => {
    const base = {
      display_name: displayName,
      provider_ref: providerRef || "dashscope",
      model: effectiveModel,
      slot: effectiveSlot,
      secret_ref: secretRef,
      tool_policy: parseList(toolPolicy),
      skill_bindings: bindings,
      token_budget: Number(tokenBudget) || 0,
    };
    if (mode === "create") {
      void onSubmit({ ...base, role_template: roleTemplate } satisfies BotCreate);
    } else {
      void onSubmit(base satisfies BotPatch);
    }
  };

  return (
    <div className="surface" style={{ padding: 20 }} data-testid="bot-form">
      <div className="section-title">
        <span>{mode === "create" ? "新建 Bot" : "编辑 Bot"}</span>
        <span className="mono muted">{mode === "create" ? "POST /api/bots" : "PATCH /api/bots/{id}"}</span>
      </div>
      {mode === "create" && (
        <div className="role-presets" aria-label="角色模板预设">
          {ROLE_PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              data-testid={`preset-${preset.key}`}
              className={`chip ${roleTemplate === preset.role ? "active" : ""}`}
              onClick={() => {
                setRoleTemplate(preset.role);
                const match = providerOptions.find(
                  (option) => option.slot === preset.role || option.slot === preset.slot,
                );
                if (match) {
                  setSlot(match.slot);
                  setModel(match.model);
                }
              }}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}
      <div className="bot-form-grid">
        <label>
          <span>显示名</span>
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} aria-label="显示名" />
        </label>
        <label>
          <span>角色模板</span>
          <input
            value={roleTemplate}
            onChange={(event) => setRoleTemplate(event.target.value)}
            disabled={mode === "edit"}
            aria-label="角色模板"
          />
        </label>
        <label>
          <span>Provider</span>
          <input value={providerRef} onChange={(event) => setProviderRef(event.target.value)} aria-label="Provider" />
        </label>
        <label>
          <span>模型槽位</span>
          <select
            aria-label="模型槽位"
            value={effectiveSlot}
            onChange={(event) => {
              const next = providerOptions.find((item) => item.slot === event.target.value);
              setSlot(event.target.value);
              if (next) setModel(next.model);
            }}
          >
            {providerOptions.length === 0 && <option value="">（使用手填模型）</option>}
            {providerOptions.map((item) => (
              <option key={item.slot} value={item.slot}>
                {item.slot} · {item.model}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>模型</span>
          <input value={effectiveModel} onChange={(event) => setModel(event.target.value)} aria-label="模型" />
        </label>
        <label>
          <span>密钥环境变量名（secret_ref）</span>
          <input value={secretRef} onChange={(event) => setSecretRef(event.target.value)} aria-label="secret_ref" />
        </label>
        <label>
          <span>允许工具（逗号分隔）</span>
          <input value={toolPolicy} onChange={(event) => setToolPolicy(event.target.value)} aria-label="允许工具" />
        </label>
        <label>
          <span>令牌预算</span>
          <input
            type="number"
            value={tokenBudget}
            onChange={(event) => setTokenBudget(event.target.value)}
            aria-label="令牌预算"
          />
        </label>
      </div>

      <div className="section-title" style={{ marginTop: 18 }}>
        <span>Skill 绑定</span>
        <span className="hint">绑定属于这个 Bot，不修改 Skill 定义本身</span>
      </div>
      <div className="bot-skill-row">
        <select aria-label="Skill 版本" value={choice} onChange={(event) => setChoice(event.target.value)}>
          <option value="">选择 Skill 版本</option>
          {skillOptions.map((item) => (
            <option key={`${item.skill_id}@${item.version}`} value={`${item.skill_id}@${item.version}`}>
              {item.skill_id}@{item.version}
            </option>
          ))}
        </select>
        <Button size="small" onClick={addBinding} disabled={!choice}>
          添加绑定
        </Button>
      </div>
      <ul className="bot-skill-list" aria-label="已绑定 Skill">
        {bindings.length === 0 && <li className="muted">尚未绑定 Skill</li>}
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

      <div className="bot-form-actions">
        <Button type="primary" onClick={submit} disabled={busy || !displayName.trim()}>
          {mode === "create" ? "创建 Bot" : "保存修改"}
        </Button>
        {mode === "edit" && onArchive && (
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