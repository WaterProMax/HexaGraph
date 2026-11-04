import unittest

from langgraph_demo import graph


class LeaveGraphTests(unittest.TestCase):
    def test_valid_short_leave_is_approved(self):
        result = graph.invoke({
            "name": "小明",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "days": 2,
            "reason": "生病",
        })

        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "approved")

    def test_valid_long_leave_waits_for_review(self):
        result = graph.invoke({
            "name": "小明",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
            "days": 4,
            "reason": "生病",
        })

        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["message"], "等待老师审批")

    def test_valid_days_is_absent(self):
        result = graph.invoke({
            "name":"小明",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "days":"",
            "reason": "生病",
        })

        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["message"], "缺少必填信息：days")

    def test_valid_start_date_is_late_end_date(self):
        result = graph.invoke({
            "name":"小明",
            "start_date": "2026-11-03",
            "end_date": "2026-11-01",
            "days":2,
            "reason": "生病",
        })

        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["message"], "开始日期不能晚于结束日期")

    def test_valid_date_is_not_valid(self):
        result = graph.invoke({
            "name":"小明",
            "start_date": "2026-02-30",
            "end_date": "2026-03-02",
            "days":2,
            "reason": "生病",
        })

        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["message"], "日期无效或格式不正确，请使用 YYYY-MM-DD")

    def test_days_must_be_positive_integer(self):
        for days in (0, -1, "2", True):
            with self.subTest(days=days):
                result = graph.invoke({
                    "name": "小明",
                    "start_date": "2026-11-01",
                    "end_date": "2026-11-03",
                    "days": days,
                    "reason": "生病",
                })

                self.assertFalse(result["valid"])
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["message"], "请假天数必须是正整数")

if __name__ == "__main__":
    unittest.main()
