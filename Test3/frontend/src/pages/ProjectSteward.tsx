import { useState } from "react";
import { Button, Input } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import StewardPlan from "./StewardPlan";
import { StewardExecution, StewardMemory, StewardRequirements } from "./StewardProgress";
import type { Artifacts, Experience, Gate, Run, RuntimeTask, Schedule } from "./stewardTypes";
import "../project-steward.css";

const EXAMPLE = "做一个帮同学在期末周找到有空位自习室的小程序。";
const SECTIONS = ["需求与方案", "任务排期", "执行与交付", "项目经验", "活动记录"] as const;
const STAGES: Record<string, string> = {
  "0": "需求分析", "1": "多角色讨论", "2": "方案比选", "3": "评审确认", "4": "需求规格", "5": "架构设计",
  "6": "任务分解", "7": "开发执行", "8": "验收", done: "已交付", stopped: "已停止",
};
const STATUS: Record<string, string> = { active: "进行中", waiting: "等待确认", running: "执行中", stopped: "已停止", done: "已交付", terminated: "已终止" };
const ACTIVITY: Record<string, string> = {
  "stage.started": "开始运行", "gate.created": "等待确认", "gate.resolved": "关卡已处理", "baseline.frozen": "冻结基线",
  "task.state_changed": "任务状态更新", "plan.edited": "已修改计划", "steward.proposals_ready": "候选方案校验结束",
  "steward.experience_saved": "更新项目经验", "steward.start_failed": "需求分析失败", "model.stage_started": "开始模型生成",
};
interface Project { id: string; name: string }
interface Activity { seq: number; kind: string; subject?: string; payload?: { kind?: string; from?: string; to?: string } }

function GateCard({ gate, run, candidate, busy, stale, view, perform }: {
  gate: Gate; run: Run; candidate: string; busy: boolean; stale: boolean; view: (tab: number) => void;
  perform: (action: () => Promise<unknown>) => void;
}) {
  const [note, setNote] = useState("");
  const isSupplement = gate.kind === "想法补充";
  const isComparison = gate.kind === "方案比选";
  const needsReason = gate.kind === "验收确认" && !gate.payload?.pass;
  const reason = note.trim();
  const commit = (decision: "approve" | "reject") => perform(() => api.resolveGate(
    gate.id, decision, {
      ...(isSupplement ? { text: reason } : { reason }), ...(isComparison ? { candidate } : {}),
    }, run.revision,
  ));
  const approval = isComparison ? (candidate === "fusion" ? "融合并评审" : "选定方案并评审") : isSupplement ? "提交补充" : gate.kind === "文档检查失败" ? "重试生成" : "确认并推进";
  return <section className="steward-gate" aria-label="当前确认点">
    <div className="steward-heading"><h3>{gate.kind}</h3><span>等待处理</span></div>
    {gate.payload?.missing?.map((item, i) => <p key={i}>{item}</p>)}
    {gate.payload?.errors?.map((item, i) => <p key={i}>{item}</p>)}
    {gate.kind === "评审确认" && gate.payload?.pass === false && <p>评审有阻断项，推进会按评审规则处理返工。</p>}
    {isComparison ? <Button onClick={() => view(0)}>查看候选方案</Button> : <label>
      {isSupplement ? "补充需求" : needsReason ? "验收说明（必填）" : "处理说明（可选）"}
      <Input.TextArea value={note} onChange={(event) => setNote(event.target.value)} disabled={busy || stale} rows={2} maxLength={4000} />
    </label>}
    <div className="steward-actions">
      <Button type="primary" disabled={busy || stale || (isComparison && !candidate) || ((isSupplement || needsReason) && !reason)} onClick={() => commit("approve")}>{approval}</Button>
      {!isSupplement && !(isComparison && run.provenance?.generation === "preset") &&
        <Button disabled={busy || stale} onClick={() => commit("reject")}>{isComparison ? "重新生成候选" : "退回"}</Button>}
    </div>
  </section>;
}

function RunPanel({ run, stale }: { run: Run; stale: boolean }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<number | null>(null);
  const [selection, setSelection] = useState({ gateId: "", id: "" });
  const gate = run.gates.find((item) => item.status === "pending");
  const candidate = gate && selection.gateId === gate.id ? selection.id : "";
  const view = tab ?? (run.stage === "6" ? 1 : ["7", "8", "done"].includes(run.stage) ? 2 : 0);
  const arts = useQuery<Artifacts>({ queryKey: ["arts", run.id], queryFn: () => api.artifacts(run.id), refetchInterval: 3000 });
  const tasks = useQuery<RuntimeTask[]>({ queryKey: ["tasks", run.id], queryFn: () => api.tasks(run.id), refetchInterval: 3000 });
  const preview = useQuery<Schedule | null>({ queryKey: ["steward-schedule", run.id, run.revision], queryFn: () => api.planPreview(run.id), enabled: Boolean(arts.data?.plan) && view === 1 });
  const memory = useQuery<Experience[]>({ queryKey: ["steward-memory", run.project_id], queryFn: () => api.experiences(run.project_id), enabled: view === 3 });
  const events = useQuery<Activity[]>({ queryKey: ["steward-events", run.id], queryFn: () => api.events(run.id), refetchInterval: 3000, enabled: view === 4 });
  const refresh = () => Promise.all([
    qc.invalidateQueries({ queryKey: ["run", run.id] }), qc.invalidateQueries({ queryKey: ["runs"] }),
    qc.invalidateQueries({ queryKey: ["arts", run.id] }), qc.invalidateQueries({ queryKey: ["tasks", run.id] }),
    qc.invalidateQueries({ queryKey: ["steward-schedule", run.id] }), qc.invalidateQueries({ queryKey: ["steward-memory", run.project_id] }),
    qc.invalidateQueries({ queryKey: ["steward-events", run.id] }),
  ]);
  const action = useMutation({ mutationFn: (operation: () => Promise<unknown>) => operation(), onSettled: refresh });
  const perform = (operation: () => Promise<unknown>) => {
    if (!action.isPending && !stale) action.mutate(operation);
  };
  const artifacts = arts.data ?? {};
  const busy = action.isPending || stale;
  const activeQuery = [arts, preview, tasks, memory, events][view];
  const terminal = ["terminated", "stopped", "done"].includes(run.status);
  return <div className="steward-grid">
    <aside className="steward-side glass-panel" aria-label="运行概况">
      <h2>运行概况</h2>
      <p className="steward-status"><span className={`dot ${run.status === "done" ? "completed" : gate || terminal ? "error" : "in_progress"}`} />
        <strong>{run.paused ? "已暂停" : STATUS[run.status] ?? run.status}</strong> · {STAGES[run.stage] ?? run.stage}</p>
      <p className="mono steward-wrap">{run.id.slice(0, 8)} · 修订 {run.revision}</p>
      {run.provenance?.generation_label && <p>{run.provenance.generation_label}<br />{run.provenance.execution_label}</p>}
      {artifacts.steward_error && <p className="steward-error" role="alert">{artifacts.steward_error}</p>}
      {gate && !terminal && <GateCard key={gate.id} gate={gate} run={run} candidate={candidate} busy={busy} stale={stale || arts.isError || run.paused} view={setTab} perform={perform} />}
      {action.isPending && <p role="status">正在处理，结果将自动刷新…</p>}
      {action.isError && <p className="steward-error" role="alert">{action.error.message}</p>}
      <div className="steward-actions">
        <Button onClick={() => void refresh()} disabled={action.isPending}>刷新状态</Button>
        <Link to={`${run.provenance?.mode === "deepseek" ? "/deepseek" : "/workstation"}/${run.id}`}>打开流程图</Link>
      </div>
    </aside>
    <section className="steward-content glass-panel" aria-label="项目产物">
      <nav className="steward-tabs" aria-label="主理人阶段">{SECTIONS.map((name, i) =>
        <button key={name} type="button" aria-pressed={view === i} onClick={() => setTab(i)}>{name}</button>)}</nav>
      <div className="steward-view">
        {activeQuery.isFetching && !activeQuery.data && <p role="status">正在加载…</p>}
        {activeQuery.isError && <p className="steward-error" role="alert">加载失败，请刷新后重试。</p>}
        {view === 0 && <StewardRequirements run={run} artifacts={artifacts} candidate={candidate} canChoose={gate?.kind === "方案比选"}
          busy={busy} setCandidate={(id) => setSelection({ id, gateId: gate?.id ?? "" })} />}
        {view === 1 && <StewardPlan run={run} cards={artifacts.plan?.tasks ?? []} tasks={tasks.data ?? []} schedule={preview.data}
          errors={artifacts.plan_errors} editable={!terminal && gate?.kind === "PLAN基线确认" && !artifacts.baseline_PLAN} disabled={busy} perform={perform} />}
        {view === 2 && <StewardExecution run={run} artifacts={artifacts} tasks={tasks.data ?? []} busy={busy} perform={perform} />}
        {view === 3 && <StewardMemory runId={run.id} items={memory.data ?? []} busy={busy} perform={perform} />}
        {view === 4 && (events.data?.length ? <ol className="steward-events">{[...events.data].reverse().map((event) =>
          <li key={event.seq}><span className="mono">#{event.seq}</span> <strong>{ACTIVITY[event.kind] ?? event.kind}</strong> {event.payload?.kind ?? event.subject}{event.payload?.to && ` · ${event.payload.to}`}</li>)}</ol> : <p className="muted">暂无活动记录。</p>)}
      </div>
    </section>
  </div>;
}

function RequirementForm({ project, initialIdea, projects }: { project?: Project; initialIdea?: string; projects: Project[] }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState(project?.id ?? "");
  const [name, setName] = useState("");
  const [idea, setIdea] = useState(initialIdea ?? "");
  const [provider, setProvider] = useState<"existing" | "deepseek">("existing");
  const tooLong = new TextEncoder().encode(idea.trim()).length > 24_000;
  const start = useMutation({
    mutationFn: async () => {
      const target = projectId || (await api.createProject(name.trim())).id;
      setProjectId(target);
      return api.createRun(target, idea.trim(), { steward: true, provider });
    },
    onSuccess: (result) => navigate(`/steward/${result.run.id}`),
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: ["runs"] }), qc.invalidateQueries({ queryKey: ["projects"] })]),
  });
  const blocked = start.isPending || (!projectId && !name.trim()) || !idea.trim() || tooLong;
  return <form className="steward-form steward-composer glass-panel" onSubmit={(event) => { event.preventDefault(); if (!blocked) start.mutate(); }}>
    <div className="steward-heading"><h2>{initialIdea ? "基于本轮需求开启新运行" : "提交项目需求"}</h2>
      <Button disabled={start.isPending} onClick={() => { setIdea(EXAMPLE); if (!name) setName("自习室空位查询"); }}>填入课堂示例</Button></div>
    <div className="steward-candidates">
      <label>项目<select disabled={start.isPending} value={projectId} onChange={(event) => setProjectId(event.target.value)}>
        <option value="">新建项目</option>
        {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        {projectId && !projects.some((item) => item.id === projectId) && <option value={projectId}>{project?.name ?? "当前项目"}</option>}
      </select></label>
      <label>模型来源<select disabled={start.isPending} value={provider} onChange={(event) => setProvider(event.target.value === "deepseek" ? "deepseek" : "existing")}>
        <option value="existing">使用后端配置</option><option value="deepseek">DeepSeek</option>
      </select></label>
    </div>
    {!projectId && <label>项目名称<Input value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} disabled={start.isPending} /></label>}
    <label>描述用户、问题和希望交付的结果<Input.TextArea rows={6} value={idea} onChange={(event) => setIdea(event.target.value)} required disabled={start.isPending} placeholder="例如，为同学提供按楼栋筛选的自习室空位列表。" /></label>
    {tooLong && <p className="steward-error" role="alert">需求最多 24,000 字节。</p>}
    {start.isError && <p className="steward-error" role="alert">{start.error.message}</p>}
    <div className="steward-actions">
      <Button type="primary" htmlType="submit" disabled={blocked} loading={start.isPending}>开始需求分析</Button>
      <span className="muted">课堂示例可离线演示。提交自己的需求时请选择已配置的真实模型。</span>
    </div>
  </form>;
}

export default function ProjectSteward() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [revisionSource, setRevisionSource] = useState<Run | null>(null);
  const runs = useQuery<Run[]>({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 3000 });
  const projects = useQuery<Project[]>({ queryKey: ["projects"], queryFn: api.projects });
  const run = useQuery<Run>({ queryKey: ["run", id], queryFn: () => api.run(id!), enabled: Boolean(id), refetchInterval: 2500 });
  const project = projects.data?.find((item) => item.id === run.data?.project_id);
  const changeRun = (value: string) => { setRevisionSource(null); navigate(value ? `/steward/${value}` : "/steward"); };
  return <div className="ws steward">
    <header className="topbar">
      <div className="topbar-left"><h1>项目主理人</h1>{project && <span className="steward-wrap">{project.name}</span>}</div>
      <div className="topbar-right">
        <label>运行历史 <select value={id ?? ""} onChange={(event) => changeRun(event.target.value)}>
          <option value="">新运行</option>
          {id && !runs.data?.some((item) => item.id === id) && <option value={id}>{id.slice(0, 8)}</option>}
          {[...(runs.data ?? [])].reverse().map((item) => <option key={item.id} value={item.id}>{item.idea?.slice(0, 28) || item.id.slice(0, 8)} · {item.id.slice(0, 8)}</option>)}
        </select></label>
        {run.data && <Button onClick={() => setRevisionSource(run.data)}>修改需求，开启新一轮</Button>}
      </div>
    </header>
    <div className="steward-page-body">
      {(!id || revisionSource?.id === id) && <RequirementForm key={revisionSource?.id ?? "new"} projects={projects.data ?? []}
        project={revisionSource && id ? (project ?? { id: revisionSource.project_id, name: "当前项目" }) : undefined}
        initialIdea={revisionSource?.idea} />}
      {revisionSource?.id === id && id && <Button onClick={() => setRevisionSource(null)}>收起新运行表单</Button>}
      {id && run.isPending && <p role="status">正在加载运行…</p>}
      {id && run.isError && <p className="steward-error" role="alert">运行读取失败。<Button onClick={() => void run.refetch()}>重试</Button></p>}
      {id && run.data && <RunPanel key={id} run={run.data} stale={run.isError} />}
      {(runs.isError || projects.isError) && <p className="steward-error" role="alert">历史或项目列表加载失败。<Button onClick={() => void Promise.all([runs.refetch(), projects.refetch()])}>重试</Button></p>}
    </div>
  </div>;
}
