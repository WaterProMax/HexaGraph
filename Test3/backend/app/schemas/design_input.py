"""设计规格导入：外部文档是输入来源，内部仍落回 SpecDoc / DesignDoc。

本模块只描述“导入”这一层的请求、来源和模型整理结果，不定义第二套任务图
或调度状态。确认、分解、执行仍复用 runtime 的 DESIGN / PLAN 关卡。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.docs import DesignDoc, SpecDoc

# 接口层硬上限：前后端统一按 100 KiB 校验。
MAX_INPUT_BYTES = 100 * 1024
# 单次模型整理的软上限；超过时明确要求拆分，不静默截断。
MODEL_CHAR_BUDGET = 24_000


class DesignSource(BaseModel):
    """输入来源标识，用于审计与页面展示。"""

    kind: Literal["text", "file"] = "text"
    name: str = ""
    note: str = ""


class DesignRunCreate(BaseModel):
    text: str
    source: DesignSource = Field(default_factory=DesignSource)
    title: str = ""
    provider: Literal["existing", "deepseek"] = "existing"


class SpecIntake(BaseModel):
    """spec_importer 的结构化输出。"""

    spec: SpecDoc
    missing: list[str] = Field(default_factory=list)
    notes: str = ""
    section_map: list[dict[str, str]] = Field(default_factory=list)


class DesignIntake(BaseModel):
    """design_importer 的结构化输出。"""

    design: DesignDoc
    missing: list[str] = Field(default_factory=list)
    notes: str = ""
    section_map: list[dict[str, str]] = Field(default_factory=list)


class DesignInputMeta(BaseModel):
    kind: Literal["text", "file"] = "text"
    name: str = ""
    note: str = ""
    bytes: int = 0
    chars: int = 0
    sha256: str = ""


class DesignRunResult(BaseModel):
    """POST /projects/{id}/design-runs 的响应体。"""

    run_id: str
    project_id: str
    status: Literal[
        "importing",
        "awaiting_confirmation",
        "needs_input",
        "needs_split",
        "failed",
    ]
    input: DesignInputMeta
    spec: dict | None = None
    design: dict | None = None
    missing: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    error_category: str | None = None
    checks: dict[str, list[str]] = Field(default_factory=dict)
    gate: dict | None = None
    provenance: dict = Field(default_factory=dict)
    message: str = ""
