from __future__ import annotations

import asyncio
import copy
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.runtime import RoleRegistry, call_agent, run_tool_agent
from app.change.classify import classify_cr, evaluation_pass
from app.discussion.engine import run_discussion
from app.docs.acceptance import acceptance_pass
from app.docs.checks import (
    check_design,
    check_proposal,
    check_spec,
    check_task_graph,
    review_pass,
    route_review,
)
from app.errors import AgentOutputError, CommandDenied, RevisionConflict, ValidationFailed
from app.ids import IdAllocator
from app.listening.cluster import cluster
from app.listening.distill import validate_distill
from app.listening.known import match_known
from app.listening.mask import hash_author, mask_text
from app.listening.route import route as route_feedback
from app.llm.gateway import Gateway
from app.orchestrator.budget import check_budget, tokens_budget
from app.orchestrator.classify import classify, failure_signature
from app.orchestrator.control import require_control
from app.orchestrator.replan import propose_replan
from app.orchestrator.scheduler import select_tasks
from app.orchestrator.states import next_task_state
from app.orchestrator.validator import judge_output
from app.schemas.common import IdeaCheck, IdeaDraft
from app.schemas.docs import (
    AcceptanceItem,
    AcceptanceReport,
    DesignDoc,
    IdeaCard,
    Issue,
    ProposalDoc,
    ReviewSheet,
    SpecDoc,
    TaskCard,
    TaskGraph,
)
from app.settings import load_limits, load_models, load_profile, load_roles
from app.stage.engine import StageEngine
from app.tools.sandbox import in_write_set, run_command
from app.tools.taskset import TaskToolset
from app.trace.service import TraceGraph
from app.workspace.gitops import changed_files, commit, create_worktree, dirty_files, init_repo_sync, merge, rollback_merge


@dataclass
class RunState:
    id: str
    project_id: str
    idea: str
    status: str = "active"
    revision: int = 1
    paused: bool = False
    pending_human: bool = False
    engine: StageEngine = field(default_factory=StageEngine)
    ids: IdAllocator = field(default_factory=IdAllocator)
    artifacts: dict[str, Any] = field(default_factory=dict)
    gates: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    crs: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    raw_feedback: list[dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    trace: TraceGraph = field(default_factory=TraceGraph)
    limits: dict[str, Any] = field(default_factory=dict)
    skip_continue: set[str] = field(default_factory=set)


class Workbench:
    def __init__(self, gateway: Gateway, registry: RoleRegistry, data_dir: Path) -> None:
        self.gateway = gateway
        self.registry = registry
        self.data_dir = data_dir
        self.projects: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, RunState] = {}
        self.limits = load_limits()
        self.models = load_models()
        self.roles = load_roles()
        self.profile = load_profile()
        self._token_mark = 0

    def emit(self, run: RunState, kind: str, subject: str = "", payload: dict[str, Any] | None = None, actor: str = "system") -> None:
        run.events.append(
            {
                "seq": len(run.events) + 1,
                "kind": kind,
                "subject": subject,
                "payload": payload or {},
                "actor": actor,
            }
        )

    def create_project(self, name: str, profile: str = "python-pytest") -> dict[str, Any]:
        pid = str(uuid.uuid4())
        self.projects[pid] = {"id": pid, "name": name, "profile": profile}
        return self.projects[pid]

    def create_run(self, project_id: str, idea: str) -> RunState:
        self._prepare_scripted()
        rid = str(uuid.uuid4())
        run = RunState(id=rid, project_id=project_id, idea=idea, limits=copy.deepcopy(self.limits))
        self.runs[rid] = run
        run.artifacts["idea_raw"] = idea
        self.emit(run, "stage.started", "0", {"idea": idea})
        return run

    def patch_limits(self, run: RunState, body: dict[str, Any], actor: str = "owner") -> dict[str, Any]:
        before = copy.deepcopy(run.limits)
        _deep_merge_limits(run.limits, body)
        self.emit(run, "system.limit_changed", "", {"before": before, "after": copy.deepcopy(run.limits)}, actor)
        return run.limits

    def _prepare_scripted(self) -> None:
        from app.llm.providers import ScriptedProvider
        from app.settings import get_settings

        provider = self.gateway.provider
        if not isinstance(provider, ScriptedProvider):
            return
        if get_settings().test3_scripted_fixture != "study-room":
            return
        if provider.queue:
            return
        from app.fixtures.study_room import scripted_m1_queue

        provider.queue = list(scripted_m1_queue())

    def _token_snapshot(self) -> int:
        return int(self.gateway.stats.get("tokens_in", 0)) + int(self.gateway.stats.get("tokens_out", 0))

    def _charge(self, run: RunState) -> None:
        used = self._token_snapshot()
        delta = used - self._token_mark
        self._token_mark = used
        if delta > 0:
            run.tokens_used += delta
        self._drain_gateway(run)
        self._emit_budget(run)

    def _charge_task(self, run: RunState, task: dict[str, Any], mark: int) -> None:
        used = self._token_snapshot()
        delta = max(0, used - mark)
        if delta:
            run.tokens_used += delta
            task["tokens_used"] = int(task.get("tokens_used") or 0) + delta
        self._drain_gateway(run)
        self._emit_budget(run, task)

    def _drain_gateway(self, run: RunState) -> None:
        while self.gateway.events:
            ev = self.gateway.events.pop(0)
            self.emit(run, ev.get("kind") or "llm.fallback", str(ev.get("slot") or ""), ev)

    def _emit_budget(self, run: RunState, task: dict[str, Any] | None = None) -> None:
        orch = run.limits.get("orchestrator") or {}
        info = check_budget(
            run.tokens_used,
            int(orch.get("run_token_budget") or 0),
            warn_ratio=float(orch.get("warn_ratio") or 0.8),
        )
        if info["warn"] and not run.artifacts.get("_budget_warned"):
            run.artifacts["_budget_warned"] = True
            self.emit(run, "budget.warn", "", info)
        if info["exceeded"]:
            run.paused = True
            self.emit(run, "budget.exceeded", "", info)
        if task is None:
            return
        card = TaskCard.model_validate(task["card"])
        limit = tokens_budget(int(card.points), int(orch.get("tokens_per_point") or 1_500_000))
        tinfo = check_budget(int(task.get("tokens_used") or 0), limit, warn_ratio=float(orch.get("warn_ratio") or 0.8))
        if tinfo["exceeded"]:
            task["state"] = "needs_human"
            task["last_error"] = "token_budget"
            self.emit(run, "budget.exceeded", task["code"], tinfo)

    def _judge_patterns(self) -> dict[str, list[str]]:
        return {
            "empty": list(self.profile.get("empty_test_patterns") or []),
            "skip": list(self.profile.get("skip_all_patterns") or []),
        }

    def _whitelist(self) -> list[str]:
        return list(self.profile.get("whitelist_prefixes") or ["pytest", "python -m pytest", "python -m", "ruff check"])

    async def start_idea(self, run: RunState) -> dict[str, Any]:
        card = IdeaCard(raw=run.idea)
        check = await call_agent("idea_checker", {"idea_card": card.model_dump()}, registry=self.registry, gateway=self.gateway)
        assert isinstance(check, IdeaCheck)
        card.user, card.problem, card.needs_payer, card.payer = check.user, check.problem, check.needs_payer, check.payer
        if check.missing and not check.ok:
            self._charge(run)
            return self._gate(run, "想法补充", {"missing": check.missing, "card": card.model_dump()})
        draft = await call_agent("pm_draft", {"idea_card": card.model_dump()}, registry=self.registry, gateway=self.gateway)
        assert isinstance(draft, IdeaDraft)
        card.approach = draft.approach
        card.features = draft.features
        run.artifacts["idea_card"] = card.model_dump()
        self._charge(run)
        return self._gate(run, "初步做法确认", {"card": card.model_dump()})

    async def resolve_gate(
        self,
        run: RunState,
        gate_id: str,
        decision: str,
        payload: dict[str, Any],
        actor: str = "owner",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        gate = next(g for g in run.gates if g["id"] == gate_id)
        if gate["status"] != "pending":
            raise ValidationFailed("关卡已裁决，不能重复推进")
        if expected_revision is not None and expected_revision != run.revision:
            raise RevisionConflict("revision mismatch")
        gate["status"] = "approved" if decision == "approve" else "rejected"
        gate["decision"] = payload
        run.pending_human = False
        run.revision += 1
        self.emit(run, "gate.resolved", gate_id, {"decision": decision, **payload}, actor)
        kind = gate["kind"]
        if kind == "想法补充":
            run.engine.supplements += 1
            extra = payload.get("text") or ""
            run.idea = run.idea + " " + extra
            return await self.start_idea(run)
        if kind == "初步做法确认":
            if decision != "approve":
                return await self.start_idea(run)
            run.engine.apply("idea_confirmed")
            return await self.run_discussion_step(run)
        if kind == "争议清单查看与裁决":
            self._apply_verdicts(run, payload.get("verdicts") or [])
            run.engine.apply("discussion_viewed")
            return await self.run_proposal(run)
        if kind == "评审确认":
            return await self.after_review_gate(run, decision, payload)
        if kind == "SPEC基线确认":
            self._freeze(run, "SPEC")
            run.engine.apply("spec_confirmed")
            return await self.run_design(run)
        if kind == "DESIGN基线确认":
            self._freeze(run, "DESIGN")
            run.engine.apply("design_confirmed")
            return await self.run_plan(run)
        if kind == "PLAN基线确认":
            self._freeze(run, "PLAN")
            run.engine.apply("plan_confirmed")
            self._materialize_tasks(run)
            return {"status": "executing", "stage": run.engine.current}
        if kind == "验收确认":
            return self._resolve_acceptance(run, decision, payload, gate)
        if kind == "重排提案":
            return await self._apply_replan(run, payload)
        if kind == "反馈分流确认":
            return {"status": "routed"}
        if kind == "变更决定":
            return await self.decide_cr(run, payload)
        return {"status": gate["status"]}

    def _resolve_acceptance(self, run: RunState, decision: str, payload: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
        passed = bool((gate.get("payload") or {}).get("pass"))
        reason = str(payload.get("reason") or "").strip()
        if decision != "approve":
            return {"status": "rejected", "pass": passed}
        if not passed and not reason:
            gate["status"] = "pending"
            run.pending_human = True
            raise ValidationFailed("验收未通过，人工确认必须写理由")
        run.engine.apply("acceptance_confirmed")
        self._freeze(run, "BUILD")
        run.status = "done"
        return {"status": "done", "pass": passed, "manual": (not passed), "reason": reason}

    async def run_discussion_step(
        self,
        run: RunState,
        *,
        reopen: bool = False,
        review_opinions: list[Any] | None = None,
        prev_issues: list[Issue] | None = None,
    ) -> dict[str, Any]:
        card = IdeaCard.model_validate(run.artifacts["idea_card"])
        result = await run_discussion(
            card,
            registry=self.registry,
            gateway=self.gateway,
            ids=run.ids,
            reopen=reopen,
            review_opinions=review_opinions,
            prev_issues=prev_issues,
            max_utterances=int((run.limits.get("discussion") or self.limits["discussion"])["max_utterances"]),
        )
        run.artifacts["questions"] = [q.model_dump() for q in result["questions"]]
        run.artifacts["merge_rows"] = [r.model_dump() for r in result["merge_rows"]]
        run.artifacts["utterances"] = [u.model_dump() for u in result["utterances"]]
        run.artifacts["issues"] = [i.model_dump() for i in result["issues"]]
        for u in result["utterances"]:
            self.emit(run, "discussion.message", str(u.seq), {"role": u.role, "rule": u.rule})
        if result["status_overrides"]:
            self.emit(run, "discussion.status_overridden", "", {"items": result["status_overrides"]})
        self._charge(run)
        return self._gate(run, "争议清单查看与裁决", {"issues": run.artifacts["issues"], "reopen": reopen})

    async def run_proposal(self, run: RunState) -> dict[str, Any]:
        issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
        idea = run.artifacts["idea_card"]
        doc = await call_agent(
            "proposal_writer",
            {"idea_card": idea, "issue_list": [i.model_dump() for i in issues]},
            registry=self.registry,
            gateway=self.gateway,
        )
        assert isinstance(doc, ProposalDoc)
        errors = check_proposal(doc, issues, capacity=int((run.limits.get("plan") or {})["capacity_points"]))
        run.artifacts["proposal"] = doc.model_dump()
        run.artifacts["proposal_errors"] = errors
        if errors:
            self._charge(run)
            return {"status": "failed", "errors": errors, "stage": "2"}
        run.engine.apply("proposal_checked")
        self._charge(run)
        return await self.run_review(run)

    async def run_review(self, run: RunState) -> dict[str, Any]:
        sheets: list[ReviewSheet] = []
        for role in ("review_user", "review_dev", "review_qa", "review_expert"):
            sheet = await call_agent(
                role,
                {"idea_card": run.artifacts["idea_card"], "proposal": run.artifacts["proposal"]},
                registry=self.registry,
                gateway=self.gateway,
            )
            assert isinstance(sheet, ReviewSheet)
            for op in sheet.opinions:
                if not op.code:
                    op.code = run.ids.next("R")
            sheets.append(sheet)
        run.artifacts["reviews"] = [s.model_dump() for s in sheets]
        run.artifacts["review_pass"] = review_pass(sheets)
        self._charge(run)
        return self._gate(run, "评审确认", {"pass": run.artifacts["review_pass"], "reviews": run.artifacts["reviews"]})

    async def after_review_gate(self, run: RunState, decision: str, payload: dict[str, Any]) -> dict[str, Any]:
        sheets = [ReviewSheet.model_validate(s) for s in run.artifacts["reviews"]]
        opinions = [op for s in sheets for op in s.opinions]
        passed = bool(run.artifacts["review_pass"])
        if decision == "override":
            passed = payload.get("pass", passed)
            self.emit(run, "review.overridden", "", {"reason": payload.get("reason", "")}, "owner")
        if passed and decision in {"approve", "override"}:
            run.engine.apply("review_confirmed")
            return await self.run_spec(run)
        route = payload.get("route") or route_review(opinions, returns=run.engine.returns, max_returns=int((run.limits.get("rework") or {})["max_returns"]))
        if route == "步骤1":
            run.engine.apply("review_to_discussion")
            if run.engine.current == "stopped":
                return {"status": "stopped", "reason": "退回超过 2 次"}
            prev = [Issue.model_validate(i) for i in run.artifacts["issues"]]
            disputed = [op for op in opinions if op.kind == "争议类"] or opinions
            return await self.run_discussion_step(run, reopen=True, review_opinions=disputed, prev_issues=prev)
        if route == "步骤2":
            run.engine.apply("review_to_proposal")
            if run.engine.current == "stopped":
                return {"status": "stopped", "reason": "退回超过 2 次"}
            return await self.run_proposal(run)
        if route == "我决定" and payload.get("accept_risk"):
            run.engine.apply("review_accept_risk")
            return await self.run_spec(run)
        run.engine.apply("review_stop")
        return {"status": "stopped", "reason": "只有验证类意见，先做真人验证"}

    async def run_spec(self, run: RunState) -> dict[str, Any]:
        issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
        spec = await call_agent(
            "spec_writer",
            {
                "idea_card": run.artifacts["idea_card"],
                "proposal": run.artifacts["proposal"],
                "issue_list": [i.model_dump() for i in issues],
                "review_sheet": run.artifacts["reviews"],
            },
            registry=self.registry,
            gateway=self.gateway,
        )
        assert isinstance(spec, SpecDoc)
        errors = check_spec(spec, issues, [ReviewSheet.model_validate(s) for s in run.artifacts["reviews"]])
        run.artifacts["spec"] = spec.model_dump()
        run.artifacts["spec_errors"] = errors
        if errors:
            self._charge(run)
            return {"status": "need_human", "errors": errors}
        for item in spec.features + spec.nonfunc:
            for src in item.sources:
                run.trace.link(src, item.code, "issue → spec_item")
        self._charge(run)
        return self._gate(run, "SPEC基线确认", {"spec": spec.model_dump()})

    async def run_design(self, run: RunState) -> dict[str, Any]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
        design = await call_agent("architect", {"spec": spec.model_dump()}, registry=self.registry, gateway=self.gateway)
        assert isinstance(design, DesignDoc)
        errors = check_design(design, spec, issues, max_modules=int((run.limits.get("design") or {})["max_modules"]))
        run.artifacts["design"] = design.model_dump()
        run.artifacts["design_errors"] = errors
        if errors:
            self._charge(run)
            return {"status": "failed", "errors": errors}
        for module in design.modules:
            for src in module.sources:
                run.trace.link(src, module.code, "spec_item → module")
        self._charge(run)
        return self._gate(run, "DESIGN基线确认", {"design": design.model_dump()})

    async def run_plan(self, run: RunState) -> dict[str, Any]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        design = DesignDoc.model_validate(run.artifacts["design"])
        graph = await call_agent(
            "decomposer",
            {"spec": spec.model_dump(), "design": design.model_dump()},
            registry=self.registry,
            gateway=self.gateway,
        )
        assert isinstance(graph, TaskGraph)
        errors = check_task_graph(graph, spec, design, int((run.limits.get("plan") or {})["capacity_points"]))
        run.artifacts["plan"] = graph.model_dump()
        run.artifacts["plan_errors"] = errors
        if errors:
            self._charge(run)
            return {"status": "failed", "errors": errors}
        self._charge(run)
        return self._gate(run, "PLAN基线确认", {"plan": graph.model_dump()})

    def _materialize_tasks(self, run: RunState) -> None:
        graph = TaskGraph.model_validate(run.artifacts["plan"])
        for task in graph.tasks:
            existing = run.tasks.get(task.code)
            if existing and existing["state"] == "done":
                continue
            run.tasks[task.code] = {
                "id": f"{run.id}:{task.code}",
                "code": task.code,
                "state": "pending",
                "revision": int((existing or {}).get("revision") or 1),
                "card": task.model_dump(),
                "repair_rounds": 0,
                "signatures": [],
                "evidence": [],
                "paused": False,
                "locked_by": "",
                "tokens_used": 0,
                "prev_output": "",
                "review_issues": [],
            }
            for src in task.sources:
                run.trace.link(src, task.code, "spec_item → task")
        self._refresh_ready(run)

    def _refresh_ready(self, run: RunState) -> None:
        states = {code: t["state"] for code, t in run.tasks.items()}
        for code, task in run.tasks.items():
            if task["state"] != "pending":
                continue
            deps = task["card"]["depends_on"]
            if all(states.get(d) == "done" or (states.get(d) == "skipped" and d in run.skip_continue) for d in deps):
                task["state"] = "ready"

    def _task_over_budget(self, run: RunState, task: dict[str, Any]) -> bool:
        card = TaskCard.model_validate(task["card"])
        limit = tokens_budget(int(card.points), int((run.limits.get("orchestrator") or {}).get("tokens_per_point") or 1_500_000))
        return int(task.get("tokens_used") or 0) >= limit

    async def schedule_once(self, run: RunState) -> list[str]:
        if run.paused:
            return []
        started: list[str] = []
        while not run.paused:
            graph = TaskGraph.model_validate(run.artifacts["plan"])
            states = {c: t["state"] for c, t in run.tasks.items()}
            running = [TaskCard.model_validate(t["card"]) for t in run.tasks.values() if t["state"] == "running"]
            picked = select_tasks(
                graph,
                states,
                run_paused=run.paused,
                paused={c for c, t in run.tasks.items() if t["paused"]},
                locked={c for c, t in run.tasks.items() if t["locked_by"]},
                running=running,
                concurrency=int((run.limits.get("orchestrator") or {})["concurrency"]),
                budget_exhausted={c for c, t in run.tasks.items() if self._task_over_budget(run, t)},
                skip_continue=run.skip_continue,
            )
            if not picked:
                break
            await asyncio.gather(*(self.execute_task(run, card.code) for card in picked))
            started.extend(card.code for card in picked)
            self._refresh_ready(run)
        return started

    async def execute_task(self, run: RunState, code: str) -> dict[str, Any]:
        task = run.tasks[code]
        card = TaskCard.model_validate(task["card"])
        task["revision"] = int(task.get("revision") or 1) + 1
        if task["state"] == "ready":
            task["state"] = next_task_state(task["state"], "scheduled")
        self.emit(run, "task.state_changed", code, {"code": code, "event": "scheduled", "to": task["state"], "rev": task["revision"]})
        if self._task_over_budget(run, task):
            task["state"] = "needs_human"
            task["last_error"] = "token_budget"
            self.emit(run, "budget.exceeded", code, {"used": task.get("tokens_used")})
            return {"state": task["state"], "kind": "预算耗尽"}
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        wt = self.data_dir / "runs" / run.id / "wt" / code
        if not wt.exists():
            create_worktree(repo, wt, f"task/{code}")
        visible: dict[str, Any] = {
            "task_card": card.model_dump(),
            "interfaces": task.get("interfaces") or [],
            "dependency_outputs": self._dep_outputs(run, card),
        }
        if task.get("prev_output") or task.get("review_issues") or int(task.get("repair_rounds") or 0) > 0:
            visible["prev_output"] = task.get("prev_output") or ""
            visible["review_issues"] = task.get("review_issues") or []
        tools = TaskToolset(
            wt,
            list(card.write_set),
            whitelist=self._whitelist(),
            timeout=int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600),
            env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
            truncate=int(self.profile.get("output_truncate") or 8000),
            on_denied=lambda _kind, rel: self.emit(run, "task.write_denied", code, {"path": rel}),
        )
        env_retries = 0
        max_env = int((run.limits.get("orchestrator") or {}).get("max_env_retries") or 3)
        result: Any = None
        while True:
            mark = self._token_snapshot()
            try:
                result = await run_tool_agent(
                    "coder" if card.role == "coder" else "tester",
                    visible,
                    tools,
                    registry=self.registry,
                    gateway=self.gateway,
                    max_steps=int(card.budget.max_tool_steps or (run.limits.get("orchestrator") or {}).get("max_tool_steps") or 30),
                )
                break
            except Exception as exc:  # noqa: BLE001
                self._charge_task(run, task, mark)
                fields = _exc_fields(exc)
                kind = classify(fields)
                if kind == "环境故障" and env_retries < max_env:
                    env_retries += 1
                    await asyncio.sleep(0.01 * (2**env_retries))
                    continue
                return await self._finish_failure(run, task, card, kind, str(exc), fields)
        self._charge_task(run, task, mark)
        if isinstance(result, dict) and result.get("done") is False:
            return await self._finish_failure(run, task, card, "代码缺陷", result.get("summary") or "max tool steps", {"exit_code": 1})

        if not card.acceptance:
            return await self._finish_failure(run, task, card, "任务描述问题", "验收命令为空", {"exit_code": 1})

        cmd_results: list[dict[str, Any]] = []
        denied = False
        timeout = False
        for check in card.acceptance:
            try:
                cmd_out = await run_command(
                    list(check.cmd),
                    cwd=wt,
                    whitelist=self._whitelist(),
                    timeout=int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600),
                    env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
                    truncate=int(self.profile.get("output_truncate") or 8000),
                )
            except CommandDenied as exc:
                denied = True
                cmd_results.append({"cmd": list(check.cmd), "denied": True, "exit_code": 1, "output": str(exc)})
                break
            cmd_results.append(cmd_out)
            if cmd_out.get("timeout"):
                timeout = True
        output = "\n".join(str(item.get("output") or "") for item in cmd_results)
        task["prev_output"] = output
        if denied:
            return await self._finish_failure(run, task, card, "任务描述问题", "验收命令被拒", {"exit_code": 1, "denied": True})
        if timeout:
            return await self._finish_failure(run, task, card, "环境故障", "验收超时", {"timeout": True, "exit_code": -1})

        exit_code = 0
        for item in cmd_results:
            code_i = int(item.get("exit_code") if item.get("exit_code") is not None else 1)
            if code_i != 0:
                exit_code = code_i
        judged = judge_output(exit_code, output, self._judge_patterns())

        pending = [rel for rel in dirty_files(wt) if not _ignore_write_noise(rel)]
        if not pending and not tools.written:
            return await self._finish_failure(run, task, card, "任务描述问题", "没有真实文件产出", {"exit_code": 1, "zero_tests": True})
        sha = commit(wt, f"{code} attempt")
        extras = []
        names = [rel for rel in (changed_files(wt, "HEAD~1") if pending else list(tools.written)) if not _ignore_write_noise(rel)]
        for rel in names:
            try:
                if not in_write_set((wt / rel).resolve() if (wt / rel).exists() else wt / rel, wt, list(card.write_set)):
                    extras.append(rel)
            except Exception:  # noqa: BLE001
                extras.append(rel)
        if extras:
            self.emit(run, "task.write_denied", code, {"paths": extras})
            return await self._finish_failure(run, task, card, "任务描述问题", f"写集外: {extras}", {"exit_code": 1})

        if task["state"] == "running":
            task["state"] = next_task_state(task["state"], "code_finished")
        review = await call_agent(
            "code_reviewer",
            {"task_card": card.model_dump(), "interfaces": [], "diff": "", "command_output": output},
            registry=self.registry,
            gateway=self.gateway,
        )
        self._charge(run)
        issues = list(getattr(review, "issues", []) or [])
        task["review_issues"] = [i.model_dump() if hasattr(i, "model_dump") else i for i in issues]
        blocking = any(getattr(i, "blocking", False) for i in issues)
        verdict = getattr(review, "verdict", "fail")
        if judged["passed"] and verdict == "pass" and not blocking:
            merged = merge(repo, f"task/{code}")
            if merged["ok"]:
                regression = await self._run_regression(run, repo)
                if not regression["ok"]:
                    rollback_merge(repo, str(merged["before"]))
                    return await self._finish_failure(run, task, card, "代码缺陷", regression["reason"], {"exit_code": 1})
                task["state"] = "done"
                task["evidence"].append({"kind": "command", "summary": output, "path": str(wt)})
                task["evidence"].append({"kind": "review", "summary": "pass", "path": ""})
                task["evidence"].append({"kind": "merge", "summary": sha, "path": ""})
                self.emit(run, "task.state_changed", code, {"code": code, "to": "done", "event": "accepted"})
                self._refresh_ready(run)
                return {"state": "done"}
            task["state"] = "needs_human"
            task["last_error"] = "合并冲突"
            self.emit(run, "task.state_changed", code, {"code": code, "to": "needs_human", "kind": "合并冲突"})
            return {"state": "needs_human", "kind": "合并冲突"}
        fields = {
            "exit_code": judged["exit_code"],
            "review_blocking": blocking,
            "zero_tests": judged["zero_tests"],
            "all_skipped": judged["all_skipped"],
            "same_signature": bool(task["signatures"] and task["signatures"][-1] == failure_signature(output)),
        }
        kind = classify(fields)
        return await self._finish_failure(run, task, card, kind, output, fields)

    async def _finish_failure(
        self,
        run: RunState,
        task: dict[str, Any],
        card: TaskCard,
        kind: str,
        output: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        sig = failure_signature(output or kind)
        if task["signatures"] and task["signatures"][-1] == sig:
            kind = "任务描述问题"
        task["signatures"].append(sig)
        task["prev_output"] = output
        if kind == "代码缺陷":
            task["repair_rounds"] = int(task.get("repair_rounds") or 0) + 1
            limit = int((run.limits.get("orchestrator") or {}).get("max_repair_rounds") or 6)
            if task["repair_rounds"] >= limit:
                task["state"] = "needs_human"
            else:
                if task["state"] == "verifying":
                    task["state"] = next_task_state(task["state"], "defect_repair")
                else:
                    task["state"] = "running"
                return await self.execute_task(run, card.code)
        elif kind == "任务描述问题":
            task["state"] = "needs_human"
            self.emit(run, "task.state_changed", card.code, {"code": card.code, "to": task["state"], "kind": kind})
            return self._gate(run, "重排提案", {"task": card.code, "kind": kind})
        elif kind == "环境故障":
            task["state"] = "failed"
        else:
            task["state"] = "needs_human"
        self.emit(run, "task.state_changed", card.code, {"code": card.code, "to": task["state"], "kind": kind})
        return {"state": task["state"], "kind": kind}

    def _dep_outputs(self, run: RunState, card: TaskCard) -> list[dict[str, Any]]:
        outs = []
        for dep in card.depends_on:
            other = run.tasks.get(dep)
            if other:
                outs.append({"code": dep, "state": other["state"], "evidence": other.get("evidence") or []})
        return outs

    async def _run_regression(self, run: RunState, repo: Path) -> dict[str, Any]:
        patterns = self._judge_patterns()
        timeout = int((run.limits.get("orchestrator") or {}).get("attempt_timeout_s") or 600)
        env_allow = list(self.profile.get("env_allowlist") or ["PATH"])
        whitelist = self._whitelist()
        commands: list[list[str]] = []
        for task in run.tasks.values():
            if task["state"] != "done":
                continue
            card = TaskCard.model_validate(task["card"])
            for check in card.acceptance:
                commands.append(list(check.cmd))
        test_cmd = self.profile.get("test_command")
        if test_cmd:
            commands.append(list(test_cmd))
        if not commands:
            return {"ok": True, "reason": ""}
        for cmd in commands:
            try:
                out = await run_command(cmd, cwd=repo, whitelist=whitelist, timeout=timeout, env_allow=env_allow)
            except CommandDenied as exc:
                return {"ok": False, "reason": str(exc)}
            code_i = 1 if out.get("exit_code") is None else int(out.get("exit_code"))
            judged = judge_output(code_i, str(out.get("output") or ""), patterns)
            if not judged["passed"]:
                return {"ok": False, "reason": out.get("output") or "regression failed"}
        return {"ok": True, "reason": ""}

    async def _apply_replan(self, run: RunState, payload: dict[str, Any]) -> dict[str, Any]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        design = DesignDoc.model_validate(run.artifacts["design"])
        graph = await call_agent(
            "decomposer",
            {"spec": spec.model_dump(), "design": design.model_dump(), "rewrite": payload},
            registry=self.registry,
            gateway=self.gateway,
        )
        assert isinstance(graph, TaskGraph)
        result = propose_replan(graph, spec, design, int((run.limits.get("plan") or {})["capacity_points"]))
        if not result["ok"]:
            return {"status": "replan_failed", "errors": result["errors"]}
        for task in run.tasks.values():
            if task["state"] not in {"done", "skipped"}:
                task["state"] = "cancelled"
        run.artifacts["plan"] = graph.model_dump()
        self._materialize_tasks(run)
        return {"status": "replanned", "tasks": list(run.tasks)}

    async def control_task(
        self,
        run: RunState,
        code: str,
        action: str,
        expected_revision: int,
        reason: str,
        actor: str = "owner",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = run.tasks[code]
        if task["revision"] != expected_revision:
            raise RevisionConflict("revision mismatch")
        require_control(action, task["state"], reason=reason)
        prev = task["state"]
        extra = payload or {}
        if action == "pause":
            task["paused"] = True
        elif action == "resume":
            task["paused"] = False
        elif action == "retry":
            event = "retry" if task["state"] == "failed" else "human_retry"
            task["state"] = next_task_state(task["state"], event)
            task["revision"] += 1
            run.revision += 1
            self.emit(run, f"control.{action}", code, {"from": prev, "to": task["state"], "reason": reason, "rev": task["revision"]}, actor)
            return await self.execute_task(run, code)
        elif action == "skip":
            task["state"] = "skipped"
            if extra.get("downstream", "continue") == "continue":
                run.skip_continue.add(code)
        elif action == "takeover":
            task["locked_by"] = actor
        elif action == "force-pass":
            repo = self.data_dir / "runs" / run.id / "repo"
            if repo.exists():
                regression = await self._run_regression(run, repo)
                if not regression["ok"]:
                    raise ValidationFailed("集成回归失败，不能强制通过")
            task["state"] = "done"
            task["evidence"].append({"kind": "manual", "summary": reason, "path": ""})
        elif action == "patch":
            raise ValidationFailed("patch 本轮未实现，见 Handoff")
        task["revision"] += 1
        run.revision += 1
        self.emit(run, f"control.{action}", code, {"from": prev, "to": task["state"], "reason": reason, "rev": task["revision"]}, actor)
        self._refresh_ready(run)
        return task

    def set_run_control(self, run: RunState, action: str, actor: str = "owner") -> RunState:
        if action == "pause":
            run.paused = True
        elif action == "resume":
            run.paused = False
        elif action == "terminate":
            run.status = "terminated"
            run.paused = True
        run.revision += 1
        self.emit(run, f"control.{action}", "", {"status": run.status, "paused": run.paused}, actor)
        return run

    def todos(self, run: RunState) -> list[dict[str, Any]]:
        items = [g for g in run.gates if g["status"] == "pending"]
        for task in run.tasks.values():
            if task["state"] == "needs_human":
                items.append({"kind": "needs_human", "task": task["code"]})
        if run.pending_human:
            items.append({"kind": "pending_human", "revision": run.revision})
        return items

    def budget(self, run: RunState) -> dict[str, Any]:
        orch = run.limits.get("orchestrator") or {}
        limit = int(orch.get("run_token_budget") or 0)
        info = check_budget(run.tokens_used, limit, warn_ratio=float(orch.get("warn_ratio") or 0.8))
        info["used"] = run.tokens_used
        info["limit"] = limit
        info["per_point"] = int(orch.get("tokens_per_point") or 1_500_000)
        return info

    async def accept(self, run: RunState) -> dict[str, Any]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        items: list[AcceptanceItem] = []
        for feat in list(spec.features) + list(spec.nonfunc):
            related = [t for t in run.tasks.values() if feat.code in t["card"]["sources"]]
            result = "未验证"
            evidence = ""
            reason = ""
            if related:
                ok, evidence, reason = await self._verify_spec_item(repo, related)
                result = "通过" if ok else "未通过"
            if any(feat.manual) and feat.priority == "P0" and result != "通过":
                reason = reason or "P0 人工项未填写理由"
            items.append(
                AcceptanceItem(
                    code=feat.code,
                    kind=feat.kind,
                    priority=feat.priority,
                    result=result,
                    evidence_path=evidence,
                    manual=any(feat.manual) if feat.manual else False,
                    tasks=[t["code"] for t in related],
                    reason=reason,
                )
            )
        report = AcceptanceReport(
            features=[i for i in items if i.kind == "功能"],
            nonfunc=[i for i in items if i.kind == "非功能"],
            matrix=run.trace.matrix(),
        )
        run.artifacts["acceptance"] = report.model_dump()
        passed = acceptance_pass(report, {"p1_pass_ratio": float((run.limits.get("acceptance") or {})["p1_pass_ratio"])})
        return self._gate(run, "验收确认", {"pass": passed, "report": report.model_dump()})

    async def _verify_spec_item(self, repo: Path, related: list[dict[str, Any]]) -> tuple[bool, str, str]:
        outputs: list[str] = []
        ok = True
        reason = ""
        evidence = str(repo)
        for task in related:
            card = TaskCard.model_validate(task["card"])
            if not card.acceptance:
                ok = False
                reason = "无验收命令"
                continue
            for check in card.acceptance:
                try:
                    out = await run_command(
                        list(check.cmd),
                        cwd=repo,
                        whitelist=self._whitelist(),
                        timeout=int(self.limits["orchestrator"]["attempt_timeout_s"]),
                        env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
                    )
                except CommandDenied as exc:
                    ok = False
                    reason = str(exc)
                    outputs.append(str(exc))
                    continue
                code_i = 1 if out.get("exit_code") is None else int(out.get("exit_code"))
                judged = judge_output(code_i, str(out.get("output") or ""), self._judge_patterns())
                outputs.append(str(out.get("output") or ""))
                evidence = str(repo / f"accept-{task['code']}.log")
                (repo / f"accept-{task['code']}.log").write_text(str(out.get("output") or ""), encoding="utf-8")
                if not judged["passed"]:
                    ok = False
                    reason = reason or (out.get("output") or "未通过")
        return ok, evidence, reason or ("\n".join(outputs)[:200] if not ok else "")

    async def submit_cr(self, run: RunState, description: str, impact_codes: list[str], **flags: Any) -> dict[str, Any]:
        open_crs = [c for c in run.crs if c.get("status") not in {"closed", "rejected", "applied"}]
        if len(open_crs) >= int((run.limits.get("change") or {}).get("max_open") or 3):
            run.artifacts.setdefault("cr_queue", []).append({"description": description, "codes": impact_codes, **flags})
            return {"queued": True, "queue_size": len(run.artifacts["cr_queue"])}
        impact = run.trace.impact(impact_codes)
        impact.update(flags)
        kind = str(flags.get("kind") or "")
        level = classify_cr(impact, kind)
        scores: list[int] = []
        any_red = bool(flags.get("red_line"))
        any_block = bool(flags.get("blocking"))
        for role in ("eval_value", "eval_impact", "eval_risk"):
            try:
                score = await call_agent(
                    role,
                    {"change_request": {"description": description, "kind": kind}, "impact": impact, "baseline": run.artifacts.get("spec")},
                    registry=self.registry,
                    gateway=self.gateway,
                )
                scores.append(int(getattr(score, "score", 0)))
                any_red = any_red or bool(getattr(score, "red_line", False))
                any_block = any_block or bool(getattr(score, "blocking", False))
            except Exception:  # noqa: BLE001
                break
        ok, ev_flags = evaluation_pass(scores, any_red_line=any_red, any_blocking=any_block)
        code = run.ids.next("CR")
        cr = {
            "code": code,
            "description": description,
            "impact": impact,
            "level": level,
            "kind": kind,
            "status": "analyzed",
            "eval_ok": ok,
            "eval_flags": ev_flags,
            "scores": scores,
        }
        run.crs.append(cr)
        self._charge(run)
        return self._gate(run, "变更决定", {"cr": cr})

    async def decide_cr(self, run: RunState, payload: dict[str, Any]) -> dict[str, Any]:
        cr = next(c for c in run.crs if c["code"] == payload.get("code"))
        cr["decision"] = payload.get("decision")
        cr["status"] = "decided"
        flags = cr.get("eval_flags") or {}
        if flags.get("red_line") or flags.get("blocking"):
            cr["eval_ok"] = False
        if cr["decision"] == "批准":
            for code in cr["impact"].get("downstream", []):
                if code not in run.tasks:
                    continue
                task = run.tasks[code]
                if task["state"] == "done":
                    task["state"] = next_task_state(task["state"], "change_impact")
                    self.emit(run, "task.state_changed", code, {"code": code, "to": "stale", "event": "change_impact"})
                    task["state"] = next_task_state(task["state"], "change_approved")
                    self.emit(run, "task.state_changed", code, {"code": code, "to": "ready", "event": "change_approved"})
                    task["revision"] += 1
                elif task["state"] == "running":
                    task["paused"] = True
                    self.emit(run, "task.state_changed", code, {"code": code, "to": task["state"], "event": "change_pause"})
            # incremental SPEC/DESIGN/PLAN 1.1 is not done this round
            cr["status"] = "approved"
        return cr

    async def import_feedback(self, run: RunState, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        imported = []
        for row in rows:
            masked = mask_text(row.get("text") or "")
            item = {
                "id": len(run.raw_feedback) + 1,
                "text": masked,
                "text_masked": masked,
                "author_hash": hash_author(row.get("author") or "anon", key),
                "source": row.get("source") or "manual",
            }
            run.raw_feedback.append(item)
            imported.append(item)
        try:
            vectors = await self.gateway.embed([r["text_masked"] for r in imported])
        except Exception:  # noqa: BLE001
            vectors = [[float(sum(ord(c) for c in r["text_masked"]) % 17), 1.0] for r in imported]
        groups = cluster(vectors, threshold=float((run.limits.get("listening") or {}).get("cluster_threshold") or 0.78))
        known_texts = []
        for issue in run.artifacts.get("issues") or []:
            if issue.get("destination") == "本版不做" or issue.get("status") in {"待定", "未讨论"}:
                known_texts.append(issue.get("text") or "")
                known_texts.append(issue.get("code") or "")
        keywords = list((run.limits.get("listening") or {}).get("known_keywords") or [])
        group_payload = []
        for members in groups:
            group_payload.append(
                {
                    "quotes": [imported[i]["id"] for i in members],
                    "texts": [imported[i]["text_masked"] for i in members],
                    "authors": list({imported[i]["author_hash"] for i in members}),
                }
            )
        distilled: list[dict[str, Any]] = []
        try:
            batch = await call_agent("distiller", {"feedback_group": group_payload}, registry=self.registry, gateway=self.gateway)
            distilled = list(getattr(batch, "items", None) or [])
        except Exception:  # noqa: BLE001
            distilled = []
        scores: dict[str, Any] = {}
        any_red = False
        if distilled:
            for role in ("fb_eval_value", "fb_eval_cost", "fb_eval_risk"):
                try:
                    score = await call_agent(
                        role,
                        {"feedback_group": distilled, "baseline": run.artifacts.get("spec")},
                        registry=self.registry,
                        gateway=self.gateway,
                    )
                    scores[getattr(score, "dimension", role)] = int(getattr(score, "score", 0))
                    any_red = any_red or bool(getattr(score, "red_line", False))
                except Exception:  # noqa: BLE001
                    break
        raw_by_id = {row["id"]: row["text_masked"] for row in imported}
        for idx, members in enumerate(groups):
            texts = [imported[i]["text_masked"] for i in members]
            authors = {imported[i]["author_hash"] for i in members}
            agent_item = distilled[idx] if idx < len(distilled) else {}
            item = {
                "code": run.ids.next("FB"),
                "category": agent_item.get("category") or "",
                "summary": agent_item.get("summary") or "",
                "quotes": agent_item.get("quotes") or [imported[i]["id"] for i in members],
                "count": agent_item.get("count") if agent_item.get("count") is not None else len(members),
                "basis": agent_item.get("basis") or "归纳",
                "unique_authors": len(authors),
                "red_line": bool(agent_item.get("red_line") or any_red),
                "known": False,
                "new_direction": bool(agent_item.get("new_direction")),
                "linked_issue": agent_item.get("linked_issue") or "",
            }
            known = match_known(item["summary"] or " ".join(texts), known_texts, keywords=keywords)
            item["known"] = bool(known)
            if known and not item["linked_issue"] and known in {i.get("code") for i in (run.artifacts.get("issues") or [])}:
                item["linked_issue"] = known
            item["distill_errors"] = validate_distill(item, raw_by_id)
            item["route"] = route_feedback(item, scores)
            run.feedback.append(item)
        self._charge(run)
        return imported

    def _gate(self, run: RunState, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        gate = {"id": str(uuid.uuid4()), "kind": kind, "status": "pending", "payload": payload}
        run.gates.append(gate)
        run.status = "waiting"
        run.pending_human = True
        self.emit(run, "gate.created", gate["id"], {"kind": kind})
        return {"status": "need_human", "gate": gate, "stage": run.engine.current, "state": "needs_human"}

    def _apply_verdicts(self, run: RunState, verdicts: list[dict[str, Any]]) -> None:
        issues = [Issue.model_validate(i) for i in run.artifacts["issues"]]
        by_code = {i.code: i for i in issues}
        for item in verdicts:
            issue = by_code.get(item["code"])
            if not issue:
                continue
            issue.status = item["status"]
            issue.basis = "人工裁决"
            issue.conclusion = item.get("reason") or issue.conclusion
            if item.get("assumption_unverified"):
                issue.basis = "待真人验证"
        run.artifacts["issues"] = [i.model_dump() for i in issues]

    def _freeze(self, run: RunState, kind: str) -> None:
        run.artifacts[f"baseline_{kind}"] = "1.0"
        self.emit(run, "baseline.frozen", kind, {"version": "1.0"})


def _deep_merge_limits(dst: dict[str, Any], src: dict[str, Any]) -> None:
    if not isinstance(src, dict):
        raise ValidationFailed("limits patch 必须是对象")
    for key, value in src.items():
        if key not in dst:
            raise ValidationFailed(f"未知限制项: {key}")
        if isinstance(dst[key], dict):
            if not isinstance(value, dict):
                raise ValidationFailed(f"{key} 必须是对象")
            _deep_merge_limits(dst[key], value)
        else:
            dst[key] = value


def _ignore_write_noise(rel: str) -> bool:
    parts = Path(rel).parts
    return any(part in {"__pycache__", ".pytest_cache", ".git"} or part.endswith(".pyc") for part in parts)


def _exc_fields(exc: Exception) -> dict[str, Any]:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    name = exc.__class__.__name__.lower()
    return {
        "http_status": status,
        "timeout": "timeout" in name or "timeout" in str(exc).lower(),
        "parse_error": isinstance(exc, AgentOutputError) or "parse" in name,
        "env_error": True,
    }
