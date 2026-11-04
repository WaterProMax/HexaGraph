from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from datetime import datetime

class LeaveState(TypedDict, total=False):
    name: str
    days: int
    valid: bool
    status: str
    message: str
    start_date: str
    end_date:str
    reason: str

def reject(state: LeaveState):
    return {
        "status": "rejected",
    }


def direct_pass(state: LeaveState):
    return {
        "status": "approved",
        "message": "请假不超过三天，直接通过",
    }

def teacher_review(state: LeaveState):
    return {
        "status": "pending",
        "message": "等待老师审批",
    }

def validate_leave(state: LeaveState):
    required_fields = ("name","start_date","end_date","days","reason")
    missing_fields = []

    for field in required_fields:
        content = state.get(field)

        if field != "days" and isinstance(content, str):
            content = content.strip()

        if content is None or content == "":
            missing_fields.append(field)

    if missing_fields:
        return {
            "valid": False,
            "message": f"缺少必填信息：{', '.join(missing_fields)}",
        }

    if not isinstance(state["start_date"], str) or not isinstance(state["end_date"], str):
        return {
            "valid": False,
            "message": "开始日期和结束日期必须是字符串",
        }

    try:
        start_date = datetime.strptime(state["start_date"], "%Y-%m-%d")
        end_date = datetime.strptime(state["end_date"], "%Y-%m-%d")
    except ValueError:
        return {
            "valid": False,
            "message": "日期无效或格式不正确，请使用 YYYY-MM-DD",
        }

    if start_date > end_date:
        return {
            "valid": False,
            "message": "开始日期不能晚于结束日期",
        }

    days = state["days"]
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        return {
            "valid": False,
            "message": "请假天数必须是正整数",
        }

    return {
        "valid": True,
    }

def route_leave(state: LeaveState):
    if not state["valid"]:
        return "reject"
    elif state["days"] <= 3:
        return "direct_pass"
    else:
        return "teacher_review"

builder = StateGraph(LeaveState)

builder.add_node("reject", reject)
builder.add_node("direct_pass", direct_pass)
builder.add_node("teacher_review", teacher_review)
builder.add_node("validate_leave", validate_leave)

builder.add_edge(START, "validate_leave")

builder.add_conditional_edges(
    "validate_leave",
    route_leave,
    {
        "reject": "reject",
        "direct_pass": "direct_pass",
        "teacher_review": "teacher_review",
    },
)

builder.add_edge("reject", END)
builder.add_edge("direct_pass", END)
builder.add_edge("teacher_review",END)

graph = builder.compile()

test_cases = [
    {"name": "小明","start_date":20261101, "end_date":"2026-11-03","days":2,"reason":"生病"},
    {"name": "小明","start_date":"2026-02-30", "end_date":"2026-11-03","days": 2,"reason":"生病"},
    {"name": "小明","start_date":"2026-11-01", "end_date":"2026-11-03","days": 4,"reason":"生病"},
]

if __name__ == "__main__":
    for case in test_cases:
        print(graph.invoke(case))
