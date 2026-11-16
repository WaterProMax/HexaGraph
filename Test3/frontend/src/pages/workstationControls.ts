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

export function scheduleEnabled(
  run?: { status?: string; paused?: boolean; stage?: string } | null,
  opts?: { importing?: boolean; statusQueryFailed?: boolean },
): boolean {
  if (!run || opts?.importing || opts?.statusQueryFailed) return false;
  if (run.paused || isTerminalRunStatus(run.status)) return false;
  return true;
}
