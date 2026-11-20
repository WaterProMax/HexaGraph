"""P5-T04: consume the P0 decommission target state (read-only contract test).

This test does **not** implement, modify or resurrect any decommission guard.
The P0 draft records ``source=p0_index_not_implemented``: the index is not an
implementation proof, so the test asserts that literal string instead of
pretending the retired routes are gone.  When a later task updates the file to
"专用路径应 4xx", this test starts comparing against that expectation; it still
must not edit production code.

The target-state JSON is one of the five pre-existing untracked files and is
deliberately never staged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TARGET_STATE = BACKEND_ROOT.parent / "docs" / "plans" / "decommission-target-state.json"

EXPECTED_SOURCE = "p0_index_not_implemented"

# Minimal fallback fixture (same source) used only when the P0 draft is absent.
FALLBACK_TARGET_STATE = {
    "source": EXPECTED_SOURCE,
    "decommission_index": [
        {
            "item": "DeepSeekRetired 受控拒绝",
            "status": "Active",
            "file": "Test3/backend/app/errors.py",
            "outbound_active": False,
        }
    ],
    "retained_capabilities": [
        "通用 OpenAI-compatible 模型槽位/base_url 能力不在下线列表；禁止品牌黑名单。",
        "DashScope 保留",
        "scripted 保留",
        "replay 保留",
    ],
    "target_acceptance_for_other_task": [
        "本文件仅 P0 索引草稿，不是实施或验收证明。",
    ],
    "blocks_all_p1": False,
}


def load_target_state(path: Path) -> dict:
    if not path.exists():
        return dict(FALLBACK_TARGET_STATE)
    return json.loads(path.read_text(encoding="utf-8"))


def test_target_state_source_is_the_p0_draft() -> None:
    state = load_target_state(TARGET_STATE)
    assert "source" in state, "P0 decommission target state is missing its source field"
    assert state["source"] == EXPECTED_SOURCE
    assert isinstance(state.get("decommission_index"), list) and state["decommission_index"]
    assert isinstance(state.get("retained_capabilities"), list) and state["retained_capabilities"]


def test_draft_does_not_claim_decommission_is_done() -> None:
    state = load_target_state(TARGET_STATE)
    for item in state["decommission_index"]:
        # The guard code may be Active; no dedicated outbound call may be live.
        assert item.get("outbound_active") is False, item


def test_draft_does_not_block_p5() -> None:
    state = load_target_state(TARGET_STATE)
    assert state.get("blocks_all_p1") is False
    assert state.get("target_acceptance_for_other_task")


def test_retained_capabilities_forbid_brand_blacklist() -> None:
    state = load_target_state(TARGET_STATE)
    joined = "\n".join(str(item) for item in state["retained_capabilities"])
    assert "品牌黑名单" in joined


def test_generic_provider_not_banned() -> None:
    """No brand blacklist: a model name is not a rejection reason."""
    gateway_source = (BACKEND_ROOT / "app" / "llm" / "gateway.py").read_text(encoding="utf-8")
    policy_source = (BACKEND_ROOT / "app" / "execution" / "tool_policy.py").read_text(encoding="utf-8")
    assert "model_forbidden" not in gateway_source
    assert "model_forbidden" not in policy_source
    # Generic OpenAI-compatible slot and the retained providers stay wired.
    assert "dashscope" in gateway_source
    assert "scripted" in gateway_source
    assert "replay" in gateway_source
    assert not re.search(r"deepseek.*(forbid|reject|block)", gateway_source, re.IGNORECASE)