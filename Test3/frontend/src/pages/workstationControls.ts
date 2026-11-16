const TERMINAL_RUN_STATUSES = new Set(["stopped", "terminated", "done"]);

export function isTerminalRunStatus(status?: string | null): boolean {
  return Boolean(status && TERMINAL_RUN_STATUSES.has(status));
}

export function pauseResumeKind(
  run?: { status?: string; paused?: boolean } | null,
): "pause" | "resume" | null {
  if (!run || isTerminalRunStatus(run.status)) return null;
  return run.paused ? "resume" : "pause";
}

export function pauseResumeEnabled(
  run?: { status?: string; paused?: boolean } | null,
  opts?: { statusQueryFailed?: boolean },
): boolean {
  if (opts?.statusQueryFailed) return false;
  return pauseResumeKind(run) !== null;
}

export function gateActionsLocked(opts: {
  resolving?: boolean;
  importing?: boolean;
  statusQueryFailed?: boolean;
}): boolean {
  return Boolean(opts.resolving || opts.importing || opts.statusQueryFailed);
}

export function isDesignImporting(opts: {
  artifactStatus?: string | null;
  inFlight?: { run_id?: string; status?: string } | null;
  activeRunId?: string | null;
}): boolean {
  if (opts.artifactStatus === "importing") return true;
  if (opts.artifactStatus) return false;
  return Boolean(
    opts.inFlight?.status === "importing" &&
      opts.inFlight.run_id &&
      opts.inFlight.run_id === opts.activeRunId,
  );
}

export function autoAdvanceAllowed(opts: {
  autoAdvance: boolean;
  hasPendingGate: boolean;
  gatesLocked: boolean;
}): boolean {
  return Boolean(opts.autoAdvance && opts.hasPendingGate && !opts.gatesLocked);
}

export function scheduleEnabled(
  run?: { status?: string; paused?: boolean; stage?: string } | null,
  opts?: { importing?: boolean; statusQueryFailed?: boolean },
): boolean {
  if (!run || opts?.importing || opts?.statusQueryFailed) return false;
  if (run.paused || isTerminalRunStatus(run.status)) return false;
  return true;
}

export function scheduleNoticeText(scheduleMode?: string | null): string {
  if (scheduleMode === "auto") {
    return "有就绪任务，编排器每 5 秒自动调度一次。";
  }
  return "有就绪任务，请点击调度执行。";
}

export function provenanceMarks(
  provenance?: { generation_label?: string; execution_label?: string } | null,
): string[] {
  return [provenance?.generation_label, provenance?.execution_label].filter(
    (label): label is string => Boolean(label),
  );
}
