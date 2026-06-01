"""失败案例复盘：失败类型归类（纯离线）。"""

import unittest

from backtest_agent_v1 import failure_review as fr


def _row(ret=-3.0, ep=10.0, xp=9.7, reason="止损", t1="否", hold=3, exit_date="2026-03-01"):
    return {"收益率%": ret, "入场价": ep, "出场价": xp, "退出原因": reason,
            "曾达第一目标": t1, "持仓天数": hold, "出场日": exit_date}


class TestClassify(unittest.TestCase):
    END = "2026-06-01"

    def test_data_anomaly(self):
        self.assertEqual(fr.classify_failure(_row(ep=0), self.END, 10), "数据异常")
        self.assertEqual(fr.classify_failure(_row(xp=None), self.END, 10), "数据异常")

    def test_end_close(self):
        r = _row(reason="持有到期", hold=4, exit_date=self.END)
        self.assertEqual(fr.classify_failure(r, self.END, 10), "期末平仓")

    def test_time_exit_ineffective(self):
        r = _row(reason="持有到期", hold=10, exit_date="2026-03-01")
        self.assertEqual(fr.classify_failure(r, self.END, 10), "时间退出无效")

    def test_chase_high_fallback(self):
        r = _row(reason="止损", t1="是", hold=6)
        self.assertEqual(fr.classify_failure(r, self.END, 10), "追高后回落")

    def test_false_breakout_stop(self):
        self.assertEqual(fr.classify_failure(_row(reason="止损", hold=1), self.END, 10), "假突破")

    def test_false_breakout_ma20(self):
        self.assertEqual(fr.classify_failure(_row(reason="跌破MA20", hold=2), self.END, 10), "假突破")

    def test_stop_triggered(self):
        self.assertEqual(fr.classify_failure(_row(reason="止损", hold=5), self.END, 10), "止损触发")

    def test_volume_fade(self):
        self.assertEqual(fr.classify_failure(_row(reason="跌破MA20", hold=4), self.END, 10), "放量不延续")

    def test_break_ma20(self):
        self.assertEqual(fr.classify_failure(_row(reason="跌破MA20", hold=8), self.END, 10), "跌破MA20")


if __name__ == "__main__":
    unittest.main()
