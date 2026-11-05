from __future__ import annotations

from typing import Any

from app.schemas.common import Claim, Target
from app.schemas.docs import IdeaCard, Issue, MergeRow, Question, Utterance

IDEA = IdeaCard(
    raw="做一个帮同学在期末周找到有空位自习室的小程序。",
    user="期末周需要自习、没有固定座位的本校本科生",
    problem="期末周自习室座位紧张，跑了几栋楼都找不到空位，浪费时间",
    needs_payer=True,
    payer="后勤",
    approach="按教学楼和楼层列出自习教室，到场的同学上报剩余座位数，其他同学查看",
    features=["按楼栋和楼层查看剩余座位", "上报剩余座位数", "收藏常去的教室"],
)

QUESTIONS = [
    Question(code="Q-01", role="产品经理", category="竞争", text="学生现在在微信群里问哪里有位，我们比群聊好在哪？", reason="群聊零成本"),
    Question(code="Q-02", role="产品经理", category="范围", text="第一版覆盖几栋楼？", reason="全校铺开会摊薄上报"),
    Question(code="Q-03", role="用户代表", category="价值", text="我到了楼下才会想查，要是还得先登录，我宁可直接上楼看", reason="必须比上楼更快"),
    Question(code="Q-04", role="用户代表", category="价值", text="信息过期了，我会白跑一趟", reason="白跑一次就不再相信"),
    Question(code="Q-05", role="付费方代表", category="可行性", text="接入门禁或摄像头数据涉及隐私", reason="需要审批"),
    Question(code="Q-06", role="付费方代表", category="范围", text="会不会有人刷假消息，或者借此占座", reason="已有占座纠纷"),
    Question(code="Q-07", role="开发", category="可行性", text="上报靠手动输入，数字可能填错或乱填", reason="没有校验"),
    Question(code="Q-08", role="开发", category="可行性", text="上报的人少时信息很稀疏", reason="冷启动"),
    Question(code="Q-09", role="测试", category="可测性", text="有空位怎么定义？剩 1 个算不算？", reason="写不出验收"),
    Question(code="Q-10", role="测试", category="可测性", text="一条上报多久以前的算过期？", reason="写不出验收"),
]

MERGE_ROWS = [
    MergeRow(issue="I-01", from_questions=["Q-05"], proposers=["付费方代表"], text="是否接入学校的门禁或摄像头数据", category="可行性"),
    MergeRow(issue="I-02", from_questions=["Q-04", "Q-09", "Q-10"], proposers=["用户代表", "测试"], text="有空位如何定义，多久算过期", category="可测性"),
    MergeRow(issue="I-03", from_questions=["Q-08"], proposers=["开发"], text="上报的人够不够", category="可行性"),
    MergeRow(issue="I-04", from_questions=["Q-01"], proposers=["产品经理"], text="比微信群好在哪", category="竞争"),
    MergeRow(issue="I-05", from_questions=["Q-03"], proposers=["用户代表"], text="查询门槛是否需要登录", category="价值"),
    MergeRow(issue="I-06", from_questions=["Q-06", "Q-07"], proposers=["付费方代表", "开发"], text="上报的数据是否可信", category="范围"),
    MergeRow(issue="I-07", from_questions=["Q-02"], proposers=["产品经理"], text="第一版覆盖范围", category="范围"),
]


def issues() -> list[Issue]:
    return [
        Issue(code=r.issue, sources=r.from_questions, proposers=r.proposers, category=r.category, text=r.text, assumption_critical=_flag(r.issue))
        for r in MERGE_ROWS
    ]


def _flag(code: str) -> bool | None:
    if code in {"I-03", "I-04"}:
        return True
    if code in {"I-05", "I-06"}:
        return False
    return None


def utterances() -> list[Utterance]:
    return [
        Utterance(seq=1, role="主持人", targets=[Target(issue="I-01", to_role="开发")], position="追问", body="第一轮的 10 个问题已合并为 7 条争议。请开发先回应。", reasons="开场", mention=["开发"]),
        Utterance(seq=2, role="开发", targets=[Target(issue="I-01")], position="补充", body="建议第一版不依赖学校数据，只用学生上报。接入要经过学校审批。", reasons="审批不受我们控制", claims=[Claim(text="接入要审批", kind="事实")]),
        Utterance(seq=3, role="付费方代表", targets=[Target(issue="I-01"), Target(issue="I-06")], position="接受", body="对 I-01 接受。对 I-06 提议限频。", reasons="避开隐私评估", claims=[Claim(text="刷假消息尚未发生", kind="假设")]),
        Utterance(seq=4, role="测试", targets=[Target(issue="I-06"), Target(issue="I-02")], position="补充", body="限频可验证。显示剩余座位数和上报时间，超过 30 分钟标灰。", reasons="可测"),
        Utterance(seq=5, role="用户代表", targets=[Target(issue="I-02"), Target(issue="I-03")], position="接受", body="显示剩余座位数和时间我接受。如果大部分是灰的，我第二次就不会打开。", reasons="人设", claims=[Claim(text="信息稀疏导致流失", kind="假设")]),
        Utterance(seq=6, role="主持人", targets=[Target(issue="I-05", to_role="开发")], position="追问", body="I-02 还需要提出者以外的角色回应；I-05 还没有人回应，请开发说明。", reasons="规则1", mention=["开发"]),
        Utterance(seq=7, role="开发", targets=[Target(issue="I-05"), Target(issue="I-02"), Target(issue="I-06")], position="接受", body="查看不需要登录、上报才需要。限频接受。", reasons="实现可行"),
        Utterance(seq=8, role="产品经理", targets=[Target(issue="I-03"), Target(issue="I-07")], position="补充", body="第一版只覆盖一栋教学楼。上报量只能靠真人试点验证。", reasons="集中上报", claims=[Claim(text="单栋能凑够上报", kind="假设")]),
        Utterance(seq=9, role="付费方代表", targets=[Target(issue="I-07")], position="同意", body="只做一栋楼我同意，可以配合张贴二维码。", reasons="后勤可配合"),
        Utterance(seq=10, role="用户代表", targets=[Target(issue="I-04"), Target(issue="I-05")], position="接受", body="群里问经常没人回，按楼层看更快。查看免登录我接受。", reasons="人设", claims=[Claim(text="群聊回复慢", kind="假设")]),
        Utterance(seq=11, role="主持人", targets=[Target(issue="I-04", to_role="产品经理"), Target(issue="I-03", to_role="开发")], position="追问", body="请产品经理对 I-04 表态，再请开发对 I-03 表态。", reasons="规则1", mention=["产品经理", "开发"]),
        Utterance(seq=12, role="产品经理", targets=[Target(issue="I-04")], position="不接受", body="I-04 优势依赖上报量，不能算有结论。I-07 按一栋楼执行。", reasons="依赖 I-03"),
        Utterance(seq=13, role="开发", targets=[Target(issue="I-03")], position="不接受", body="单栋楼试点能缓解，但上报量够不够现在不知道，不接受当作已解决。", reasons="未知"),
        Utterance(seq=14, role="主持人", targets=[Target(issue="I-03")], position="小结", body="7 条争议都已被回应，五个角色都发过言，讨论结束。", reasons="正常结束"),
    ]


EXPECTED_SPEAKERS = [
    ("主持人", "open"),
    ("开发", "2"),
    ("付费方代表", "3"),
    ("测试", "3"),
    ("用户代表", "3"),
    ("主持人", "1"),
    ("开发", "2"),
    ("产品经理", "3"),
    ("付费方代表", "4"),
    ("用户代表", "4"),
    ("主持人", "1"),
    ("产品经理", "2"),
    ("开发", "2"),
]

EXPECTED_STATUS = {
    "I-01": "采纳",
    "I-02": "采纳",
    "I-03": "待定",
    "I-04": "待定",
    "I-05": "采纳",
    "I-06": "采纳",
    "I-07": "采纳",
}


def scripted_m1_queue() -> list[dict[str, Any]]:
    """Deterministic DashScope-free queue for the study-room M1 path (idea → SPEC gate)."""
    queue: list[dict[str, Any]] = [
        {"user": IDEA.user, "problem": IDEA.problem, "needs_payer": True, "payer": "后勤", "missing": [], "ok": True},
        {"approach": IDEA.approach, "features": IDEA.features},
    ]
    for role in ("产品经理", "用户代表", "付费方代表", "开发", "测试"):
        qs = [q.model_dump() for q in QUESTIONS if q.role == role]
        queue.append({"questions": qs, "persona": "小林" if role == "用户代表" else ""})
    queue.append({"rows": [r.model_dump() for r in MERGE_ROWS], "notes": ""})
    for u in utterances():
        if u.role == "主持人":
            queue.append({"body": u.body, "mention": u.mention, "announce_finish": u.position == "小结"})
        else:
            queue.append({"questions": [], "utterance": u.model_dump()})
    queue.append(
        {
            "elevator": "给期末找不到座位的本科生看各层剩余座位",
            "nabcd": {"N": "找不到座位", "A": "上报查看", "B": "少白跑", "C": "群聊", "D": "张贴二维码"},
            "do": [{"name": "查看座位", "sources": ["初步做法", "I-02"]}],
            "dont": [{"name": "门禁接入", "sources": ["I-01"]}],
            "implementation": "小程序+上报",
            "features": [
                {"name": "查看剩余座位", "sources": ["初步做法", "I-02"], "points": 5},
                {"name": "上报座位", "sources": ["初步做法", "I-06"], "points": 5},
                {"name": "收藏教室", "sources": ["初步做法"], "points": 3},
            ],
            "risks": [
                {"code": "I-03", "verification": "一栋楼试点两周看上报条数", "fallback": "固定时段提醒"},
                {"code": "I-04", "verification": "对比群聊响应", "fallback": "保留待定"},
            ],
            "estimate_total": 13,
            "capacity": 40,
            "chapters": ["电梯演讲", "NABCD", "做什么", "不做什么", "大致怎么实现", "功能清单", "风险与待定", "估算"],
        }
    )
    for dim in ("用户价值", "可行性", "可测性", "竞争力"):
        queue.append({"reviewer": dim, "dimension": dim, "score": 4, "opinions": [{"text": "可进入规格", "kind": "验证类", "blocking": False}]})
    queue.append(
        {
            "users": [{"name": "小林"}],
            "scenarios": [{"code": "S1", "text": "期末找座位"}],
            "features": [
                {
                    "code": "F1",
                    "kind": "功能",
                    "title": "按楼层查看剩余座位",
                    "story": "作为学生我想查看剩余座位",
                    "scenario": "S1",
                    "priority": "P0",
                    "impact": "没有则无法使用",
                    "acceptance": ["能看到座位数和上报时间"],
                    "manual": [False],
                    "sources": ["初步做法", "I-02", "I-05"],
                },
                {
                    "code": "F2",
                    "kind": "功能",
                    "title": "上报剩余座位",
                    "story": "作为到场学生我要上报",
                    "scenario": "S1",
                    "priority": "P0",
                    "impact": "没有则数据为空",
                    "acceptance": ["同一账号 10 分钟内第二次上报被拒绝"],
                    "manual": [False],
                    "sources": ["初步做法", "I-06"],
                },
                {
                    "code": "F3",
                    "kind": "功能",
                    "title": "收藏教室",
                    "story": "收藏后置顶",
                    "scenario": "S1",
                    "priority": "P1",
                    "impact": "体验",
                    "acceptance": ["收藏后下次打开置顶"],
                    "manual": [True],
                    "sources": ["初步做法"],
                },
            ],
            "out_of_scope": [{"code": "I-01", "title": "门禁数据接入"}, {"code": "I-07", "title": "多栋楼"}],
            "nonfunc": [],
            "open_questions": [{"code": "I-03", "text": "上报量", "verification": "试点"}, {"code": "I-04", "text": "相对群聊"}],
            "review_followup": [
                {"code": "R-01", "text": "可进入规格", "result": "写入第4章"},
                {"code": "R-02", "text": "可进入规格", "result": "写入第4章"},
                {"code": "R-03", "text": "可进入规格", "result": "写入第4章"},
                {"code": "R-04", "text": "可进入规格", "result": "写入第4章"},
            ],
            "chapters": ["用户与场景", "功能", "非功能需求", "还没定的问题", "附录"],
        }
    )
    return queue
