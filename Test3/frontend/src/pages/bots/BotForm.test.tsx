import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BotInstance } from "../../api/types";
import { BotForm } from "./BotForm";

const imported = { skill_id: "review", version: "1.0.0", description_md: "", allowed_tool_refs: [] };
const providers = [{ slot: "coder", model: "m1" }];

const botA: BotInstance = {
  bot_id: "bot-a",
  display_name: "Leader A",
  role_template: "coder",
  provider_ref: "dashscope",
  model: "m-old",
  slot: "coder",
  secret_ref: "DASHSCOPE_API_KEY",
  tool_policy: [],
  skill_bindings: [{ skill_id: "review", pinned_version: "1.0.0" }],
  token_budget: 40000,
  status: "active",
};

afterEach(cleanup);

describe("BotForm", () => {
  it("submits the create payload with an imported skill and no bot_id", async () => {
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={onSubmit}
        onImportSkill={vi.fn().mockResolvedValue(imported)}
      />,
    );
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "Leader A" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "m1" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.change(screen.getByLabelText("GitHub 地址"), { target: { value: "https://github.com/acme/review" } });
    fireEvent.click(screen.getByRole("button", { name: /^添\s*加$/ }));
    await screen.findByText("review@1.0.0");
    fireEvent.click(screen.getByRole("button", { name: "创建 Bot" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const draft = onSubmit.mock.calls[0][0];
    expect(draft.display_name).toBe("Leader A");
    expect(draft.model).toBe("m1");
    expect(draft.slot).toBe("coder");
    expect(draft.skill_bindings).toEqual([{ skill_id: "review", pinned_version: "1.0.0" }]);
    expect(draft).not.toHaveProperty("bot_id");
  });

  it("prefills an edit form and never leaks identity fields into the patch", () => {
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="edit"
        initial={botA}
        providerOptions={providers}
        loadState="ready"
        onSubmit={onSubmit}
      />,
    );
    expect((screen.getByLabelText("显示名") as HTMLInputElement).value).toBe("Leader A");
    expect((screen.getByLabelText("自定义模型 ID") as HTMLInputElement).value).toBe("m-old");
    expect(screen.queryByLabelText("允许工具")).toBeNull();
    expect(screen.queryByLabelText("令牌预算")).toBeNull();
    expect(screen.queryByText(/PATCH/)).toBeNull();
    fireEvent.change(screen.getByLabelText("自定义模型 ID"), { target: { value: "m-new" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    const patch = onSubmit.mock.calls[0][0];
    expect(patch.model).toBe("m-new");
    expect(patch).not.toHaveProperty("api_key");
    expect(patch.tool_policy).toEqual([]);
    expect(patch.token_budget).toBe(40000);
    expect(patch).not.toHaveProperty("bot_id");
    expect(patch).not.toHaveProperty("role_template");
    expect(patch).not.toHaveProperty("status");
  });

  it("keeps two bots independent even when they bind the same skill", () => {
    const onSubmitA = vi.fn();
    const onSubmitB = vi.fn();
    const botB: BotInstance = { ...botA, bot_id: "bot-b", display_name: "Leader B", model: "m-b" };
    render(
      <>
        <BotForm mode="edit" initial={botA} providerOptions={providers} loadState="ready" onSubmit={onSubmitA} />
        <BotForm mode="edit" initial={botB} providerOptions={providers} loadState="ready" onSubmit={onSubmitB} />
      </>,
    );
    const models = screen.getAllByLabelText("自定义模型 ID") as HTMLInputElement[];
    fireEvent.change(models[0], { target: { value: "m-only-a" } });
    fireEvent.click(screen.getAllByRole("button", { name: "保存修改" })[0]);
    expect(onSubmitA.mock.calls[0][0].model).toBe("m-only-a");
    expect(onSubmitB).not.toHaveBeenCalled();
    expect((screen.getAllByLabelText("自定义模型 ID")[1] as HTMLInputElement).value).toBe("m-b");
  });

  it("edit form can replace the API Key and swap provider, models follow the provider", () => {
    const onSubmit = vi.fn();
    render(<BotForm mode="edit" initial={botA} providerOptions={providers} loadState="ready" onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: " sk-new " } });
    fireEvent.change(screen.getByLabelText("供应商"), { target: { value: "deepseek" } });
    const models = Array.from((screen.getByLabelText("模型") as HTMLSelectElement).options).map((o) => o.value);
    expect(models).toContain("deepseek-flash");
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    const patch = onSubmit.mock.calls[0][0];
    expect(patch).toMatchObject({
      api_key: "sk-new",
      provider_ref: "deepseek",
      model: "deepseek-flash",
      secret_ref: "DEEPSEEK_API_KEY",
    });
  });

  it("shows a masked stand-in for a stored key and only sends a replacement", () => {
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="edit"
        initial={{ ...botA, has_api_key: true }}
        providerOptions={providers}
        loadState="ready"
        onSubmit={onSubmit}
      />,
    );
    const input = screen.getByLabelText("API Key") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.value).toBe("••••••••••••");
    expect(input.value).not.toContain("sk-");

    fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("api_key");

    // partial edit of the dots must not leak them into the key
    fireEvent.change(input, { target: { value: "••sk-fresh" } });
    expect(input.value).toBe("sk-fresh");
    fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
    expect(onSubmit.mock.calls[1][0].api_key).toBe("sk-fresh");

    // clearing the field keeps the stored key (empty is "no change")
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
    expect(onSubmit.mock.calls[2][0]).not.toHaveProperty("api_key");
  });

  it("an edit form without a stored key starts empty", () => {
    render(<BotForm mode="edit" initial={botA} providerOptions={providers} loadState="ready" onSubmit={vi.fn()} />);
    expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe("");
  });

  it("asks for confirmation before archiving", () => {
    const onArchive = vi.fn();
    render(
      <BotForm
        mode="edit"
        initial={botA}
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
        onArchive={onArchive}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "归档 Bot" }));
    expect(onArchive).not.toHaveBeenCalled();
    expect(screen.getByTestId("bot-archive-confirm")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认归档" }));
    expect(onArchive).toHaveBeenCalledTimes(1);
  });
});
describe("identity step", () => {
  it("renders the cover, name and duty choices before the technical fields", () => {
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByTestId("bot-identity")).toBeTruthy();
    expect(screen.getByTestId("bot-identity").querySelector("[data-testid='bot-avatar']")).toBeTruthy();
    expect((screen.getByLabelText("显示名") as HTMLInputElement).placeholder).toBe("给你的 Bot 起个名字");
    expect(screen.getByTestId("bot-duty-grid")).toBeTruthy();
    expect(screen.getByTestId("duty-leader").getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByTestId("duty-coder").getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByLabelText("模型")).toBeNull();
    expect(screen.queryByLabelText("角色模板")).toBeNull();
  });

  it("closes the dialog on Escape", () => {
    const onCancel = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("model step offers domestic providers with base URL, a masked key and a per-provider model list", () => {
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "小助" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    const provider = screen.getByLabelText("供应商") as HTMLSelectElement;
    const labels = Array.from(provider.options).map((option) => option.textContent ?? "");
    expect(labels.some((text) => text.includes("https://api.moonshot.cn/v1"))).toBe(true);
    expect(labels.some((text) => text.includes("https://api.deepseek.com"))).toBe(true);
    expect((screen.getByLabelText("API Key") as HTMLInputElement).type).toBe("password");

    fireEvent.change(provider, { target: { value: "moonshot" } });
    const models = Array.from((screen.getByLabelText("模型") as HTMLSelectElement).options).map((o) => o.value);
    expect(models).toContain("kimi-k3.1-pro");
    expect(models).not.toContain("m1");

    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "  sk-real-key  " } });
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "创建 Bot" }));
    const draft = onSubmit.mock.calls[0][0];
    expect(draft.api_key).toBe("sk-real-key");
    expect(draft.provider_ref).toBe("moonshot");
    expect(draft.model).toBe("kimi-k3.1-pro");
    expect(draft.secret_ref).toBe("MOONSHOT_API_KEY");
  });

  it("skill step: empty state, import by GitHub URL, error shown, binding removable", async () => {
    const onImportSkill = vi
      .fn()
      .mockRejectedValueOnce(new Error("找不到这个仓库或分支，请确认它是公开的"))
      .mockResolvedValueOnce({ skill_id: "acme-review", version: "abc1234", description_md: "", allowed_tool_refs: [] });
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={onSubmit}
        onImportSkill={onImportSkill}
      />,
    );
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "小助" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByTestId("skill-empty")).toBeTruthy();
    const add = screen.getByRole("button", { name: /^添\s*加$/ }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("GitHub 地址"), { target: { value: "https://github.com/acme/none" } });
    fireEvent.click(screen.getByRole("button", { name: /^添\s*加$/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("找不到这个仓库");
    expect(screen.getByTestId("skill-empty")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^添\s*加$/ }));
    await screen.findByText("acme-review@abc1234");
    expect(screen.queryByTestId("skill-empty")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "移除" }));
    expect(screen.getByTestId("skill-empty")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^添\s*加$/ }));
  });

  it("closes via the ✕ button and exposes a photo upload input", () => {
    const onCancel = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );
    expect(screen.queryByRole("button", { name: "取消" })).toBeNull();
    expect((screen.getByTestId("avatar-upload") as HTMLInputElement).accept).toBe("image/*");
    expect(screen.getByRole("button", { name: "上传头像照片" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("walks the three steps and blocks the next step until a name exists", () => {
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const next = () => screen.getByRole("button", { name: "下一步" }) as HTMLButtonElement;
    expect(next().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "周明" } });
    expect(next().disabled).toBe(false);
    fireEvent.click(next());
    expect(screen.getByLabelText("模型")).toBeTruthy();
    expect(screen.queryByTestId("bot-identity")).toBeNull();
    fireEvent.click(next());
    expect(screen.getByTestId("bot-step-summary")).toBeTruthy();
    expect(screen.getByLabelText("GitHub 地址")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "上一步" }));
    expect(screen.getByLabelText("模型")).toBeTruthy();
  });

  it("reports avatar picks to the parent without touching the payload", () => {
    const onAvatarChange = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
        avatarDraft={{}}
        onAvatarChange={onAvatarChange}
      />,
    );
    fireEvent.click(screen.getByLabelText("头像 🦊"));
    expect(onAvatarChange).toHaveBeenCalledWith({ emoji: "🦊" });
    fireEvent.click(screen.getByLabelText("颜色 #7c3aed"));
    expect(onAvatarChange).toHaveBeenCalledWith({ color: "#7c3aed" });
  });
});

describe("role presets", () => {
  it("applies a preset role and matching slot in create mode", () => {
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={[{ slot: "flagship", model: "m1" }]}
        loadState="ready"
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "PM Bot" } });
    fireEvent.click(screen.getByTestId("duty-pm"));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "创建 Bot" }));
    const draft = onSubmit.mock.calls[0][0];
    expect(draft.role_template).toBe("pm");
    expect(draft.slot).toBe("flagship");
    expect(draft.model).toBe("m1");
  });

  it("locks the role template select when editing", () => {
    render(
      <BotForm
        mode="edit"
        initial={botA}
        providerOptions={providers}
        loadState="ready"
        onSubmit={vi.fn()}
      />,
    );
    const select = screen.getByLabelText("角色模板") as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(select.value).toBe("coder");
  });
});
