import { useState } from "react";
import { Button, Input } from "antd";
import { api } from "../api/client";
import type { Perform, Run, RuntimeTask, Schedule, TaskCard } from "./stewardTypes";

export const TASK_STATES: Record<string, string> = {
  pending: "待开始", ready: "可调度", running: "执行中", verifying: "验证中", done: "已完成",
  failed: "失败", needs_human: "需人工审核", blocked: "已阻塞", cancelled: "已取消", skipped: "已跳过", stale: "待重新调度",
};

function TaskEdit({ task, cards, run, disabled, perform }: {
  task: TaskCard; cards: TaskCard[]; run: Run; disabled: boolean; perform: Perform;
}) {
  const [title, setTitle] = useState(task.title);
  const [points, setPoints] = useState(task.points);
  const [deps, setDeps] = useState(task.depends_on);
  return <form className="steward-form" onSubmit={(event) => {
    event.preventDefault();
    if (!disabled && title.trim()) perform(() => api.editPlan(run.id, {
      code: task.code, title: title.trim(), points, depends_on: deps, expected_revision: run.revision,
    }));
  }}>
    <label>任务名称<Input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required disabled={disabled} /></label>
    <label>估算点数<select value={points} onChange={(event) => setPoints(Number(event.target.value))} disabled={disabled}>
      {[1, 2, 3, 5, 8].map((point) => <option key={point}>{point}</option>)}
    </select></label>
    <fieldset disabled={disabled}>
      <legend>前置依赖</legend>
      {cards.filter((card) => card.code !== task.code).map((card) => <label key={card.code} className="steward-check">
        <input type="checkbox" checked={deps.includes(card.code)} onChange={(event) => {
          setDeps(event.target.checked ? [...deps, card.code] : deps.filter((code) => code !== card.code));
        }} /> {card.code} {card.title}
      </label>)}
    </fieldset>
    <Button type="primary" htmlType="submit" disabled={disabled || !title.trim()}>保存并重新排期</Button>
  </form>;
}

export default function StewardPlan({ run, cards, tasks, schedule, errors, editable, disabled, perform }: {
  run: Run; cards: TaskCard[]; tasks: RuntimeTask[]; schedule?: Schedule | null; errors?: string[];
  editable: boolean; disabled: boolean; perform: Perform;
}) {
  const [selected, setSelected] = useState("");
  const detail = cards.find((card) => card.code === selected) ?? cards[0];
  const byCode = new Map(cards.map((card) => [card.code, card]));
  const states = new Map(tasks.map((task) => [task.code, task.state]));
  const critical = new Set(schedule?.critical);
  if (!detail) return <p className="muted">确认设计规格后生成任务计划。</p>;
  return <>
    {errors?.length ? <ul className="steward-error" role="alert">{errors.map((error, i) => <li key={i}>{error}</li>)}</ul> : null}
    {schedule && <section aria-label="甘特排期">
      <div className="steward-heading"><h3>甘特排期</h3><span className="mono">{schedule.span} 点 · 并发 {schedule.concurrency}</span></div>
      <p className="muted">以估算点数为单位。橙色标识依赖关键路径，点击任意任务条可查看详情。</p>
      <div className="steward-gantt">
        <div className="steward-ticks" aria-hidden="true"><span>0</span><span>{Math.round(schedule.span / 2)}</span><span>{schedule.span} 点</span></div>
        {schedule.rows.map(({ code, start, end }) => <div className="steward-gantt-row" key={code}>
          <span title={byCode.get(code)?.title}><b className="mono">{code}</b> {byCode.get(code)?.title}</span>
          <div className="steward-track">
            <button type="button" className={critical.has(code) ? "critical" : ""} aria-pressed={detail.code === code}
              aria-label={`${code} ${byCode.get(code)?.title}，${start} 至 ${end} 点${critical.has(code) ? "，关键路径" : ""}`}
              title={`${code} · ${start}–${end} 点`} onClick={() => setSelected(code)}
              style={{ left: `${start / schedule.span * 100}%`, width: `${(end - start) / schedule.span * 100}%` }} />
          </div>
        </div>)}
      </div>
      <p className="steward-wrap"><strong>关键路径</strong> <span className="mono">{schedule.critical.join(" → ")}</span></p>
    </section>}
    <div className="steward-heading"><h3>任务详情</h3><label>选择任务 <select value={detail.code} onChange={(event) => setSelected(event.target.value)}>
      {cards.map((card) => <option key={card.code} value={card.code}>{card.code} {card.title}</option>)}
    </select></label></div>
    <div className="steward-field">
      <strong>{detail.code} {detail.title}</strong> · {TASK_STATES[states.get(detail.code) ?? "pending"]} · {detail.points} 点
      <p>{detail.description}</p>
      <dl className="steward-facts">
        <dt>前置依赖</dt><dd>{detail.depends_on.join("、") || "无"}</dd>
        <dt>写入范围</dt><dd>{detail.write_set.join("、") || "无"}</dd>
        <dt>交付物</dt><dd>{detail.outputs.join("、") || "无"}</dd>
        <dt>验收命令</dt><dd>{detail.acceptance.map((item) => item.cmd.join(" ")).join("；") || "无"}</dd>
      </dl>
      {editable && <TaskEdit key={JSON.stringify([detail.code, run.revision, detail.title, detail.points, detail.depends_on])}
        task={detail} cards={cards} run={run} disabled={disabled} perform={perform} />}
    </div>
  </>;
}
