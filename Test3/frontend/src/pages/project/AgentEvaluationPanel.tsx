import { useMemo } from "react";
import { Alert, Button, Empty, message } from "antd";
import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import { agentsToCsv, downloadCsv, formatDuration, formatNumber } from "./runMonitor";
import { useRunMonitor } from "./useRunMonitor";
import "./runMonitor.css";

type Props = { runId?: string };

export function AgentEvaluationPanel({ runId }: Props) {
  const monitor = useRunMonitor(runId);
  const agents = monitor.data?.agents || [];
  const totals = useMemo(() => {
    const done = agents.reduce((sum, agent) => sum + agent.done, 0);
    const failed = agents.reduce((sum, agent) => sum + agent.failed, 0);
    const attempted = done + failed;
    return {
      done,
      failed,
      attempted,
      successRate: attempted ? Math.round((done * 100) / attempted) : 0,
      tokens: agents.reduce((sum, agent) => sum + agent.tokens_used, 0),
      fallbacks: agents.reduce((sum, agent) => sum + agent.fallback_count, 0),
    };
  }, [agents]);

  const exportCsv = () => {
    if (!agents.length) return;
    try {
      downloadCsv(`agent-evaluation-${(runId || "run").slice(0, 8)}.csv`, agentsToCsv(agents));
      message.success("Agent 评测 CSV 已导出");
    } catch (err: any) {
      message.error(err?.message || "CSV 导出失败");
    }
  };

  return (
    <div className="agent-eval" data-testid="agent-evaluation">
      <div className="mon-head">
        <div>
          <div className="mon-kicker">Agent 评测</div>
          <div className="mon-head-title">
            <span className="mono">{runId || "未绑定运行"}</span>
            <span className="mon-note">成功率 = 完成 /（完成 + 失败）</span>
          </div>
        </div>
        <div className="mon-run-actions">
          <Button size="small" type="text" icon={<ReloadOutlined />} aria-label="刷新评测" onClick={() => void monitor.refresh()} />
          <Button size="small" icon={<DownloadOutlined />} disabled={!agents.length} onClick={exportCsv}>
            导出 CSV
          </Button>
        </div>
      </div>

      {monitor.error && <Alert type="warning" showIcon message={monitor.error} style={{ marginBottom: 12 }} />}

      <div className="mon-kpis">
        <div className="mon-kpi"><span>参与 Agent</span><strong>{agents.length}</strong><em>按任务角色</em></div>
        <div className="mon-kpi"><span>完成任务</span><strong>{totals.done}</strong><em>已验收</em></div>
        <div className="mon-kpi tone-failed"><span>失败</span><strong>{totals.failed}</strong><em>待修复</em></div>
        <div className="mon-kpi tone-running"><span>成功率</span><strong>{totals.successRate}%</strong><em>{totals.attempted} 次尝试</em></div>
        <div className="mon-kpi"><span>Token</span><strong>{formatNumber(totals.tokens)}</strong><em>合计消耗</em></div>
        <div className="mon-kpi"><span>模型回退</span><strong>{totals.fallbacks}</strong><em>主模型失败后</em></div>
      </div>

      {!agents.length ? (
        <Empty description={runId ? "还没有可评测的任务执行数据。" : "还没有绑定运行。"} />
      ) : (
        <div className="eval-list">
          {agents.map((agent) => (
            <article className="eval-card" key={`${agent.role}-${agent.slot}`}>
              <header className="eval-card-head">
                <div>
                  <strong>{agent.role}</strong>
                  <span>{agent.model || "—"} · {agent.slot || "—"}</span>
                </div>
                <div className="eval-rate">
                  <strong>{agent.success_rate}%</strong>
                  <span>成功率</span>
                </div>
              </header>
              <div className="eval-grid">
                <span>任务 <b>{agent.total}</b></span>
                <span>完成 <b>{agent.done}</b></span>
                <span>失败 <b className={agent.failed ? "eval-failed" : ""}>{agent.failed}</b></span>
                <span>Token <b>{formatNumber(agent.tokens_used)}</b></span>
                <span>平均修复 <b>{agent.avg_repair_rounds}</b></span>
                <span>模型回退 <b>{agent.fallback_count}</b></span>
                <span>平均耗时 <b>{formatDuration(agent.avg_task_seconds)}</b></span>
                <span>完成率 <b>{agent.completion_rate}%</b></span>
              </div>
              <div className="eval-reasons">
                {agent.failure_reasons.length === 0 && <span className="muted">暂无失败原因</span>}
                {agent.failure_reasons.map((item) => (
                  <span
                    className="eval-reason"
                    key={item.reason}
                    title={`${item.reason} × ${item.count}`}
                  >
                    {item.reason} ×{item.count}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}