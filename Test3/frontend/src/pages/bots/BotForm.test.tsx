import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BotInstance } from "../../api/types";
import { BotForm } from "./BotForm";

const skills = [
  { skill_id: "review", version: "1.0.0", description_md: "", allowed_tool_refs: [] },
  { skill_id: "review", version: "1.1.0", description_md: "", allowed_tool_refs: [] },
];
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
  it("submits the create payload with a pinned skill and no bot_id", () => {
    const onSubmit = vi.fn();
    render(
      <BotForm mode="create" providerOptions={providers} skillOptions={skills} loadState="ready" onSubmit={onSubmit} />,
    );
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "Leader A" } });
    fireEvent.change(screen.getByLabelText("模型槽位"), { target: { value: "coder" } });
    fireEvent.change(screen.getByLabelText("Skill 版本"), { target: { value: "review@1.0.0" } });
    fireEvent.click(screen.getByRole("button", { name: "添加绑定" }));
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
        skillOptions={skills}
        loadState="ready"
        onSubmit={onSubmit}
      />,
    );
    expect((screen.getByLabelText("显示名") as HTMLInputElement).value).toBe("Leader A");
    expect((screen.getByLabelText("模型") as HTMLInputElement).value).toBe("m-old");
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "m-new" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    const patch = onSubmit.mock.calls[0][0];
    expect(patch.model).toBe("m-new");
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
        <BotForm mode="edit" initial={botA} providerOptions={providers} skillOptions={skills} loadState="ready" onSubmit={onSubmitA} />
        <BotForm mode="edit" initial={botB} providerOptions={providers} skillOptions={skills} loadState="ready" onSubmit={onSubmitB} />
      </>,
    );
    const models = screen.getAllByLabelText("模型") as HTMLInputElement[];
    fireEvent.change(models[0], { target: { value: "m-only-a" } });
    fireEvent.click(screen.getAllByRole("button", { name: "保存修改" })[0]);
    expect(onSubmitA.mock.calls[0][0].model).toBe("m-only-a");
    expect(onSubmitB).not.toHaveBeenCalled();
    expect((screen.getAllByLabelText("模型")[1] as HTMLInputElement).value).toBe("m-b");
  });

  it("asks for confirmation before archiving", () => {
    const onArchive = vi.fn();
    render(
      <BotForm
        mode="edit"
        initial={botA}
        providerOptions={providers}
        skillOptions={skills}
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
describe("role presets", () => {
  it("applies a preset role and matching slot in create mode", () => {
    const onSubmit = vi.fn();
    render(
      <BotForm
        mode="create"
        providerOptions={[{ slot: "flagship", model: "m1" }]}
        skillOptions={skills}
        loadState="ready"
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "PM Bot" } });
    fireEvent.click(screen.getByTestId("preset-pm"));
    fireEvent.click(screen.getByRole("button", { name: "创建 Bot" }));
    const draft = onSubmit.mock.calls[0][0];
    expect(draft.role_template).toBe("pm");
    expect(draft.slot).toBe("flagship");
    expect(draft.model).toBe("m1");
  });

  it("does not offer presets when editing", () => {
    render(
      <BotForm
        mode="edit"
        initial={botA}
        providerOptions={providers}
        skillOptions={skills}
        loadState="ready"
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("preset-pm")).toBeNull();
  });
});
