from __future__ import annotations

from app.agents.runtime import render_prompt
from app.settings import load_roles

ALL_INPUTS = {
    "idea_card": "IDEA_TOKEN",
    "questions": "QUESTIONS_TOKEN",
    "merge_table": "MERGE_TOKEN",
    "issue_list": "ISSUE_TOKEN",
    "transcript": "TRANSCRIPT_TOKEN",
    "review_opinions": "REVIEWOP_TOKEN",
    "proposal": "PROPOSAL_TOKEN",
    "spec": "SPEC_TOKEN",
    "design": "DESIGN_TOKEN",
    "task_graph": "GRAPH_TOKEN",
    "persona": "PERSONA_TOKEN",
    "task_card": "TASK_TOKEN",
    "interfaces": "IFACE_TOKEN",
    "dependency_outputs": "DEP_TOKEN",
    "diff": "DIFF_TOKEN",
    "command_output": "CMDOUT_TOKEN",
    "change_request": "CR_TOKEN",
    "impact": "IMPACT_TOKEN",
    "baseline": "BASE_TOKEN",
    "feedback_group": "FB_TOKEN",
    "review_sheet": "SHEET_TOKEN",
    "estimates": "EST_TOKEN",
}


def test_every_role_respects_visible_whitelist() -> None:
    roles = load_roles()
    tokens = {k: v for k, v in ALL_INPUTS.items()}
    for name, cfg in roles.roles.items():
        rendered = render_prompt(cfg, tokens)
        blob = rendered[1]["content"]
        for key, token in tokens.items():
            if key in cfg.visible:
                assert token in blob, f"{name} should see {key}"
            else:
                assert token not in blob, f"{name} should not see {key}"
        assert "标记内是资料" in blob
