import { useEffect, useRef, useState } from "react";

export const UX_TIMEOUT_MS = 10 * 60 * 1000;
export const UX_TIMEOUT_COPY = "等待已停止（未取消后端整理）。可刷新查看状态。";

export function importWaitCopy(step: string, seconds: number): string {
  const label =
    step === "spec" ? "正在整理需求规格" : step === "design" ? "正在整理设计规格" : "正在整理…";
  return `${label} ${seconds} 秒`;
}

export function startedAtMs(startedAt: string | undefined, fallback: number): number {
  if (!startedAt) return fallback;
  const parsed = Date.parse(startedAt);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function importWaitText(args: {
  status?: string;
  step?: string;
  startedAt?: string;
  now?: number;
  fallbackStart?: number;
}): string {
  if (args.status && args.status !== "importing") return "";
  const now = args.now ?? Date.now();
  const started = startedAtMs(args.startedAt, args.fallbackStart ?? now);
  if (now - started >= UX_TIMEOUT_MS) return UX_TIMEOUT_COPY;
  return importWaitCopy(args.step || "", Math.max(0, Math.floor((now - started) / 1000)));
}

export function designComposerForced(
  artifacts?: { design_input_status?: string; design_input?: unknown } | null,
  run?: { origin?: string } | null,
): boolean {
  return (
    artifacts?.design_input_status === "importing" ||
    run?.origin === "design_spec" ||
    Boolean(artifacts?.design_input)
  );
}

export function useImportWaitText(opts: {
  active: boolean;
  status?: string;
  step?: string;
  startedAt?: string;
}): string {
  const [now, setNow] = useState(() => Date.now());
  const fallbackStartRef = useRef<number | null>(null);
  useEffect(() => {
    if (!opts.active) {
      fallbackStartRef.current = null;
      return;
    }
    if (fallbackStartRef.current == null) fallbackStartRef.current = Date.now();
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [opts.active, opts.startedAt]);
  if (!opts.active) return "";
  return importWaitText({
    status: opts.status,
    step: opts.step,
    startedAt: opts.startedAt,
    now,
    fallbackStart: fallbackStartRef.current ?? now,
  });
}
