import { useEffect, useRef, useState } from "react";
import { Alert, Button, message } from "antd";
import { FileTextOutlined, UploadOutlined } from "@ant-design/icons";
import { api } from "../api/client";
import { UX_TIMEOUT_MS, startedAtMs, useImportWaitText } from "./designImportWait";
import { composeDeepSeekSubmission, stripRuntimeBoundary } from "./designSpecText";

const MAX_BYTES = 100 * 1024;
const POLL_MS = 1000;

const RETRY_STATUSES = new Set(["failed", "needs_input", "needs_split", "timeout"]);

interface DesignInputFields {
  title?: string;
  text?: string;
  source?: { kind?: string; name?: string };
}

interface Props {
  projectName: string;
  onProjectName: (value: string) => void;
  onCreated: (result: any) => void;
  watchingImport?: boolean;
  importArtifacts?: {
    design_input_status?: string;
    design_input_step?: string;
    design_input_started_at?: string;
    design_input?: DesignInputFields;
  } | null;
  projectId?: string;
  onProjectId?: (id: string) => void;
  runId?: string;
  provider?: "existing" | "deepseek";
  /** Bump to open the original text and focus it (e.g. "去改原文" in the preview). */
  editSourceSignal?: number;
}

function fieldsFromInput(input?: DesignInputFields | null): { title: string; text: string; fileName: string } {
  return {
    title: input?.title || "",
    // 导入结果里的 text 含系统追加的运行边界小节；回填时去掉，避免重试时重复叠加。
    text: stripRuntimeBoundary(input?.text || ""),
    fileName: input?.source?.name || "",
  };
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

function isAbort(err: unknown): boolean {
  return Boolean(err && typeof err === "object" && (err as { name?: string }).name === "AbortError");
}

async function sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export default function DesignSpecInput({
  projectName,
  onProjectName,
  onCreated,
  watchingImport = false,
  importArtifacts = null,
  projectId,
  onProjectId,
  runId,
  provider = "existing",
  editSourceSignal = 0,
}: Props) {
  const initial = fieldsFromInput(importArtifacts?.design_input);
  const [title, setTitle] = useState(initial.title);
  const [text, setText] = useState(initial.text);
  const [fileName, setFileName] = useState(initial.fileName);
  const [boundaries, setBoundaries] = useState({ language: "", framework: "", storage: "", deployment: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pollStep, setPollStep] = useState("");
  const [pollStartedAt, setPollStartedAt] = useState<string | undefined>();
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const dirtyRef = useRef(false);
  const lastRunIdRef = useRef(runId);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const rawToggledRef = useRef(false);
  // Once an import produced a status the source is round-trippable: fold it away but keep it editable.
  const backfilled = Boolean(importArtifacts?.design_input_status);
  const [rawOpen, setRawOpen] = useState(!backfilled);

  const waitText = useImportWaitText({
    active: busy || watchingImport,
    status: importArtifacts?.design_input_status || (busy || watchingImport ? "importing" : undefined),
    step: importArtifacts?.design_input_step || pollStep,
    startedAt: importArtifacts?.design_input_started_at || pollStartedAt,
  });

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (lastRunIdRef.current !== runId) {
      lastRunIdRef.current = runId;
      dirtyRef.current = false;
      rawToggledRef.current = false;
    }
    if (dirtyRef.current) return;
    const next = fieldsFromInput(importArtifacts?.design_input);
    if (!importArtifacts?.design_input) return;
    setTitle(next.title);
    setText(next.text);
    setFileName(next.fileName);
  }, [runId, importArtifacts]);

  useEffect(() => {
    if (rawToggledRef.current) return;
    // Never fold the text away under a user who is typing in it.
    if (backfilled && document.activeElement === textRef.current) return;
    setRawOpen(!backfilled);
  }, [backfilled, runId]);

  useEffect(() => {
    if (!editSourceSignal) return;
    rawToggledRef.current = true;
    setRawOpen(true);
    window.setTimeout(() => textRef.current?.focus(), 0);
  }, [editSourceSignal]);

  const markDirty = () => {
    dirtyRef.current = true;
  };

  const loadFile = async (file: File) => {
    setError("");
    if (byteLength(await file.text()) > MAX_BYTES) {
      setError(`文件超过 100 KiB 上限：${file.name}`);
      return;
    }
    const body = await file.text();
    markDirty();
    setText(body);
    setFileName(file.name);
    if (!title.trim()) setTitle(file.name.replace(/\.(md|txt)$/i, ""));
  };

  const watchImport = async (runId: string, signal: AbortSignal) => {
    let started = Date.now();
    try {
      while (!signal.aborted) {
        if (Date.now() - started >= UX_TIMEOUT_MS) {
          return;
        }
        const arts = await api.artifacts(runId, { signal });
        const status = arts?.design_input_status;
        setPollStep(arts?.design_input_step || "");
        if (arts?.design_input_started_at) {
          setPollStartedAt(arts.design_input_started_at);
          started = startedAtMs(arts.design_input_started_at, started);
        }
        if (status && status !== "importing") {
          onCreated({
            run_id: runId,
            status,
            spec: arts.spec,
            design: arts.design,
            missing: arts.design_input_missing,
            errors: arts.design_input_errors,
            error_category: arts.design_input_error_category,
            checks: arts.design_input_checks,
            input: arts.design_input,
            provenance: arts.provenance,
            message: arts.design_input_message,
          });
          if (status === "awaiting_confirmation") {
            message.success("设计规格已整理，等待你确认");
          } else if (status === "needs_input") {
            message.warning("设计规格存在缺项，尚未进入任务分解");
          } else if (status === "failed") {
            message.error(arts.design_input_message || "设计规格未能进入确认阶段");
          }
          return;
        }
        await sleep(POLL_MS, signal);
      }
    } catch (err) {
      if (isAbort(err)) return;
      throw err;
    }
  };

  const submit = async () => {
    setError("");
    if (!text.trim()) {
      setError("设计规格为空");
      return;
    }
    const submissionText = provider === "deepseek" ? composeDeepSeekSubmission(text, boundaries) : text;
    if (byteLength(submissionText) > MAX_BYTES) {
      setError(provider === "deepseek" ? "设计规格与运行边界超过 100 KiB 上限" : "设计规格超过 100 KiB 上限");
      return;
    }
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(true);
    setPollStep("");
    setPollStartedAt(undefined);
    try {
      const name = projectName.trim() || title.trim() || "设计规格导入";
      let pid = projectId?.trim() || "";
      if (!pid) {
        const project = await api.createProject(name);
        pid = String(project.id || "");
        if (pid) onProjectId?.(pid);
      }
      if (!pid) throw new Error("未能创建或复用项目");
      const result = await api.createDesignRun(
        pid,
        submissionText,
        { kind: fileName ? "file" : "text", name: fileName, note: provider === "deepseek" ? "DeepSeek 真实运行" : "" },
        title.trim(),
        provider,
        { signal: ac.signal },
      );
      onCreated(result);
      if (result.status === "importing") {
        await watchImport(result.run_id, ac.signal);
      } else if (result.status === "awaiting_confirmation") {
        message.success("设计规格已整理，等待你确认");
      } else if (result.status === "needs_input") {
        message.warning("设计规格存在缺项，尚未进入任务分解");
      } else {
        message.error(result.message || "设计规格未能进入确认阶段");
      }
    } catch (err: any) {
      if (isAbort(err)) return;
      if (err?.status === 409 && err?.run_id) {
        onCreated({ run_id: err.run_id, status: "importing", message: err.summary || err.message });
        try {
          await watchImport(err.run_id, ac.signal);
        } catch (watchErr: any) {
          if (!isAbort(watchErr)) setError(watchErr?.message || String(watchErr));
        }
        return;
      }
      setError(err?.message || String(err));
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
      setBusy(false);
    }
  };

  const disabled = busy || watchingImport;
  const retryable = RETRY_STATUSES.has(importArtifacts?.design_input_status || "");
  const submitLabel = retryable
    ? "修改原文后重新提交"
    : provider === "deepseek"
      ? "调用 DeepSeek 并检查"
      : "整理并检查";

  return (
    <div className="composer-fields" data-testid="design-spec-input" data-provider={provider}>
      {provider === "deepseek" && (
        <>
          <div className="design-boundaries" aria-label="DeepSeek 运行边界">
            {([
              ["language", "目标语言", "例如 Python 3.11"],
              ["framework", "目标框架", "例如 FastAPI；未指定可留空"],
              ["storage", "存储", "例如 SQLite；未指定可留空"],
              ["deployment", "部署边界", "默认：本地受限工作区"],
            ] as const).map(([key, label, placeholder]) => (
              <input
                key={key}
                aria-label={label}
                value={boundaries[key]}
                placeholder={placeholder}
                onChange={(e) => {
                  markDirty();
                  setBoundaries((current) => ({ ...current, [key]: e.target.value }));
                }}
              />
            ))}
          </div>
        </>
      )}
      <input
        className="composer-name"
        aria-label="项目名称"
        value={projectName}
        onChange={(e) => onProjectName(e.target.value)}
        placeholder="项目名称"
      />
      <input
        className="composer-name"
        aria-label="设计规格标题"
        value={title}
        onChange={(e) => {
          markDirty();
          setTitle(e.target.value);
        }}
        placeholder="设计规格标题（可选）"
      />
      <label className="design-file">
        <Button size="small" icon={<UploadOutlined />} onClick={() => fileRef.current?.click()}>
          读取 Markdown / 文本
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".md,.markdown,.txt,text/plain,text/markdown"
          aria-label="读取设计规格文件"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void loadFile(file);
            e.target.value = "";
          }}
        />
        {fileName && (
          <span className="mono muted">
            <FileTextOutlined /> {fileName}
          </span>
        )}
      </label>
      <details
        className="design-raw"
        open={rawOpen}
        onToggle={(e) => {
          const open = (e.currentTarget as HTMLDetailsElement).open;
          if (open !== rawOpen) {
            rawToggledRef.current = true;
            setRawOpen(open);
          }
        }}
      >
        <summary>
          设计规格原文
          <span className="mono muted">{rawOpen ? "" : backfilled ? "已折叠 · 展开可修改后重新提交" : ""}</span>
        </summary>
        <textarea
          ref={textRef}
          aria-label="设计规格原文"
          rows={5}
          value={text}
          onChange={(e) => {
            markDirty();
            setText(e.target.value);
          }}
          placeholder="粘贴设计规格：目标、功能、模块、接口或数据要求、业务规则、约束与验收条件…"
        />
      </details>
      <details className="design-hint" data-testid="design-demo-hint">
        <summary>输入说明</summary>
        <div className="mono muted" style={{ lineHeight: 1.5 }}>
          {provider === "deepseek"
            ? "请提供明确的功能、模块、接口或数据要求和验收条件。整理后仍需你确认 DESIGN，再生成 PLAN；确认 PLAN 后才会物化并调度任务。"
            : "离线主演示请用 examples/design-specs/self-study-room.md，与预置座位查询任务一致。scripted 使用预置测试输出，不会按任意文档理解业务。club-signup.md 只验证上传与原文保存，不代表系统从该文档生成了任务。"}
        </div>
      </details>
      <div className="composer-actions" style={{ justifyContent: "space-between" }}>
        <span className="mono muted">
          {byteLength(text).toLocaleString()} / {MAX_BYTES.toLocaleString()} 字节
        </span>
        <Button size="small" type="primary" loading={busy} disabled={disabled} onClick={submit}>
          {submitLabel}
        </Button>
      </div>
      {waitText && (
        <div className="mono muted" data-testid="design-import-wait">
          {waitText}
        </div>
      )}
      {error && <Alert type="error" showIcon message={error} />}
    </div>
  );
}
