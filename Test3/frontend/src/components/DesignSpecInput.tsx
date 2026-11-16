import { useEffect, useRef, useState } from "react";
import { Alert, Button, message } from "antd";
import { FileTextOutlined, UploadOutlined } from "@ant-design/icons";
import { api } from "../api/client";
import { UX_TIMEOUT_MS, startedAtMs, useImportWaitText } from "./designImportWait";

const MAX_BYTES = 100 * 1024;
const POLL_MS = 1000;

interface Props {
  projectName: string;
  onProjectName: (value: string) => void;
  onCreated: (result: any) => void;
  watchingImport?: boolean;
  importArtifacts?: {
    design_input_status?: string;
    design_input_step?: string;
    design_input_started_at?: string;
  } | null;
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
}: Props) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pollStep, setPollStep] = useState("");
  const [pollStartedAt, setPollStartedAt] = useState<string | undefined>();
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

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

  const loadFile = async (file: File) => {
    setError("");
    if (byteLength(await file.text()) > MAX_BYTES) {
      setError(`文件超过 100 KiB 上限：${file.name}`);
      return;
    }
    const body = await file.text();
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
    if (byteLength(text) > MAX_BYTES) {
      setError("设计规格超过 100 KiB 上限");
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
      const project = await api.createProject(name);
      const result = await api.createDesignRun(
        project.id,
        text,
        { kind: fileName ? "file" : "text", name: fileName, note: "" },
        title.trim(),
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

  return (
    <div className="composer-fields" data-testid="design-spec-input">
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
        onChange={(e) => setTitle(e.target.value)}
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
      <textarea
        aria-label="设计规格原文"
        rows={10}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="粘贴设计规格：目标、功能、模块、接口或数据要求、业务规则、约束与验收条件…"
      />
      <div className="composer-actions" style={{ justifyContent: "space-between" }}>
        <span className="mono muted">
          {byteLength(text).toLocaleString()} / {MAX_BYTES.toLocaleString()} 字节
        </span>
        <Button size="small" type="primary" loading={busy} disabled={disabled} onClick={submit}>
          整理并检查
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
