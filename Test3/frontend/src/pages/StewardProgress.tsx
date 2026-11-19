import { useState } from "react";
import { Button, Input } from "antd";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { TASK_STATES } from "./StewardPlan";
import type { Artifacts, Experience, Perform, Proposal, Run, RuntimeTask } from "./stewardTypes";

function ProposalSummary({ proposal }: { proposal: Proposal }) {
  return <>
    <p><strong>{proposal.elevator}</strong></p>
    <p>{proposal.implementation}</p>
    <p className="mono">估算 {proposal.estimate_total} 点</p>
    <ul>{proposal.features.map((item, i) => <li key={i}>{item.name} · {item.points} 点</li>)}</ul>
    {proposal.risks.length > 0 && <details><summary>风险与预案</summary>
      <ul>{proposal.risks.map((item, i) => <li key={i}>{item.code} · {item.verification} · {item.fallback}</li>)}</ul>
    </details>}
  </>;
}

export function StewardRequirements({ run, artifacts, candidate, setCandidate, canChoose, busy }: {
  run: Run; artifacts: Artifacts; candidate: string; setCandidate: (id: string) => void; canChoose: boolean; busy: boolean;
}) {
  const comparison = artifacts.steward_comparison;
  return <div className="steward-stack">
    <details className="steward-field" open={!artifacts.idea_card && !artifacts.spec}>
      <summary>需求原文</summary><p className="steward-multiline">{run.idea}</p>
    </details>
    {artifacts.idea_card && <details className="steward-field">
      <summary>初步做法</summary><p>{artifacts.idea_card.approach}</p>
      <ul>{artifacts.idea_card.features.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </details>}
    {!!artifacts.issues?.length && <details className="steward-field" open={run.stage === "1"}>
      <summary>讨论与争议 · {artifacts.issues.length} 项</summary>
      <ul>{artifacts.issues.map((item) => <li key={item.code}><b>{item.code} · {item.status}</b> {item.text}{item.conclusion && ` — ${item.conclusion}`}</li>)}</ul>
      {!!artifacts.utterances?.length && <details><summary>讨论记录</summary>
        <ul>{artifacts.utterances.map((item, i) => <li key={i}><b>{item.role}</b> {item.body}</li>)}</ul>
      </details>}
    </details>}
    {comparison && <section aria-label="候选方案">
      <h3>候选方案</h3>
      {!!comparison.errors.length && <ul className="steward-error">{comparison.errors.map((item, i) => <li key={i}>{item}</li>)}</ul>}
      <div className="steward-candidates">{comparison.candidates.map((item) => <article key={item.id} className="steward-field">
        {canChoose ? <label className="steward-check"><input type="radio" name="proposal" value={item.id} disabled={busy}
          checked={candidate === item.id} onChange={() => setCandidate(item.id)} />方案 {item.id} · {item.focus}</label> : <strong>方案 {item.id} · {item.focus}</strong>}
        <ProposalSummary proposal={item.proposal} />
      </article>)}</div>
      {canChoose && comparison.candidates.length > 1 && <label className="steward-field steward-check">
        <input type="radio" name="proposal" value="fusion" disabled={busy} checked={candidate === "fusion"} onChange={() => setCandidate("fusion")} />融合两份方案后评审
      </label>}
    </section>}
    {artifacts.proposal && <details className="steward-field" open={run.stage === "3"}>
      <summary>进入评审的方案</summary><ProposalSummary proposal={artifacts.proposal} />
    </details>}
    {!!artifacts.reviews?.length && <section aria-label="多视角评审">
      <h3>多视角评审</h3>
      <div className="steward-candidates">{artifacts.reviews.map((review, i) => <article key={i} className="steward-field">
        <div className="steward-heading"><strong>{review.dimension}</strong><span className="mono">{review.score} / 5</span></div>
        <ul>{review.opinions.map((op, i) => <li key={i}>{op.blocking && <strong>阻断 · </strong>}{op.text}</li>)}</ul>
      </article>)}</div>
    </section>}
    {artifacts.spec && <details className="steward-field" open={run.stage === "4"}>
      <summary>需求规格</summary>
      <ul>{artifacts.spec.features.map((f) => <li key={f.code}><b>{f.code} {f.title}</b><ul>{f.acceptance.map((x, i) => <li key={i}>{x}</li>)}</ul></li>)}</ul>
    </details>}
    {artifacts.design && <details className="steward-field" open={run.stage === "5"}>
      <summary>设计模块</summary>
      <ul>{artifacts.design.modules.map((m) => <li key={m.code}><b>{m.code} {m.name}</b> {m.responsibility}</li>)}</ul>
    </details>}
  </div>;
}

export function StewardExecution({ run, tasks, artifacts, busy, perform }: {
  run: Run; tasks: RuntimeTask[]; artifacts: Artifacts; busy: boolean; perform: Perform;
}) {
  const terminal = ["done", "terminated", "stopped"].includes(run.status);
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState("");
  const task = tasks.find((item) => item.code === selected) ?? tasks[0];
  const done = tasks.filter((item) => item.state === "done").length;
  const acceptanceGate = [...run.gates].reverse().find((item) => item.kind === "验收确认");
  return <div className="steward-stack">
    <div className="steward-heading">
      <h3>开发进度 {done} / {tasks.length}</h3>
      <div className="steward-actions">
        <Button disabled={busy || terminal || !tasks.length} onClick={() => perform(() => run.paused ? api.resumeRun(run.id) : api.pauseRun(run.id))}>{run.paused ? "继续" : "暂停"}</Button>
        <Button type="primary" disabled={busy || terminal || run.paused || run.stage !== "7" || !tasks.some((item) => item.state === "ready")}
          onClick={() => perform(() => api.schedule(run.id))}>推进调度</Button>
      </div>
    </div>
    {tasks.length ? <>
      <progress aria-label="任务完成进度" value={done} max={tasks.length} />
      <div className="phase-items">{tasks.map((item) => <button className="row" type="button" key={item.id} aria-pressed={item.code === task?.code}
        onClick={() => { setSelected(item.code); setReason(""); }}>
        <span className={`dot ${item.state === "done" ? "completed" : ["running", "verifying"].includes(item.state) ? "in_progress" : ["blocked", "needs_human", "failed"].includes(item.state) ? "error" : "pending"}`} />
        <span className="steward-wrap">{item.code} · {item.card.title}</span><span className="mono">{TASK_STATES[item.state] ?? item.state}</span>
      </button>)}</div>
    </> : <p className="muted">任务计划确认后才会进入调度。</p>}
    {task && <article className="steward-field">
      <h3>{task.code} {task.card.title}</h3>
      <p>{task.card.description}</p>
      {task.last_error && <p className="steward-error" role="status">{task.last_error}</p>}
      {!!task.evidence?.length && <details><summary>任务验收证据</summary>
        {task.evidence.map((item, i) => <pre key={i}>{item.cmd?.join(" ")}{item.exit_code !== undefined ? ` · 退出码 ${item.exit_code}` : ""}{item.output ? `\n${item.output}` : ""}</pre>)}
      </details>}
      {["failed", "needs_human"].includes(task.state) && <div className="steward-form">
        <label>返工说明<Input.TextArea value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy || terminal} /></label>
        <Button disabled={busy || terminal} onClick={() => perform(() => api.control(task.id, "retry", task.revision, reason.trim()))}>退回重试</Button>
        <Link to={`${run.provenance?.mode === "deepseek" ? "/deepseek" : "/workstation"}/${run.id}`}>到工作台处理接管</Link>
      </div>}
    </article>}
    <section className="steward-field" aria-label="项目交付">
      <h3>交付验收</h3>
      {artifacts.acceptance ? <>
        <p>{acceptanceGate?.payload.pass === true ? "通过检查" : "需核对验收结果"}</p>
        {artifacts.build_tag && <p>交付版本 <code>{artifacts.build_tag}</code></p>}
        {artifacts.release_dir && <p className="steward-wrap">本机产物目录 <code>{artifacts.release_dir}</code></p>}
        <details><summary>验收报告</summary><pre>{JSON.stringify(artifacts.acceptance, null, 2)}</pre></details>
      </> : <p className="muted">执行结束后在这里查看最终验收报告。</p>}
    </section>
  </div>;
}

export function StewardMemory({ runId, items, busy, perform }: { runId: string; items: Experience[]; busy: boolean; perform: Perform }) {
  const [filter, setFilter] = useState("");
  const [title, setTitle] = useState("");
  const [lesson, setLesson] = useState("");
  const visible = items.filter((item) => `${item.title} ${item.lesson}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const labels = { candidate: "待审核", published: "已收录", rejected: "已退回" };
  return <div className="steward-stack">
    <label>搜索项目经验<Input value={filter} onChange={(event) => setFilter(event.target.value)} /></label>
    {visible.map((item) => <article className="steward-field" key={item.id}>
      <div className="steward-heading"><strong>{item.title}</strong><span>{labels[item.status]}</span></div>
      <p className="steward-multiline">{item.lesson}</p>
      {item.status === "candidate" && <div className="steward-actions">
        <Button type="primary" disabled={busy} onClick={() => perform(() => api.reviewExperience(item.run_id, item.id, "publish"))}>收录经验</Button>
        <Button disabled={busy} onClick={() => perform(() => api.reviewExperience(item.run_id, item.id, "reject"))}>退回经验</Button>
      </div>}
    </article>)}
    {!visible.length && <p className="muted">{items.length ? "没有匹配的经验。" : "项目暂无经验。"}</p>}
    <form className="steward-form" onSubmit={(event) => {
      event.preventDefault();
      if (!busy && title.trim() && lesson.trim()) perform(async () => {
        await api.saveExperience(runId, title.trim(), lesson.trim());
        setTitle("");
        setLesson("");
      });
    }}>
      <h3>记录经验</h3>
      <label>经验标题<Input value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={120} disabled={busy} /></label>
      <label>问题、做法与验证<Input.TextArea value={lesson} onChange={(event) => setLesson(event.target.value)} required maxLength={3000} disabled={busy} rows={4} /></label>
      <Button type="primary" htmlType="submit" disabled={busy || !title.trim() || !lesson.trim()}>提交审核</Button>
    </form>
  </div>;
}
