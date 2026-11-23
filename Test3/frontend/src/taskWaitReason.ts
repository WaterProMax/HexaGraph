const FAILED_DEPENDENCY_STATES = new Set(["failed", "cancelled", "needs_human"]);

export function taskWaitReason(runtime: any, item: { dependsOn: string[] }, taskByCode: Map<string, any>): string {
  if (!runtime) return "";
  if (runtime.state === "ready" || runtime.state === "stale") return "依赖已满足，等待调度";
  if (runtime.state === "pending" || runtime.state === "blocked") {
    const dependencies = item.dependsOn || [];
    const blockedBy: string[] = runtime.blocked_by ?? dependencies.filter(
      (code) => FAILED_DEPENDENCY_STATES.has(taskByCode.get(code)?.state),
    );
    const waitingOn: string[] = runtime.waiting_on ?? dependencies.filter((code) => {
      const state = taskByCode.get(code)?.state ?? "pending";
      return state !== "done" && !FAILED_DEPENDENCY_STATES.has(state);
    });
    const reasons: string[] = [];
    if (blockedBy.length) {
      reasons.push(
        `失败依赖阻塞：${blockedBy.map((code) => `${code}（${taskByCode.get(code)?.state || "未知"}）`).join("、")}`,
      );
    }
    if (waitingOn.length) reasons.push(`等待依赖：${waitingOn.join("、")}`);
    if (reasons.length) return reasons.join("；");
    if (runtime.state === "blocked") return runtime.last_error || "上游未完成，已阻塞";
    return "依赖已满足，等待调度";
  }
  if (runtime.state === "failed") return runtime.last_error || runtime.prev_output || "任务失败，等待重试或人工处理";
  return "";
}
