import { Alert, Tag } from "antd";

interface Props {
  artifacts: any;
  result: any;
}

const IMPORT_STATUS: Record<string, { type: "info" | "warning" | "error"; message: string }> = {
  importing: { type: "info", message: "正在整理设计规格，尚未进入确认或任务分解" },
  needs_input: { type: "warning", message: "缺少必要内容，未进入 DESIGN 确认或任务分解" },
  needs_split: { type: "warning", message: "输入需要拆分，未进入 DESIGN 确认或任务分解" },
  failed: { type: "error", message: "整理失败，未进入 DESIGN 确认或任务分解" },
  awaiting_confirmation: { type: "info", message: "整理完成，等待 DESIGN 确认；尚未进入任务分解或调度" },
  design_confirmed: { type: "info", message: "DESIGN 已确认，等待 PLAN 确认；尚未进入调度" },
  plan_confirmed: { type: "info", message: "PLAN 已确认，任务已建立；调度状态以任务列表为准" },
};

export default function DesignSpecPreview({ artifacts, result }: Props) {
  const spec = result?.spec ?? artifacts?.spec;
  const design = result?.design ?? artifacts?.design;
  const missing: string[] = result?.missing ?? artifacts?.design_input_missing ?? [];
  const errors: string[] = result?.errors ?? artifacts?.design_input_errors ?? [];
  const input = result?.input ?? artifacts?.design_input;
  const provenance = result?.provenance ?? artifacts?.provenance;
  const checks = result?.checks ?? artifacts?.design_input_checks;
  const importStatus = IMPORT_STATUS[result?.status ?? artifacts?.design_input_status];

  return (
    <section className="glass-panel" style={{ padding: 14 }} data-testid="design-spec-preview">
      <div className="section-title">
        <span>设计规格整理</span>
        {provenance?.generation_label && <span className="hint">{provenance.generation_label}</span>}
      </div>

      {importStatus && (
        <Alert
          data-testid="design-import-status"
          style={{ marginBottom: 10 }}
          type={importStatus.type}
          showIcon
          message={importStatus.message}
        />
      )}

      {input && (
        <div className="kv" style={{ marginBottom: 10 }}>
          <div className="k">输入来源</div>
          <div className="mono">
            {input.source?.kind === "file" ? "文件" : "粘贴"} · {input.source?.name || "未命名"} · {input.chars} 字符
          </div>
          <div className="k">原文指纹</div>
          <div className="mono muted">{(input.sha256 || "").slice(0, 16)}</div>
        </div>
      )}

      {missing.length > 0 && (
        <Alert
          style={{ marginBottom: 8 }}
          type="warning"
          showIcon
          message={`缺少必要内容 ${missing.length} 项`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          }
        />
      )}

      {errors.length > 0 && (
        <Alert
          style={{ marginBottom: 8 }}
          type="error"
          showIcon
          message={`结构检查未通过 ${errors.length} 项`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {errors.slice(0, 8).map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          }
        />
      )}

      {spec ? (
        <div style={{ marginBottom: 10 }}>
          <div className="section-title">
            <span>需求规格</span>
            <span className="hint">
              {(spec.features || []).length} 功能 · {(spec.nonfunc || []).length} 非功能
            </span>
          </div>
          {(spec.features || []).map((f: any) => (
            <div className="row" key={f.code} style={{ cursor: "default" }}>
              <span className="dot completed" />
              <span className="row-main">
                <span className="row-meta">
                  <span className="code">{f.code}</span>
                  <Tag color={f.priority === "P0" ? "red" : "default"}>{f.priority}</Tag>
                </span>
                <span className="row-title">
                  <span className="text">{f.title}</span>
                </span>
                <span className="row-sub">
                  {(f.acceptance || []).join("；") || "缺少验收条件"}
                </span>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="well muted" style={{ padding: 12 }}>
          尚未整理出需求规格
        </div>
      )}

      {design ? (
        <div>
          <div className="section-title">
            <span>设计规格</span>
            <span className="hint">
              {(design.modules || []).length} 模块 · {(design.interfaces || []).length} 接口
            </span>
          </div>
          {(design.modules || []).map((m: any) => (
            <div className="row" key={m.code} style={{ cursor: "default" }}>
              <span className="dot completed" />
              <span className="row-main">
                <span className="row-meta">
                  <span className="code">{m.code}</span>
                  <span className="row-state">来源 {(m.sources || []).join(", ")}</span>
                </span>
                <span className="row-title">
                  <span className="text">{m.name}</span>
                </span>
                <span className="row-sub">{m.responsibility}</span>
              </span>
            </div>
          ))}
          {checks && (
            <div className="mono muted" style={{ marginTop: 8 }}>
              SPEC 检查 {checks.spec?.length || 0} 项 · DESIGN 检查 {checks.design?.length || 0} 项
            </div>
          )}
        </div>
      ) : (
        <div className="well muted" style={{ padding: 12 }}>
          尚未整理出设计规格
        </div>
      )}
    </section>
  );
}
