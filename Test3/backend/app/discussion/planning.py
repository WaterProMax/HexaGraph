"""Bridge a human-approved discussion to the existing planning gate."""

from __future__ import annotations

import asyncio
import json
import uuid

from pydantic import BaseModel, ValidationError

from app.discussion.driver import _call, _extract_json, _load_bot_context, _system_for
from app.discussion.models import DiscussionSession
from app.docs.checks import check_design, check_spec, check_task_graph
from app.errors import ValidationFailed
from app.schemas.docs import DesignDoc, SpecDoc, TaskGraph


class LeaderPlan(BaseModel):
    spec: SpecDoc
    design: DesignDoc
    plan: TaskGraph


def run_id_for(session_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hexagraph:discussion:{session_id}"))


async def generate(bench, record: DiscussionSession, *, spec=None, design=None, rewrite=None):
    package = record.decision_package
    if record.status != "approved" or package is None:
        raise ValidationFailed("需先确认需求规格")
    initial = spec is None
    schema = LeaderPlan if initial else TaskGraph
    capacity = int(bench.limits["plan"]["capacity_points"])
    bot, memory, files = await _load_bot_context(bench, record, record.leader_bot_id)
    instructions = _system_for(bot, memory, files, "leader_planning.md")
    material = {
        "approved_specification": package.body_md,
        "capacity_points": capacity,
        "schema": schema.model_json_schema(),
    }
    if not initial:
        material.update(spec=spec.model_dump(), design=design.model_dump(), rewrite=rewrite)
    errors: list[str] = []
    for _ in range(2):
        result = await _call(
            bench,
            record.session_id,
            bot,
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(
                    {**material, "validation_feedback": errors}, ensure_ascii=False
                )},
            ],
            operation="plan" if initial else "plan_rewrite",
            json_mode=True,
            track_discussion_usage=False,
            # SPEC+DESIGN+PLAN 单次输出约 22K token，耗时数分钟；给足 15 分钟避免 120s 默认超时。
            timeout=900.0,
        )
        try:
            parsed = result.parsed if isinstance(result.parsed, dict) else _extract_json(result.text)
            output = schema.model_validate(parsed)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(part) for part in issue['loc']) or '任务计划'}（{issue['type']}）"
                for issue in exc.errors(include_input=False, include_context=False, include_url=False)[:5]
            ]
            continue
        if isinstance(output, LeaderPlan):
            spec, design, graph = output.spec, output.design, output.plan
            errors = check_spec(spec, []) + check_design(design, spec, [])
        else:
            graph = output
            errors = []
        graph.capacity = capacity
        modules = {module.code for module in design.modules}
        errors += [
            f"{task.code} 的所属模块无效或缺少来源"
            for task in graph.tasks
            if task.module not in modules or not task.sources
        ]
        errors += check_task_graph(graph, spec, design, capacity)
        if not errors:
            return output
    raise ValidationFailed("Leader 的任务计划未通过校验：" + "、".join(errors[:5]))


async def prepare_run(bench, record: DiscussionSession) -> str:
    run_id = run_id_for(record.session_id)
    locks = bench._discussion_plan_locks
    async with locks.setdefault(run_id, asyncio.Lock()):
        if run_id not in bench.runs:
            output = await generate(bench, record)
            bench.create_discussion_plan_run(record, output, run_id)
    return run_id
