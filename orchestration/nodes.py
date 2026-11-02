"""六个编排节点（LangGraph Node）。

每个节点都是纯函数：`state -> 局部增量`。节点之间不直接调用彼此，
所有协作只通过 State 完成，这样任意节点都可以被单独测试与替换。

角色与契约见 docs/contract.md §3。
"""

from __future__ import annotations

import re
from typing import Any

from .state import OrchestrationState, TraceEntry

# ---------------------------------------------------------------------------
# 需求官：一句话需求 -> 结构化 spec
# ---------------------------------------------------------------------------

#: 中文业务词 -> 字段定义。词表驱动，避免用正则去猜任意自然语言。
FIELD_VOCAB: dict[str, dict[str, Any]] = {
    "订单号": {"name": "order_no", "type": "str", "required": True},
    "金额": {"name": "amount", "type": "int", "required": True},
    "状态": {"name": "status", "type": "str", "required": False},
    "买家": {"name": "buyer_id", "type": "str", "required": False},
    "备注": {"name": "remark", "type": "str", "required": False},
}

OPERATION_VOCAB: dict[str, str] = {
    "创建": "create",
    "取消": "cancel",
    "查询": "get",
    "更新": "update",
}

ENTITY_VOCAB: dict[str, str] = {
    "订单": "order",
    "库存": "stock",
    "用户": "user",
}

#: 需求里没有任何业务词时的兜底字段，保证 spec 始终可执行。
DEFAULT_FIELDS = [
    {"name": "biz_no", "type": "str", "required": True},
    {"name": "amount", "type": "int", "required": True},
]


def intake(state: OrchestrationState) -> dict[str, Any]:
    """需求官：把一句话需求拆成可执行的 spec（实体 / 字段 / 操作）。"""
    text = (state.get("requirement") or "").strip()
    entity = next((v for k, v in ENTITY_VOCAB.items() if k in text), "resource")

    fields = [dict(v) for k, v in FIELD_VOCAB.items() if k in text]
    if not fields:
        fields = [dict(f) for f in DEFAULT_FIELDS]

    operations = [v for k, v in OPERATION_VOCAB.items() if k in text] or ["create", "get"]

    spec = {
        "entity": entity,
        "fields": fields,
        "operations": operations,
        "raw_requirement": text,
    }
    return {
        "spec": spec,
        "trace": [
            TraceEntry(
                node="intake",
                summary=f"实体={entity}，字段={len(fields)} 个，操作={','.join(operations)}",
            )
        ],
    }


# ---------------------------------------------------------------------------
# 契约官：spec -> 契约（可被门禁检查、可被代码生成消费）
# ---------------------------------------------------------------------------

#: 门禁打回时的修复动作码 -> 说明。architect 只认这些码，不做自由发挥。
REPAIR_MAP: dict[str, str] = {
    "CHECK_AUDIT": "补充 updated_at 审计字段",
    "CHECK_TERMINAL": "补充终态定义，且终态不得再有出边",
    "CHECK_INVARIANT": "补充不变量清单",
    "CHECK_IDEMPOTENCY": "指定幂等键，且该键必须是必填字段",
}


def contract_architect(state: OrchestrationState) -> dict[str, Any]:
    """契约官：起草或修订契约。

    首版刻意只写「最小可用」内容（不含审计字段与终态定义），
    让契约门禁有真实的可打回项，从而演示状态驱动的回流。
    """
    spec = state["spec"]
    feedback = list(state.get("gate_feedback") or [])
    base_version = int((state.get("contract") or {}).get("version", 0))

    required_fields = [f for f in spec["fields"] if f.get("required")]
    idem_key = required_fields[0]["name"] if required_fields else spec["fields"][0]["name"]

    fields: dict[str, dict[str, Any]] = {
        f["name"]: {"type": f["type"], "required": bool(f["required"])} for f in spec["fields"]
    }

    contract: dict[str, Any] = {
        "entity": spec["entity"],
        "version": base_version + 1,
        "fields": fields,
        "transitions": {"created": ["cancelled"]},
        "terminal_states": [],
        "invariants": ["同一幂等键重复提交返回既有记录，不新增"],
        "idempotency_key": idem_key,
    }

    applied: list[str] = []
    if "CHECK_AUDIT" in feedback:
        fields["updated_at"] = {"type": "str", "required": False}
        applied.append("CHECK_AUDIT")
    if "CHECK_TERMINAL" in feedback:
        contract["terminal_states"] = ["cancelled"]
        contract["transitions"] = {"created": ["cancelled"], "cancelled": []}
        contract["invariants"].append("cancelled 为终态，不可再发生迁移")
        applied.append("CHECK_TERMINAL")
    if "CHECK_IDEMPOTENCY" in feedback:
        fields[idem_key] = {"type": "str", "required": True}
        applied.append("CHECK_IDEMPOTENCY")

    note = "首版契约" if not feedback else f"按反馈修复 {','.join(applied) or '无匹配项'}"
    return {
        "contract": contract,
        "trace": [
            TraceEntry(node="contract_architect", summary=f"v{contract['version']} · {note}")
        ],
    }


# ---------------------------------------------------------------------------
# 契约门禁：检查契约完整性（不通过则回流给契约官）
# ---------------------------------------------------------------------------


def contract_gate(state: OrchestrationState) -> dict[str, Any]:
    """契约门禁：把契约当唯一真相，缺一项就打回。"""
    contract = state["contract"]
    fields: dict[str, dict[str, Any]] = contract.get("fields") or {}
    feedback: list[str] = []

    if not fields:
        feedback.append("CHECK_FIELDS")
    if "updated_at" not in fields:
        feedback.append("CHECK_AUDIT")

    terminals = contract.get("terminal_states") or []
    transitions: dict[str, list[str]] = contract.get("transitions") or {}
    terminal_ok = bool(terminals) and all(not transitions.get(t) for t in terminals)
    if not terminal_ok:
        feedback.append("CHECK_TERMINAL")

    if not contract.get("invariants"):
        feedback.append("CHECK_INVARIANT")

    idem = contract.get("idempotency_key")
    if not idem or not (fields.get(idem) or {}).get("required"):
        feedback.append("CHECK_IDEMPOTENCY")

    rounds = int(state.get("gate_rounds", 0)) + 1
    summary = "通过" if not feedback else f"打回 {','.join(feedback)}"
    return {
        "gate_feedback": feedback,
        "gate_rounds": rounds,
        "trace": [TraceEntry(node="contract_gate", summary=f"第 {rounds} 轮 · {summary}")],
    }


# ---------------------------------------------------------------------------
# 实现官：契约 -> 可执行源码
# ---------------------------------------------------------------------------

#: 代码模板。用占位符替换而不是 f-string，避免业务代码里的 {} 与插值冲突。
SERVICE_TEMPLATE = '''"""由编排流水线根据契约生成的业务服务（demo 产物，勿手改）。"""


class ContractService:
    FIELD_SPEC = __FIELD_SPEC__
    TRANSITIONS = __TRANSITIONS__
    TERMINAL_STATES = __TERMINAL_STATES__
    IDEMPOTENCY_KEY = __IDEMPOTENCY_KEY__
    AUDIT_FIELD = "updated_at"

    def __init__(self):
        self._store = {}
        self._clock = 0

    def _tick(self):
        self._clock += 1
        return "T" + str(self._clock)

    def _validate(self, payload):
        for name, spec in self.FIELD_SPEC.items():
            if spec.get("required") and name not in payload:
                raise ValueError("字段缺失: " + name)
            if name in payload:
                expected = spec.get("type")
                actual = payload[name]
                if expected == "int" and not isinstance(actual, int):
                    raise ValueError("字段类型错误: " + name)
                if expected == "str" and not isinstance(actual, str):
                    raise ValueError("字段类型错误: " + name)

    def create(self, payload):
        self._validate(payload)
        key = payload.get(self.IDEMPOTENCY_KEY)
        if key in self._store:
            return dict(self._store[key])
        record = dict(payload)
        record.setdefault("status", "created")
        if self.AUDIT_FIELD in self.FIELD_SPEC:
            record[self.AUDIT_FIELD] = self._tick()
        self._store[key] = record
        return dict(record)

    def cancel(self, key):
        return self._transition(key, "cancelled")

    def _transition(self, key, target):
        if key not in self._store:
            raise KeyError("记录不存在: " + str(key))
        record = self._store[key]
        allowed = self.TRANSITIONS.get(record.get("status", "created"), [])
        if target not in allowed:
            raise ValueError(
                "非法状态迁移: " + str(record.get("status")) + " -> " + str(target)
            )
        record["status"] = target
        if self.AUDIT_FIELD in self.FIELD_SPEC:
            record[self.AUDIT_FIELD] = self._tick()
        return dict(record)

    def get(self, key):
        if key not in self._store:
            raise KeyError("记录不存在: " + str(key))
        return dict(self._store[key])

    def count(self):
        return len(self._store)
'''


def _render_source(contract: dict[str, Any]) -> str:
    source = SERVICE_TEMPLATE
    source = source.replace("__FIELD_SPEC__", repr(contract["fields"]))
    source = source.replace("__TRANSITIONS__", repr(contract.get("transitions") or {}))
    source = source.replace("__TERMINAL_STATES__", repr(contract.get("terminal_states") or []))
    source = source.replace("__IDEMPOTENCY_KEY__", repr(contract["idempotency_key"]))
    return source


def implementer(state: OrchestrationState) -> dict[str, Any]:
    """实现官：把契约渲染成真实可执行的 Python 源码。"""
    contract = state["contract"]
    source = _render_source(contract)
    implementation = {
        "path": "orchestration/generated_service.py (内存生成，不落盘)",
        "source": source,
        "lines": len(source.splitlines()),
        "contract_version": contract["version"],
    }
    return {
        "implementation": implementation,
        "trace": [
            TraceEntry(
                node="implementer",
                summary=f"依据契约 v{contract['version']} 生成 {implementation['lines']} 行源码",
            )
        ],
    }


# ---------------------------------------------------------------------------
# 验证官：对生成代码跑真实不变量检查
# ---------------------------------------------------------------------------


def _load_service(source: str):
    """在受控命名空间里执行生成代码，取回服务类。"""
    namespace: dict[str, Any] = {"__name__": "generated_service"}
    exec(compile(source, "<generated_service>", "exec"), namespace)  # noqa: S102 - demo 场景
    return namespace["ContractService"]


def _sample_value(field_type: str) -> Any:
    """按字段类型造样本值：int -> 100，其余 -> 'A-1'。"""
    return 100 if field_type == "int" else "A-1"


def verifier(state: OrchestrationState) -> dict[str, Any]:
    """验证官：跑不变量检查，逐条记录证据（不是「链路跑通」即算通过）。

    所有检查都从契约动态推导字段名，不写死任何一个业务字段，
    因此换需求（例如库存、用户）时这套不变量依然成立。
    """
    contract = state["contract"]
    fields: dict[str, dict[str, Any]] = contract["fields"]
    key_name = contract["idempotency_key"]
    required = [n for n, s in fields.items() if s.get("required")]
    payload = {n: _sample_value(fields[n]["type"]) for n in required}
    key_value = payload[key_name]

    service_cls = _load_service(state["implementation"]["source"])
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    # 1. 正常创建
    svc = service_cls()
    created = svc.create(dict(payload))
    record(
        "create_valid_order",
        created.get("status") == "created" and all(created.get(k) == v for k, v in payload.items()),
        f"status={created.get('status')}",
    )

    # 2. 缺必填字段必须拒绝（挑一个非幂等键的必填字段来删）
    victim = next((n for n in required if n != key_name), key_name)
    broken = {k: v for k, v in payload.items() if k != victim}
    try:
        service_cls().create(broken)
        record("reject_missing_field", False, "缺字段仍被接受")
    except ValueError as exc:
        record("reject_missing_field", True, str(exc))

    # 3. 幂等：同一键重复提交不新增记录，且不覆盖既有值
    mutated = dict(payload)
    for n, s in fields.items():
        if s.get("type") == "int" and n != key_name:
            mutated[n] = 999
    svc.create(mutated)
    record(
        "idempotent_duplicate",
        svc.count() == 1 and all(svc.get(key_value)[k] == v for k, v in payload.items()),
        f"count={svc.count()}",
    )

    # 4. 非法状态迁移必须拒绝（终态不可再迁移）
    svc.cancel(key_value)
    try:
        svc.cancel(key_value)
        record("reject_illegal_transition", False, "终态被二次迁移")
    except ValueError as exc:
        record("reject_illegal_transition", True, str(exc))

    # 5. 审计字段必须写入
    record(
        "audit_field_written",
        "updated_at" in svc.get(key_value),
        f"updated_at={svc.get(key_value).get('updated_at')}",
    )

    # 6. 不存在的记录必须报错而不是返回空
    try:
        svc.get("__NOT_EXIST__")
        record("reject_unknown_record", False, "返回了空对象")
    except KeyError as exc:
        record("reject_unknown_record", True, str(exc))

    passed = sum(1 for c in checks if c["passed"])
    return {
        "checks": checks,
        "trace": [
            TraceEntry(node="verifier", summary=f"{passed}/{len(checks)} 项不变量通过")
        ],
    }


# ---------------------------------------------------------------------------
# 评审官：聚合证据给出结论（不通过则回流给实现官）
# ---------------------------------------------------------------------------


def reviewer(state: OrchestrationState) -> dict[str, Any]:
    """评审官：只有全部不变量通过才判 accepted。"""
    checks = state.get("checks") or []
    failed = [c for c in checks if not c["passed"]]
    rounds = int(state.get("review_rounds", 0)) + 1

    if checks and not failed:
        verdict = "accepted"
        feedback: list[str] = []
    else:
        verdict = "rejected"
        feedback = ["REWORK_CHECKS"]

    summary = "通过" if verdict == "accepted" else f"{len(failed)} 项未通过"
    return {
        "verdict": verdict,
        "gate_feedback": feedback,
        "review_rounds": rounds,
        "trace": [TraceEntry(node="reviewer", summary=f"第 {rounds} 轮评审 · {summary}")],
    }
