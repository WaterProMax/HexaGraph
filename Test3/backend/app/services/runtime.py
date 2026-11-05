from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.runtime import RoleRegistry, call_agent
from app.change.classify import classify_cr
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
from app.errors import RevisionConflict
from app.ids import IdAllocator
from app.listening.cluster import cluster
from app.listening.distill import validate_distill
from app.listening.mask import hash_author, mask_text
from app.listening.route import route as route_feedback
from app.llm.gateway import Gateway
from app.orchestrator.budget import check_budget
from app.orchestrator.classify import classify, failure_signature
from app.orchestrator.control import require_control
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
from app.tools.sandbox import in_write_set, normalize_under, run_command
from app.trace.service import TraceGraph
from app.workspace.gitops import commit, create_worktree, init_repo_sync, merge


@dataclass
class RunState:
    id: str
    project_id: str
    idea: str
    status: str = "active"
    revision: int = 1
    paused: bool = False
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
        run = RunState(id=rid, project_id=project_id, idea=idea, limits=self.limits)
        self.runs[rid] = run
        run.artifacts["idea_raw"] = idea
        self.emit(run, "stage.started", "0", {"idea": idea})
        return run

    def _prepare_scripted(self) -> None:
        from app.llm.providers import ScriptedProvider
        from app.settings import get_settings

        provider = self.gateway.provider
        if not isinstance(provider, ScriptedProvider):
            return
        if get_settings().test3_scripted_fixture != "study-room":
            return
        from app.fixtures.study_room import scripted_m1_queue

        provider.queue = list(scripted_m1_queue())

    def _charge(self, run: RunState) -> None:
        used = int(self.gateway.stats.get("tokens_in", 0)) + int(self.gateway.stats.get("tokens_out", 0))
        delta = used - self._token_mark
        self._token_mark = used
        if delta > 0:
            run.tokens_used += delta

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

    async def resolve_gate(self, run: RunState, gate_id: str, decision: str, payload: dict[str, Any], actor: str = "owner") -> dict[str, Any]:
        gate = next(g for g in run.gates if g["id"] == gate_id)
        gate["status"] = "approved" if decision == "approve" else "rejected"
        gate["decision"] = payload
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
            run.engine.apply("acceptance_confirmed")
            self._freeze(run, "BUILD")
            run.status = "done"
            return {"status": "done"}
        if kind == "重排提案":
            return {"status": "replanned"}
        if kind == "反馈分流确认":
            return {"status": "routed"}
        if kind == "变更决定":
            return await self.decide_cr(run, payload)
        return {"status": gate["status"]}

    async def run_discussion_step(self, run: RunState) -> dict[str, Any]:
        card = IdeaCard.model_validate(run.artifacts["idea_card"])
        result = await run_discussion(
            card,
            registry=self.registry,
            gateway=self.gateway,
            ids=run.ids,
            max_utterances=int(self.limits["discussion"]["max_utterances"]),
        )
        run.artifacts["questions"] = [q.model_dump() for q in result["questions"]]
        run.artifacts["merge_rows"] = [r.model_dump() for r in result["merge_rows"]]
        run.artifacts["utterances"] = [u.model_dump() for u in result["utterances"]]
        run.artifacts["issues"] = [i.model_dump() for i in result["issues"]]
        for u in result["utterances"]:
            self.emit(run, "discussion.message", str(u.seq), {"role": u.role, "rule": ""})
        if result["status_overrides"]:
            self.emit(run, "discussion.status_overridden", "", {"items": result["status_overrides"]})
        self._charge(run)
        return self._gate(run, "争议清单查看与裁决", {"issues": run.artifacts["issues"]})

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
        errors = check_proposal(doc, issues, capacity=int(self.limits["plan"]["capacity_points"]))
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
        route = payload.get("route") or route_review(opinions, returns=run.engine.returns, max_returns=int(self.limits["rework"]["max_returns"]))
        if route == "步骤1":
            run.engine.apply("review_to_discussion")
            if run.engine.current == "stopped":
                return {"status": "stopped", "reason": "退回超过 2 次"}
            return await self.run_discussion_step(run)
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
        errors = check_design(design, spec, issues, max_modules=int(self.limits["design"]["max_modules"]))
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
        errors = check_task_graph(graph, spec, design, int(self.limits["plan"]["capacity_points"]))
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
            run.tasks[task.code] = {
                "id": f"{run.id}:{task.code}",
                "code": task.code,
                "state": "pending",
                "revision": 1,
                "card": task.model_dump(),
                "repair_rounds": 0,
                "signatures": [],
                "evidence": [],
                "paused": False,
                "locked_by": "",
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
            if all(states.get(d) in {"done", "skipped"} for d in deps):
                task["state"] = "ready"

    async def schedule_once(self, run: RunState) -> list[str]:
        if run.paused:
            return []
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
            concurrency=int(self.limits["orchestrator"]["concurrency"]),
        )
        started = []
        for card in picked:
            await self.execute_task(run, card.code)
            started.append(card.code)
        return started

    async def execute_task(self, run: RunState, code: str) -> dict[str, Any]:
        task = run.tasks[code]
        card = TaskCard.model_validate(task["card"])
        task["state"] = next_task_state(task["state"], "scheduled") if task["state"] == "ready" else task["state"]
        self.emit(run, "task.state_changed", code, {"code": code, "event": "scheduled", "to": task["state"]})
        repo = self.data_dir / "runs" / run.id / "repo"
        if not (repo / ".git").exists():
            init_repo_sync(repo, self.profile.get("initial_files"))
        wt = self.data_dir / "runs" / run.id / "wt" / code
        if not wt.exists():
            create_worktree(repo, wt, f"task/{code}")
        # scripted coder may write files via parsed output
        result = await call_agent(
            "coder" if card.role == "coder" else "tester",
            {"task_card": card.model_dump(), "interfaces": [], "dependency_outputs": []},
            registry=self.registry,
            gateway=self.gateway,
        )
        files = getattr(result, "files", None) or (result.get("files") if isinstance(result, dict) else [])
        denied = False
        for rel in files:
            try:
                path = normalize_under(wt, rel)
                if not in_write_set(path, wt, card.write_set):
                    denied = True
                    self.emit(run, "task.write_denied", code, {"path": rel})
                    continue
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("# generated\n", encoding="utf-8")
            except Exception:  # noqa: BLE001
                denied = True
        sha = commit(wt, f"{code} attempt")
        task["state"] = next_task_state(task["state"], "code_finished") if task["state"] == "running" else task["state"]
        cmd_out: dict[str, Any] | None = None
        if card.acceptance and not denied:
            try:
                cmd_out = await run_command(
                    list(card.acceptance[0].cmd),
                    cwd=wt,
                    whitelist=list(self.profile.get("whitelist_prefixes") or ["pytest", "python"]),
                    timeout=int(self.limits["orchestrator"]["attempt_timeout_s"]),
                    env_allow=list(self.profile.get("env_allowlist") or ["PATH"]),
                    truncate=int(self.profile.get("output_truncate") or 8000),
                )
            except Exception:  # noqa: BLE001
                cmd_out = None
        fake_output = (cmd_out or {}).get("output") or getattr(result, "summary", "") or "1 passed"
        exit_code = (cmd_out or {}).get("exit_code", 1 if denied else 0)
        judged = judge_output(exit_code, fake_output, None if denied else {"empty": [], "skip": []})
        if denied:
            judged = {"passed": False, "zero_tests": False, "all_skipped": False, "exit_code": 1}
        self._charge(run)
        review = await call_agent(
            "code_reviewer",
            {"task_card": card.model_dump(), "interfaces": [], "diff": "", "command_output": fake_output},
            registry=self.registry,
            gateway=self.gateway,
        )
        blocking = any(i.blocking for i in getattr(review, "issues", []))
        verdict = getattr(review, "verdict", "fail")
        if judged["passed"] and verdict == "pass" and not blocking:
            merged = merge(repo, f"task/{code}")
            if merged["ok"]:
                task["state"] = "done"
                task["evidence"].append({"kind": "command", "summary": fake_output, "path": str(wt)})
                task["evidence"].append({"kind": "review", "summary": "pass", "path": ""})
                task["evidence"].append({"kind": "merge", "summary": sha, "path": ""})
                self.emit(run, "task.state_changed", code, {"code": code, "to": "done", "event": "accepted"})
                self._refresh_ready(run)
                return {"state": "done"}
            task["state"] = "failed"
            return {"state": "failed", "kind": "合并冲突"}
        kind = classify(
            {
                "exit_code": judged["exit_code"],
                "review_blocking": blocking,
                "zero_tests": judged["zero_tests"],
                "all_skipped": judged["all_skipped"],
                "same_signature": False,
            }
        )
        sig = failure_signature(fake_output)
        if task["signatures"] and task["signatures"][-1] == sig:
            kind = "任务描述问题"
        task["signatures"].append(sig)
        if kind == "代码缺陷":
            task["repair_rounds"] += 1
            limit = int(self.limits["orchestrator"]["max_repair_rounds"])
            if task["repair_rounds"] >= limit:
                task["state"] = "needs_human"
            else:
                task["state"] = "running"
                return await self.execute_task(run, code)
        elif kind == "任务描述问题":
            return self._gate(run, "重排提案", {"task": code})
        else:
            task["state"] = "needs_human"
        self.emit(run, "task.state_changed", code, {"code": code, "to": task["state"], "kind": kind})
        return {"state": task["state"], "kind": kind}

    def control_task(self, run: RunState, code: str, action: str, expected_revision: int, reason: str, actor: str = "owner") -> dict[str, Any]:
        task = run.tasks[code]
        if task["revision"] != expected_revision:
            raise RevisionConflict("revision mismatch")
        require_control(action, task["state"], reason=reason)
        prev = task["state"]
        if action == "pause":
            task["paused"] = True
        elif action == "resume":
            task["paused"] = False
        elif action == "retry":
            task["state"] = "running"
        elif action == "skip":
            task["state"] = "skipped"
        elif action == "takeover":
            task["locked_by"] = actor
        elif action == "force-pass":
            task["state"] = "done"
            task["evidence"].append({"kind": "manual", "summary": reason, "path": ""})
        elif action == "patch":
            pass
        task["revision"] += 1
        run.revision += 1
        self.emit(run, f"control.{action}", code, {"from": prev, "to": task["state"], "reason": reason, "rev": task["revision"]}, actor)
        self._refresh_ready(run)
        return task

    def todos(self, run: RunState) -> list[dict[str, Any]]:
        items = [g for g in run.gates if g["status"] == "pending"]
        for task in run.tasks.values():
            if task["state"] == "needs_human":
                items.append({"kind": "needs_human", "task": task["code"]})
        return items

    def budget(self, run: RunState) -> dict[str, Any]:
        limit = int(self.limits["orchestrator"]["run_token_budget"])
        info = check_budget(run.tokens_used, limit, warn_ratio=float(self.limits["orchestrator"]["warn_ratio"]))
        info["used"] = run.tokens_used
        info["limit"] = limit
        info["per_point"] = int(self.limits["orchestrator"]["tokens_per_point"])
        return info

    async def accept(self, run: RunState) -> dict[str, Any]:
        spec = SpecDoc.model_validate(run.artifacts["spec"])
        items = []
        for feat in spec.features:
            evidence = ""
            related = [t for t in run.tasks.values() if feat.code in t["card"]["sources"] and t["state"] == "done"]
            if related and related[0]["evidence"]:
                evidence = related[0]["evidence"][0].get("path") or "task"
                result = "通过"
            else:
                result = "未验证"
            items.append(
                AcceptanceItem(
                    code=feat.code,
                    kind="功能",
                    priority=feat.priority,
                    result=result,
                    evidence_path=evidence,
                    manual=any(feat.manual) if feat.manual else False,
                    tasks=[t["code"] for t in related],
                )
            )
        report = AcceptanceReport(features=items, matrix=run.trace.matrix())
        run.artifacts["acceptance"] = report.model_dump()
        passed = acceptance_pass(report, {"p1_pass_ratio": float(self.limits["acceptance"]["p1_pass_ratio"])})
        return self._gate(run, "验收确认", {"pass": passed, "report": report.model_dump()})

    async def submit_cr(self, run: RunState, description: str, impact_codes: list[str], **flags: Any) -> dict[str, Any]:
        open_crs = [c for c in run.crs if c.get("status") not in {"closed", "rejected"}]
        if len(open_crs) >= int(self.limits["change"]["max_open"]):
            return {"queued": True}
        impact = run.trace.impact(impact_codes)
        impact.update(flags)
        level = classify_cr(impact, flags.get("kind", ""))
        code = run.ids.next("CR")
        cr = {"code": code, "description": description, "impact": impact, "level": level, "status": "analyzed"}
        run.crs.append(cr)
        return self._gate(run, "变更决定", {"cr": cr})

    async def decide_cr(self, run: RunState, payload: dict[str, Any]) -> dict[str, Any]:
        cr = next(c for c in run.crs if c["code"] == payload.get("code"))
        cr["decision"] = payload.get("decision")
        cr["status"] = "decided"
        if cr["decision"] == "批准":
            for code in cr["impact"].get("downstream", []):
                if code in run.tasks and run.tasks[code]["state"] == "done":
                    run.tasks[code]["state"] = "stale"
            cr["status"] = "applied"
        return cr

    def import_feedback(self, run: RunState, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
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
        vectors = [[float(sum(ord(c) for c in r["text_masked"]) % 17), 1.0] for r in imported]
        groups = cluster(vectors, threshold=float(self.limits["listening"]["cluster_threshold"]))
        known_texts = []
        for issue in run.artifacts.get("issues") or []:
            if issue.get("destination") == "本版不做" or issue.get("status") in {"待定", "未讨论"}:
                known_texts.append(issue.get("text") or "")
                known_texts.append(issue.get("code") or "")
        from app.listening.known import match_known

        unique_authors: dict[str, set[str]] = {}
        for g_i, members in enumerate(groups):
            texts = [imported[i]["text_masked"] for i in members]
            authors = {imported[i]["author_hash"] for i in members}
            blob = " ".join(texts)
            summary = texts[0][:80]
            known = match_known(blob, known_texts, keywords=["别的楼", "灰色", "学号"])
            item = {
                "code": run.ids.next("FB"),
                "category": "噪声" if "哈哈" in blob or "测试一下" in blob else ("缺陷" if "学号" in blob else ("新需求" if "预测" in blob else "体验问题")),
                "summary": summary,
                "quotes": [imported[i]["id"] for i in members],
                "count": len(authors),
                "unique_authors": len(authors),
                "red_line": "学号" in blob or "隐私" in blob,
                "known": bool(known),
                "new_direction": "校区" in blob,
            }
            errors = validate_distill(item, {imported[i]["id"]: imported[i]["text_masked"] for i in members})
            item["distill_errors"] = errors
            item["route"] = route_feedback(item, {"价值": 3})
            run.feedback.append(item)
            unique_authors[item["code"]] = authors
        return imported

    def _gate(self, run: RunState, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        gate = {"id": str(uuid.uuid4()), "kind": kind, "status": "pending", "payload": payload}
        run.gates.append(gate)
        run.status = "waiting"
        self.emit(run, "gate.created", gate["id"], {"kind": kind})
        return {"status": "need_human", "gate": gate, "stage": run.engine.current}

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
