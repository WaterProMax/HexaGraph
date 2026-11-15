"""设计规格导入的纯函数与模型整理调用。

边界：
- 外部文档只作为输入来源；落库与后续流程仍使用 SpecDoc / DesignDoc。
- 这里不做任务分解、不创建任务、不触发调度。
- 所有校验都是确定性函数，模型输出必须过校验才允许进入 DESIGN 关卡。
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.agents.runtime import RoleRegistry, call_agent
from app.docs.checks import check_design, check_spec
from app.llm.gateway import Gateway
from app.schemas.design_input import (
    MAX_INPUT_BYTES,
    MODEL_CHAR_BUDGET,
    DesignInputMeta,
    DesignIntake,
    DesignSource,
    SpecIntake,
)


def measure_input(text: str, source: DesignSource) -> DesignInputMeta:
    raw = text.encode("utf-8")
    return DesignInputMeta(
        kind=source.kind,
        name=source.name,
        note=source.note,
        bytes=len(raw),
        chars=len(text),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def validate_input(text: str) -> list[str]:
    """空文本与 100 KiB 上限。返回可直接展示的错误。"""
    errors: list[str] = []
    if not text or not text.strip():
        errors.append("设计规格为空")
        return errors
    size = len(text.encode("utf-8"))
    if size > MAX_INPUT_BYTES:
        errors.append(f"设计规格 {size} 字节，超过上限 {MAX_INPUT_BYTES} 字节（100 KiB）")
    return errors


def model_budget_error(meta: DesignInputMeta) -> str:
    if meta.chars <= MODEL_CHAR_BUDGET:
        return ""
    return (
        f"设计规格 {meta.chars} 字符，超过单次整理上限 {MODEL_CHAR_BUDGET} 字符；"
        "请按章节拆成多份后分别导入，避免静默截断内容。"
    )


def input_payload(text: str, title: str, source: DesignSource, meta: DesignInputMeta) -> dict[str, Any]:
    return {
        "title": title or source.name or "设计规格",
        "source": {"kind": source.kind, "name": source.name, "note": source.note},
        "sha256": meta.sha256,
        "text": text,
    }


async def intake_spec(
    text: str,
    title: str,
    source: DesignSource,
    meta: DesignInputMeta,
    *,
    gateway: Gateway,
    registry: RoleRegistry,
) -> SpecIntake:
    result = await call_agent(
        "spec_importer",
        {"design_input": input_payload(text, title, source, meta)},
        registry=registry,
        gateway=gateway,
    )
    if not isinstance(result, SpecIntake):
        raise TypeError(f"spec_importer 返回 {type(result).__name__}，期望 SpecIntake")
    return result


async def intake_design(
    text: str,
    title: str,
    source: DesignSource,
    meta: DesignInputMeta,
    spec: SpecIntake,
    *,
    gateway: Gateway,
    registry: RoleRegistry,
) -> DesignIntake:
    result = await call_agent(
        "design_importer",
        {
            "design_input": input_payload(text, title, source, meta),
            "spec": spec.spec.model_dump(),
        },
        registry=registry,
        gateway=gateway,
    )
    if not isinstance(result, DesignIntake):
        raise TypeError(f"design_importer 返回 {type(result).__name__}，期望 DesignIntake")
    return result


def cross_checks(spec: SpecIntake, design: DesignIntake, *, max_modules: int) -> dict[str, list[str]]:
    """复用现有校验器，再补两条导入特有的引用检查。"""
    issues: list[Any] = []
    spec_errors = check_spec(spec.spec, issues, None)
    design_errors = check_design(design.design, spec.spec, issues, max_modules=max_modules)

    feature_codes = {item.code for item in spec.spec.features + spec.spec.nonfunc}
    module_codes = {module.code for module in design.design.modules}
    for module in design.design.modules:
        for src in module.sources:
            if src not in feature_codes:
                design_errors.append(f"模块来源不存在: {module.code}/{src}")
        for dep in module.depends_on:
            if dep not in module_codes:
                design_errors.append(f"模块依赖不存在: {module.code}/{dep}")
    for iface in design.design.interfaces:
        for ref in list(iface.consumers):
            if ref not in module_codes:
                design_errors.append(f"接口调用方不存在: {iface.code}/{ref}")
    return {"spec": spec_errors, "design": design_errors}


def merge_missing(*groups: list[str]) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for item in group:
            text = str(item).strip()
            if text and text not in seen:
                seen.append(text)
    return seen
