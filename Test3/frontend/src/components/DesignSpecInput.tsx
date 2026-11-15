import { useRef, useState } from "react";
import { Alert, Button, message } from "antd";
import { FileTextOutlined, UploadOutlined } from "@ant-design/icons";
import { api } from "../api/client";

const MAX_BYTES = 100 * 1024;

interface Props {
  projectName: string;
  onProjectName: (value: string) => void;
  onCreated: (result: any) => void;
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export default function DesignSpecInput({ projectName, onProjectName, onCreated }: Props) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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
    setBusy(true);
    try {
      const name = projectName.trim() || title.trim() || "设计规格导入";
      const project = await api.createProject(name);
      const result = await api.createDesignRun(
        project.id,
        text,
        { kind: fileName ? "file" : "text", name: fileName, note: "" },
        title.trim(),
      );
      onCreated(result);
      if (result.status === "awaiting_confirmation") {
        message.success("设计规格已整理，等待你确认");
      } else if (result.status === "needs_input") {
        message.warning("设计规格存在缺项，尚未进入任务分解");
      } else {
        message.error(result.message || "设计规格未能进入确认阶段");
      }
    } catch (err: any) {
      setError(err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

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
        <Button size="small" type="primary" loading={busy} onClick={submit}>
          整理并检查
        </Button>
      </div>
      {error && <Alert type="error" showIcon message={error} />}
    </div>
  );
}
