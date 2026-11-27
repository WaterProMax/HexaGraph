"""Bridge a human-approved discussion to the existing planning gate."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from pydantic import BaseModel, Field, ValidationError

from app.discussion.driver import _call, _extract_json, _load_bot_context, _system_for
from app.discussion.models import DiscussionSession
from app.docs.checks import check_design, check_spec, check_task_graph, check_work_packages
from app.errors import ValidationFailed
from app.llm.providers import ScriptedProvider
from app.schemas.docs import DesignDoc, SpecDoc, TaskCard, TaskGraph, WorkPackage


logger = logging.getLogger(__name__)


class LeaderSpec(BaseModel):
    spec: SpecDoc


class LeaderOutline(BaseModel):
    spec: SpecDoc
    design: DesignDoc
    work_packages: list[WorkPackage]


class TaskBatch(BaseModel):
    tasks: list[TaskCard]


class PackageTaskBatch(BaseModel):
    tasks: list[TaskCard]
    depends_on_packages: list[str] = Field(default_factory=list)


class LeaderPlan(BaseModel):
    spec: SpecDoc
    design: DesignDoc
    plan: TaskGraph


def _schema_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in issue['loc']) or '任务计划'}（{issue['type']}）"
        for issue in exc.errors(include_input=False, include_context=False, include_url=False)[:5]
    ]




def _is_scripted(bench) -> bool:
    return isinstance(getattr(getattr(bench, "gateway", None), "provider", None), ScriptedProvider)


def _prepare_package_tasks(
    package: WorkPackage,
    batch: PackageTaskBatch,
    target: int,
    spec: SpecDoc,
    design: DesignDoc,
    allowed_packages: set[str],
) -> tuple[list[str], list[TaskCard]]:
    tasks = list(batch.tasks)
    errors: list[str] = []
    if len(tasks) < target:
        errors.append(f"当前 {len(tasks)} 个任务，至少需要 {target} 个")
    codes = [task.code for task in tasks]
    if len(set(codes)) != len(codes):
        errors.append("本地任务编号重复")
    modules = {module.code for module in design.modules}
    local = set(codes)
    for task in tasks:
        if not task.acceptance:
            errors.append(f"{task.code} 缺少验收命令")
        if task.module not in modules or not task.sources:
            errors.append(f"{task.code} 的所属模块无效或缺少来源")
        if len(task.write_set) > 8:
            errors.append(f"{task.code} 写集文件超过 8")
        if task.code in task.depends_on:
            errors.append(f"{task.code} 存在自依赖")
        for dep in task.depends_on:
            if dep not in local:
                errors.append(f"{task.code} 依赖了本包不存在的任务 {dep}")
    for dep in batch.depends_on_packages:
        if dep not in allowed_packages:
            errors.append(f"{package.code} 引用了不存在或自身的工作包 {dep}")
    if errors:
        return errors, tasks
    mapping = {task.code: f"{package.code}-{index + 1:02d}" for index, task in enumerate(tasks)}
    for task in tasks:
        task.code = mapping[task.code]
        task.parent = package.code
        task.points = 1
        task.depends_on = [mapping[dep] for dep in task.depends_on]
    known_sources = (
        {item.code for item in spec.features + spec.nonfunc}
        | {module.code for module in design.modules}
        | {item.code for item in design.interfaces}
        | {str(item.get("code")) for item in design.decisions if item.get("code")}
        | set(package.sources)
    )
    interface_codes = {item.code for item in design.interfaces}
    outputs_by_code = {task.code: set(task.outputs) for task in tasks}
    fallback_sources = list(package.sources) or [package.module]
    for task in tasks:
        task.sources = [source for source in task.sources if source in known_sources] or fallback_sources
        allowed_inputs = set(interface_codes)
        for dep in task.depends_on:
            allowed_inputs.update(outputs_by_code.get(dep, set()))
        task.inputs = [ref for ref in task.inputs if ref in allowed_inputs]
    return [], tasks




def _write_sets_overlap(left: list[str], right: list[str]) -> bool:
    for a in left:
        for b in right:
            if a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/"):
                return True
    return False


def _serialize_write_conflicts(tasks: list[TaskCard], package_order: list[str]) -> None:
    """Order same-file writes instead of rejecting an otherwise usable fine plan."""
    rank = {code: index for index, code in enumerate(package_order)}
    ordered = sorted(tasks, key=lambda task: (rank.get(task.parent, len(rank)), task.code))
    by_code = {task.code: task for task in ordered}

    def reaches(start: str, target: str) -> bool:
        seen: set[str] = set()
        stack = list(by_code[start].depends_on)
        while stack:
            code = stack.pop()
            if code == target:
                return True
            if code in seen or code not in by_code:
                continue
            seen.add(code)
            stack.extend(by_code[code].depends_on)
        return False

    for index, earlier in enumerate(ordered):
        for later in ordered[index + 1:]:
            if not _write_sets_overlap(earlier.write_set, later.write_set):
                continue
            if reaches(earlier.code, later.code) or reaches(later.code, earlier.code):
                continue
            later.depends_on = sorted(set(later.depends_on) | {earlier.code})


def _expand_package_dependencies(package_deps: dict[str, list[str]], tasks: list[TaskCard]) -> None:
    children: dict[str, list[TaskCard]] = {}
    for task in tasks:
        children.setdefault(task.parent, []).append(task)
    sinks: dict[str, list[str]] = {}
    for code, items in children.items():
        used = {dep for task in items for dep in task.depends_on}
        sinks[code] = [task.code for task in items if task.code not in used]
    for code, deps in package_deps.items():
        roots = [task for task in children.get(code, []) if not task.depends_on]
        extra = {sink for dep in deps for sink in sinks.get(dep, [])}
        if not extra:
            continue
        for root in roots:
            root.depends_on = sorted(set(root.depends_on) | extra)


def run_id_for(session_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hexagraph:discussion:{session_id}"))


async def generate(bench, record: DiscussionSession, *, spec=None, design=None, rewrite=None, work_packages=None):
    package = record.decision_package
    if record.status != "approved" or package is None:
        raise ValidationFailed("需先确认需求规格")
    initial = spec is None
    capacity = int(bench.limits["plan"]["capacity_points"])
    bot, memory, files = await _load_bot_context(bench, record, record.leader_bot_id)
    outline_instructions = _system_for(bot, memory, files, "leader_planning.md")
    task_instructions = _system_for(bot, memory, files, "leader_tasks.md")

    if initial or not work_packages:
        material = {
            "approved_specification": package.body_md,
            "capacity_points": capacity,
            "schema": LeaderOutline.model_json_schema(),
        }
        if not initial:
            material.update(
                spec=spec.model_dump(),
                design=design.model_dump(),
                note="已有批准的 SPEC/DESIGN；请保持它们不变，只生成 work_packages。",
            )
        errors: list[str] = []
        for _ in range(2):
            result = await _call(
                bench,
                record.session_id,
                bot,
                [
                    {"role": "system", "content": outline_instructions},
                    {"role": "user", "content": json.dumps(
                        {**material, "validation_feedback": errors}, ensure_ascii=False
                    )},
                ],
                operation="plan",
                json_mode=True,
                track_discussion_usage=False,
                timeout=900.0,
                checkpoint=False,
            )
            try:
                parsed = result.parsed if isinstance(result.parsed, dict) else _extract_json(result.text)
                outline = LeaderOutline.model_validate(parsed)
            except ValidationError as exc:
                errors = _schema_errors(exc)
                continue
            target_spec = outline.spec if initial else spec
            target_design = outline.design if initial else design
            sketch = TaskGraph(tasks=[], work_packages=outline.work_packages)
            errors = (
                check_spec(target_spec, [])
                + check_design(target_design, target_spec, [])
                + check_work_packages(sketch, target_spec, target_design)
            )
            if not errors:
                if initial:
                    spec, design = outline.spec, outline.design
                packages = outline.work_packages
                break
        else:
            raise ValidationFailed("Leader 的工作包划分未通过校验：" + "、".join(errors[:5]))
    else:
        packages = work_packages or []

    scripted = _is_scripted(bench)
    if packages and not scripted:
        target = int((bench.limits.get("plan") or {}).get("min_tasks_per_package") or 50)
        package_instructions = _system_for(bot, memory, files, "leader_package_tasks.md")
        package_codes = {current.code for current in packages}
        module_deps = {module.code: set(module.depends_on) for module in design.modules}
        packages_by_module: dict[str, set[str]] = {}
        for current in packages:
            packages_by_module.setdefault(current.module, set()).add(current.code)

        async def generate_package(current: WorkPackage):
            errors = []
            for attempt in range(2):
                logger.info("plan package %s attempt %s", current.code, attempt + 1)
                material = {
                    "approved_specification": package.body_md,
                    "spec": spec.model_dump(),
                    "design": design.model_dump(),
                    "package": current.model_dump(),
                    "work_packages": [item.model_dump() for item in packages],
                    "target_count": target,
                    "capacity_points": capacity,
                    "schema": PackageTaskBatch.model_json_schema(),
                }
                if rewrite:
                    material["rewrite"] = rewrite
                result = await _call(
                    bench,
                    record.session_id,
                    bot,
                    [
                        {"role": "system", "content": package_instructions},
                        {"role": "user", "content": json.dumps(
                            {**material, "validation_feedback": errors}, ensure_ascii=False
                        )},
                    ],
                    operation="plan_rewrite" if not initial else "plan",
                    json_mode=True,
                    track_discussion_usage=False,
                    timeout=900.0,
                    checkpoint=False,
                )
                try:
                    parsed = result.parsed if isinstance(result.parsed, dict) else _extract_json(result.text)
                    batch = PackageTaskBatch.model_validate(parsed)
                except ValidationError as exc:
                    errors = _schema_errors(exc)
                    continue
                errors, prepared = _prepare_package_tasks(
                    current, batch, target, spec, design, package_codes - {current.code}
                )
                if not errors:
                    logger.info("plan package %s done with %s tasks", current.code, len(prepared))
                    return current.code, prepared, list(batch.depends_on_packages)
            raise ValidationFailed(
                f"工作包 {current.code} 未通过校验：" + "、".join(errors[:5])
            )

        results = await asyncio.gather(*(generate_package(current) for current in packages))
        all_tasks: list[TaskCard] = []
        package_deps: dict[str, list[str]] = {}
        package_by_code = {current.code: current for current in packages}
        for code, prepared, _declared in results:
            all_tasks.extend(prepared)
            # Package order follows the approved module graph only.  Free-form
            # declared package edges caused cross-package cycles in practice.
            deps: set[str] = set()
            current = package_by_code[code]
            for dep_module in module_deps.get(current.module, set()):
                deps.update(packages_by_module.get(dep_module, set()))
            deps.discard(code)
            package_deps[code] = sorted(dep for dep in deps if dep in package_codes)
        _expand_package_dependencies(package_deps, all_tasks)
        _serialize_write_conflicts(all_tasks, [item.code for item in packages])
        graph = TaskGraph(tasks=all_tasks, work_packages=packages, capacity=capacity)
        modules = {module.code for module in design.modules}
        errors = [
            f"{task.code} 的所属模块无效或缺少来源"
            for task in graph.tasks
            if task.module not in modules or not task.sources
        ]
        errors += check_task_graph(graph, spec, design, capacity)
        if errors:
            raise ValidationFailed("Leader 的任务计划未通过校验：" + "、".join(errors[:5]))
        if initial:
            return LeaderPlan(spec=spec, design=design, plan=graph)
        return graph

    task_material = {
        "approved_specification": package.body_md,
        "spec": spec.model_dump(),
        "design": design.model_dump(),
        "work_packages": [item.model_dump() for item in packages],
        "capacity_points": capacity,
        "schema": TaskBatch.model_json_schema(),
    }
    if rewrite:
        task_material["rewrite"] = rewrite
    errors = []
    for _ in range(2):
        result = await _call(
            bench,
            record.session_id,
            bot,
            [
                {"role": "system", "content": task_instructions},
                {"role": "user", "content": json.dumps(
                    {**task_material, "validation_feedback": errors}, ensure_ascii=False
                )},
            ],
            operation="plan" if initial else "plan_rewrite",
            json_mode=True,
            track_discussion_usage=False,
            timeout=900.0,
            checkpoint=False,
        )
        try:
            parsed = result.parsed if isinstance(result.parsed, dict) else _extract_json(result.text)
            batch = TaskBatch.model_validate(parsed)
        except ValidationError as exc:
            errors = _schema_errors(exc)
            continue
        graph = TaskGraph(tasks=batch.tasks, work_packages=packages, capacity=capacity)
        modules = {module.code for module in design.modules}
        errors = [
            f"{task.code} 的所属模块无效或缺少来源"
            for task in graph.tasks
            if task.module not in modules or not task.sources
        ]
        errors += check_task_graph(graph, spec, design, capacity)
        if not errors:
            if initial:
                return LeaderPlan(spec=spec, design=design, plan=graph)
            return graph
    raise ValidationFailed("Leader 的任务计划未通过校验：" + "、".join(errors[:5]))


def _ensure_binding(existing, record: DiscussionSession) -> None:
    """A deterministic run_id is only reusable for the same project and session."""
    if getattr(existing, "project_id", "") != record.project_id:
        raise ValidationFailed("讨论会话与既有计划运行的所属项目不一致")
    linked = (getattr(existing, "artifacts", None) or {}).get("discussion_session_id")
    if linked and str(linked) != record.session_id:
        raise ValidationFailed("既有计划运行绑定了其它讨论会话")


async def structure_spec(bench, record: DiscussionSession) -> SpecDoc:
    """Leader structures the approved markdown specification into SPEC (no design)."""
    package = record.decision_package
    if record.status != "approved" or package is None:
        raise ValidationFailed("需先确认需求规格")
    bot, memory, files = await _load_bot_context(bench, record, record.leader_bot_id)
    instructions = _system_for(bot, memory, files, "leader_spec.md")
    errors: list[str] = []
    for _ in range(2):
        result = await _call(
            bench,
            record.session_id,
            bot,
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(
                    {
                        "approved_specification": package.body_md,
                        "schema": LeaderSpec.model_json_schema(),
                        "validation_feedback": errors,
                    }, ensure_ascii=False,
                )},
            ],
            operation="plan",
            json_mode=True,
            track_discussion_usage=False,
            timeout=900.0,
            checkpoint=False,
        )
        try:
            parsed = result.parsed if isinstance(result.parsed, dict) else _extract_json(result.text)
            spec = LeaderSpec.model_validate(parsed).spec
        except ValidationError as exc:
            errors = _schema_errors(exc)
            continue
        errors = check_spec(spec, [])
        if not errors:
            return spec
    raise ValidationFailed("Leader 的需求规格整理未通过校验：" + "、".join(errors[:5]))


async def prepare_design_run(bench, record: DiscussionSession) -> str:
    """SPEC 批准后进入第 5 步：架构师写 DESIGN + 设计检查 + 双评审 + DESIGN 基线确认关卡。

    Idempotent: an existing run bound to this session is returned unchanged, so a
    reload or a second click never regenerates the design.
    """
    run_id = run_id_for(record.session_id)
    locks = bench._discussion_plan_locks
    async with locks.setdefault(run_id, asyncio.Lock()):
        existing = bench.runs.get(run_id)
        if existing is not None:
            _ensure_binding(existing, record)
            return run_id
        spec = await structure_spec(bench, record)
        bench.create_discussion_design_run(record, spec, run_id)
        run = bench.runs[run_id]
        await bench.run_design(run)
        bench._persist_snapshot(run)
    return run_id


async def prepare_run(bench, record: DiscussionSession) -> str:
    """DESIGN 基线确认后，Leader 才把 SPEC/DESIGN 展开成工作包与任务（第 6 步）。"""
    run_id = run_id_for(record.session_id)
    locks = bench._discussion_plan_locks
    async with locks.setdefault(run_id, asyncio.Lock()):
        existing = bench.runs.get(run_id)
        if existing is None:
            raise ValidationFailed("需先完成设计规格整理与确认")
        _ensure_binding(existing, record)
        if existing.artifacts.get("plan"):
            return run_id
        if "DESIGN" not in (getattr(existing, "approved_baseline_hashes", None) or {}):
            raise ValidationFailed("需先确认设计规格基线")
        await bench._generate_plan(existing)
        bench._persist_snapshot(existing)
    return run_id
