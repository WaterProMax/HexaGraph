import { describe, expect, it } from "vitest";
import { taskWaitReason } from "./taskWaitReason";

const item = { dependsOn: ["B", "C"] };
const tasks = new Map<string, any>([
  ["B", { state: "failed" }],
  ["C", { state: "pending" }],
]);

describe("task wait reason", () => {
  it("distinguishes failed dependencies from ordinary unfinished dependencies", () => {
    expect(taskWaitReason({ state: "blocked", blocked_by: ["B"], waiting_on: ["C"] }, item, tasks)).toBe(
      "失败依赖阻塞：B（failed）；等待依赖：C",
    );
    expect(taskWaitReason({ state: "pending", blocked_by: [], waiting_on: ["B", "C"] }, item, tasks)).toBe(
      "等待依赖：B、C",
    );
  });

  it("clears the failure hint after the dependency recovers", () => {
    const recovered = new Map<string, any>([
      ["B", { state: "done" }],
      ["C", { state: "done" }],
    ]);
    expect(taskWaitReason({ state: "ready", blocked_by: [], waiting_on: [] }, item, recovered)).toBe(
      "依赖已满足，等待调度",
    );
  });
});
