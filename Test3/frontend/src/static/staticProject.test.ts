import { describe, expect, it } from "vitest";
import {
  STATIC_PROJECT_ENTRY,
  STATIC_PROJECT_ID,
  STATIC_RUN_ID,
  isStaticProjectId,
  isStaticRunId,
  loadStaticSnapshot,
  resolveStaticRead,
  staticRequestKind,
  withStaticProject,
  withStaticRun,
} from "./staticProject";

describe("staticRequestKind", () => {
  it("leaves live requests untouched", () => {
    expect(staticRequestKind("/runs")).toBe("none");
    expect(staticRequestKind("/runs/09182750-4271-5e8f-8228-7db27ffb26fd/tasks")).toBe("none");
    expect(staticRequestKind("/tasks/W1-01/pause", { method: "POST", body: "{}" })).toBe("none");
    expect(staticRequestKind("/projects", { method: "POST", body: JSON.stringify({ name: "新项目" }) })).toBe("none");
  });

  it("classifies static reads and writes by path", () => {
    expect(staticRequestKind(`/runs/${STATIC_RUN_ID}/tasks`)).toBe("read");
    expect(staticRequestKind(`/projects/${STATIC_PROJECT_ID}/memberships`)).toBe("read");
    expect(staticRequestKind(`/runs/${STATIC_RUN_ID}/schedule`, { method: "POST", body: "{}" })).toBe("write");
    expect(staticRequestKind(`/projects/${STATIC_PROJECT_ID}/archive`, { method: "POST", body: "{}" })).toBe("write");
    // Static task codes are prefixed so they can never collide with live codes.
    expect(staticRequestKind("/tasks/SW1-01/pause", { method: "POST", body: "{}" })).toBe("write");
    expect(staticRequestKind("/tasks/SW1-01")).toBe("read");
  });

  it("catches writes that only carry the static id in the body", () => {
    expect(
      staticRequestKind("/memory/records", {
        method: "POST",
        body: JSON.stringify({ project_id: STATIC_PROJECT_ID, text: "x" }),
      }),
    ).toBe("write");
  });
});

describe("resolveStaticRead", () => {
  it("serves the snapshot tasks with prefixed codes and ids", async () => {
    const tasks = await resolveStaticRead(`/runs/${STATIC_RUN_ID}/tasks`);
    expect(Array.isArray(tasks)).toBe(true);
    expect(tasks.length).toBeGreaterThan(100);
    expect(tasks[0].code).toBe("SW1-01");
    expect(tasks[0].id.startsWith("st-")).toBe(true);
    expect(tasks[1].card.depends_on).toEqual(["SW1-01"]);
  });

  it("filters event history by after=", async () => {
    const all = await resolveStaticRead(`/runs/${STATIC_RUN_ID}/events/history?after=0`);
    expect(all.length).toBeGreaterThan(10);
    const tail = await resolveStaticRead(`/runs/${STATIC_RUN_ID}/events/history?after=${all.length - 2}`);
    expect(tail).toHaveLength(2);
    expect(tail[0].seq).toBe(all.length - 1);
  });

  it("serves role memory per task and an empty execution trace", async () => {
    const memory = await resolveStaticRead(`/runs/${STATIC_RUN_ID}/tasks/SW1-01/role-memory/coder`);
    expect(memory.task_code).toBe("SW1-01");
    expect(memory.role).toBe("coder");
    expect(memory.role_section.text).toContain("SW1-01");
    const trace = await resolveStaticRead(`/runs/${STATIC_RUN_ID}/tasks/SW1-01/execution-trace`);
    expect(trace.attempts).toEqual([]);
    expect(trace.task_code).toBe("SW1-01");
  });

  it("serves discussion sessions, memberships and the project memory list", async () => {
    const sessions = await resolveStaticRead(`/projects/${STATIC_PROJECT_ID}/discussion-sessions`);
    expect(sessions.items.length).toBeGreaterThan(0);
    const members = await resolveStaticRead(`/projects/${STATIC_PROJECT_ID}/memberships`);
    expect(members.items.length).toBeGreaterThan(1);
    const memories = await resolveStaticRead(`/memory/records?project_id=${STATIC_PROJECT_ID}&visibility=project`);
    expect(memories).toBeTruthy();
  });

  it("resolves unknown static reads to null instead of hitting the network", async () => {
    expect(await resolveStaticRead(`/runs/${STATIC_RUN_ID}/not-a-real-endpoint`)).toBeNull();
  });
});

describe("list augmentation", () => {
  it("appends the static project and run exactly once", () => {
    const projects = withStaticProject([{ id: "live-1", name: "真实项目" }]);
    expect(projects).toHaveLength(2);
    expect(projects[1]).toEqual(STATIC_PROJECT_ENTRY);
    expect(withStaticProject(projects)).toHaveLength(2);

    const runs = withStaticRun([{ id: "live-run", project_id: "live-1" }]);
    expect(runs).toHaveLength(2);
    expect(runs[1].id).toBe(STATIC_RUN_ID);
    expect(runs[1].project_id).toBe(STATIC_PROJECT_ID);
    expect(withStaticRun(runs)).toHaveLength(2);
  });

  it("passes non-array payloads through untouched", () => {
    expect(withStaticProject(null)).toBeNull();
    expect(withStaticRun(undefined)).toBeUndefined();
  });
});

describe("identity helpers and snapshot", () => {
  it("recognises only the static ids", () => {
    expect(isStaticProjectId(STATIC_PROJECT_ID)).toBe(true);
    expect(isStaticProjectId("1958d688-c67e-4ad1-a667-5e6314ab7efd")).toBe(false);
    expect(isStaticRunId(STATIC_RUN_ID)).toBe(true);
    expect(isStaticRunId(undefined)).toBe(false);
  });

  it("loads a snapshot whose entities are all prefixed", async () => {
    const snap = await loadStaticSnapshot();
    expect(snap.project.id).toBe(STATIC_PROJECT_ID);
    expect(snap.project.name).toContain("静态");
    expect(snap.events.every((event) => typeof event.seq === "number")).toBe(true);
    expect(snap.bots.items.length).toBeGreaterThan(0);
    expect(snap.bots.items.every((bot) => bot.bot_id.startsWith("st-"))).toBe(true);
  });
});
