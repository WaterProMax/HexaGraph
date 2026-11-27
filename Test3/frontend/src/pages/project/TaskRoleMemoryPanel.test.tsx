import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskRoleMemoryPanel } from "./TaskRoleMemoryPanel";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

const memory = {
  run_id: "r1",
  project_id: "p1",
  task_code: "T1",
  role: "coder" as const,
  revision: 2,
  manual_text: "优先覆盖空输入测试",
  manual_updated_by: "leader",
  manual_updated_at: "2026-11-25T00:00:00+00:00",
  role_snapshot: {
    text: "任务：T1\n角色：coder",
    sources: [
      { kind: "task_card", ref: "T1", sha256: "a".repeat(64) },
      { kind: "role_definition", ref: "coder", sha256: "b".repeat(64) },
    ],
    matcher_version: "task-role-v1",
  },
  role_section: {
    kind: "task_role",
    source_id: "T1:coder",
    source_version: "task-role-v1",
    text: "任务：T1\n角色：coder",
    sha256: "a".repeat(64),
  },
  manual_section: {
    kind: "task_manual",
    source_id: "T1:coder",
    source_version: "2",
    text: "优先覆盖空输入测试",
    sha256: "c".repeat(64),
  },
  context_hash: "d".repeat(64),
  frozen: false,
  frozen_context: {},
  effective: "current" as const,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TaskRoleMemoryPanel", () => {
  it("loads the task/role memory with the actor header and renders both sections", async () => {
    const calls: Array<{ url: string; headers: any }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), headers: init?.headers });
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    expect(await screen.findByText(/任务：T1/)).toBeTruthy();
    expect((screen.getByTestId("task-role-memory-input") as HTMLTextAreaElement).value).toBe(
      "优先覆盖空输入测试",
    );
    const call = calls.find((item) => item.url.includes("/role-memory/coder"));
    expect(call?.url).toBe("/api/runs/r1/tasks/T1/role-memory/coder");
    expect((call?.headers as Record<string, string>)["X-Bot-Id"]).toBe("leader");
  });

  it("keeps save and clear disabled for non-leaders", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(memory)));
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="member" isLeader={false} />);
    expect(await screen.findByTestId("task-role-memory-save")).toBeTruthy();
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("task-role-memory-clear") as HTMLButtonElement).disabled).toBe(true);
  });

  it("saves with the current revision", async () => {
    const calls: Array<{ method: string; body: any }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ method: init?.method || "GET", body: init?.body ? JSON.parse(String(init.body)) : null });
        if (init?.method === "PUT") return json({ ...memory, revision: 3, manual_text: "新补充", manual_section: { ...memory.manual_section, text: "新补充", source_version: "3" } });
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = await screen.findByTestId("task-role-memory-input");
    fireEvent.change(input, { target: { value: "新补充" } });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT")!;
    expect(put.body).toEqual({ expected_revision: 2, manual_text: "新补充" });
    expect(await screen.findByText(/已保存/)).toBeTruthy();
  });

  it("shows a refresh prompt on 409 and reloads", async () => {
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return json({ error_category: "revision_conflict", detail: "conflict" }, 409);
        }
        gets += 1;
        return json({ ...memory, revision: gets + 2 });
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    fireEvent.change(await screen.findByTestId("task-role-memory-input"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));
    expect(await screen.findByText(/版本冲突/)).toBeTruthy();
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));
  });

  it("ignores a stale response when the run changes before it resolves", async () => {
    const stale = deferred<Response>();
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        urls.push(url);
        if (url.includes("/runs/r-old/")) return stale.promise;
        return Promise.resolve(
          json({ ...memory, run_id: "r-new", revision: 7, manual_text: "新 run 的补充" }),
        );
      }),
    );

    const view = render(
      <TaskRoleMemoryPanel runId="r-old" taskCode="T1" role="coder" actorBotId="leader" isLeader />,
    );
    view.rerender(
      <TaskRoleMemoryPanel runId="r-new" taskCode="T1" role="coder" actorBotId="leader" isLeader />,
    );

    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    expect(input.value).toBe("新 run 的补充");
    expect(urls.some((url) => url.includes("/runs/r-old/"))).toBe(true);
    expect(urls.some((url) => url.includes("/runs/r-new/"))).toBe(true);

    // The old run's GET resolves last: it must not overwrite the new run state.
    await act(async () => {
      stale.resolve(json({ ...memory, run_id: "r-old", revision: 2, manual_text: "旧 run 的补充" }));
      await stale.promise;
    });

    expect((screen.getByTestId("task-role-memory-input") as HTMLTextAreaElement).value).toBe(
      "新 run 的补充",
    );
    expect(screen.getByTestId("task-role-memory").textContent).toContain("revision 7");
  });

  it("clears manual text only for leaders the backend allows", async () => {
    const calls: Array<{ method: string; url: string }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ method: init?.method || "GET", url: String(input) });
        if (init?.method === "DELETE") return json({ ...memory, revision: 3, manual_text: "", manual_section: null });
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    fireEvent.click(await screen.findByTestId("task-role-memory-clear"));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(calls.find((call) => call.method === "DELETE")?.url).toContain("expected_revision=2");
  });

  it("keeps the draft and does not reload when the run is busy", async () => {
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return json({ error_category: "run_busy", detail: "run_busy" }, 409);
        }
        gets += 1;
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "执行中的补充" } });
    const getsBefore = gets;
    fireEvent.click(screen.getByTestId("task-role-memory-save"));

    expect(await screen.findByText(/任务正在执行/)).toBeTruthy();
    expect(input.value).toBe("执行中的补充");
    // run_busy is not a revision conflict: no reload is issued and the GET
    // count must not grow.
    expect(gets).toBe(getsBefore);
  });

  it("is read-only by default when isLeader is omitted", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(memory)));
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    expect(input.readOnly).toBe(true);
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("task-role-memory-clear") as HTMLButtonElement).disabled).toBe(true);
  });

  it("refuses a forced save click when the actor is not a leader", async () => {
    const methods: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        methods.push(init?.method || "GET");
        if (init?.method === "PUT") return json({ ...memory, revision: 3 });
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" />);
    await screen.findByTestId("task-role-memory-input");
    const save = screen.getByTestId("task-role-memory-save") as HTMLButtonElement;
    // Force-enable a control the UI disabled: the handler itself must re-check.
    save.disabled = false;
    fireEvent.click(save);
    await act(async () => {
      await Promise.resolve();
    });
    expect(methods.filter((method) => method === "PUT")).toHaveLength(0);
  });

  it("keeps the draft and reports the server revision on a CAS conflict", async () => {
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return json({ error_category: "revision_conflict", detail: "conflict" }, 409);
        }
        gets += 1;
        return json({ ...memory, revision: 5, manual_text: "别人的版本" });
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "我的约束" } });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));

    expect(await screen.findByText(/版本冲突/)).toBeTruthy();
    expect(input.value).toBe("我的约束");
    expect(screen.getByTestId("task-role-memory").textContent).toContain("revision 5");
    expect(screen.getByTestId("task-role-memory").textContent).not.toContain("已保存");
    expect(gets).toBeGreaterThanOrEqual(2);
  });

  it("does not clear the draft when DELETE hits run_busy", async () => {
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "DELETE") {
          return json({ error_category: "run_busy", detail: "run_busy" }, 409);
        }
        gets += 1;
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    const getsBefore = gets;
    fireEvent.click(screen.getByTestId("task-role-memory-clear"));

    expect(await screen.findByText(/任务正在执行/)).toBeTruthy();
    expect(input.value).toBe("优先覆盖空输入测试");
    expect(gets).toBe(getsBefore);
  });

  it("handles role_mismatch without rewriting the conflict prompt", async () => {
    let gets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return json({ error_category: "role_mismatch", detail: "role changed" }, 409);
        }
        gets += 1;
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    await screen.findByTestId("task-role-memory-input");
    fireEvent.change(screen.getByTestId("task-role-memory-input"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));

    expect((await screen.findByTestId("task-role-memory-conflict")).textContent).toContain("角色已变化");
    expect(screen.queryByText(/内容已被其他人更新/)).toBeNull();
    expect(gets).toBe(1);
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).disabled).toBe(true);
  });

  it("hides the manual body after a forbidden write", async () => {
    let put = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          put += 1;
          return json({ error_category: "forbidden", detail: "forbidden" }, 403);
        }
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    fireEvent.change(await screen.findByTestId("task-role-memory-input"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));

    expect(await screen.findByTestId("task-role-memory-forbidden")).toBeTruthy();
    expect(screen.queryByTestId("task-role-memory-input")).toBeNull();
    expect(screen.queryByTestId("task-role-memory-role-section")).toBeNull();
    expect(put).toBe(1);
  });

  it("never echoes a validation payload back to the user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return json(
            { detail: [{ loc: ["body", "manual_text"], msg: "too long", input: "秘密正文XYZ" }] },
            422,
          );
        }
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    fireEvent.change(await screen.findByTestId("task-role-memory-input"), {
      target: { value: "秘密正文XYZ" },
    });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));

    const alert = await screen.findByTestId("task-role-memory-conflict");
    expect(alert.textContent).toContain("校验");
    expect(alert.textContent).not.toContain("秘密正文XYZ");
  });

  it("keeps the draft and does not claim success on a server error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") return new Response("", { status: 500 });
        return json(memory);
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "保留的草稿" } });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));

    expect(await screen.findByTestId("task-role-memory-conflict")).toBeTruthy();
    expect(input.value).toBe("保留的草稿");
    expect(screen.queryByText(/已保存/)).toBeNull();
  });

  it("describes a missing task instead of echoing the raw detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({ error_category: "task_memory_not_found", detail: "task_memory_not_found" }, 404),
      ),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const error = await screen.findByTestId("task-role-memory-error");
    expect(error.textContent).toContain("任务不存在");
    expect(error.textContent).not.toContain("task_memory_not_found");
  });

  it("clears a previous success notice when the scope changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") return json({ ...memory, revision: 3, manual_text: "新补充" });
        return json(
          String(input).includes("/runs/r2/") ? { ...memory, run_id: "r2", revision: 9 } : memory,
        );
      }),
    );
    const view = render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    fireEvent.change(await screen.findByTestId("task-role-memory-input"), {
      target: { value: "新补充" },
    });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));
    expect(await screen.findByTestId("task-role-memory-notice")).toBeTruthy();

    view.rerender(<TaskRoleMemoryPanel runId="r2" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    await waitFor(() =>
      expect(screen.getByTestId("task-role-memory").textContent).toContain("revision 9"),
    );
    expect(screen.queryByTestId("task-role-memory-notice")).toBeNull();
  });

  it("resets busy on scope change and ignores an old write's settlement", async () => {
    const stalePut = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") return stalePut.promise;
        return Promise.resolve(
          json(
            String(input).includes("/runs/r2/")
              ? { ...memory, run_id: "r2", revision: 9, manual_text: "新任务补充" }
              : memory,
          ),
        );
      }),
    );
    const view = render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    fireEvent.change(await screen.findByTestId("task-role-memory-input"), {
      target: { value: "旧任务草稿" },
    });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).textContent).toContain(
      "保存中",
    );

    view.rerender(<TaskRoleMemoryPanel runId="r2" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    expect(input.value).toBe("新任务补充");
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).textContent).not.toContain(
      "保存中",
    );

    await act(async () => {
      stalePut.resolve(
        json({ ...memory, run_id: "r1", revision: 4, manual_text: "旧任务已保存" }),
      );
      await stalePut.promise;
    });
    expect(input.value).toBe("新任务补充");
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).textContent).not.toContain(
      "保存中",
    );
  });

  it("states that frozen context is recorded, never that it was injected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return json({ ...memory, revision: 3, frozen: true, effective: "next_attempt" });
        }
        return json({ ...memory, frozen: true, effective: "next_attempt" });
      }),
    );
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    await screen.findByTestId("task-role-memory-role-section");
    expect(screen.getByTestId("task-role-memory").textContent).toContain("已记录上下文版本");
    expect(screen.getByTestId("task-role-memory").textContent).not.toContain("已注入");

    fireEvent.change(screen.getByTestId("task-role-memory-input"), {
      target: { value: "新补充" },
    });
    fireEvent.click(screen.getByTestId("task-role-memory-save"));
    expect(await screen.findByText(/已保存，供后续新建尝试使用/)).toBeTruthy();
    expect(screen.getByTestId("task-role-memory").textContent).not.toContain("当前 Agent 已更新");
  });

  it("counts code points and blocks over-limit text without silently truncating", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(memory)));
    render(<TaskRoleMemoryPanel runId="r1" taskCode="T1" role="coder" actorBotId="leader" isLeader />);
    const input = (await screen.findByTestId("task-role-memory-input")) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "字".repeat(4001) } });
    expect(input.value.length).toBe(4001);
    expect(screen.getByTestId("task-role-memory-count").textContent).toContain("4001 / 4000");
    expect((screen.getByTestId("task-role-memory-save") as HTMLButtonElement).disabled).toBe(true);
  });
});