"""候选股观察计划：参考位计算（纯离线）。"""

import unittest

from backtest_agent_v1 import observation_plan as op


class TestLevels(unittest.TestCase):
    def test_levels_basic(self):
        lv = op._levels({"close": 100.0, "ma20": 95.0, "high_recent": 110.0, "pct_5d": 0.06})
        self.assertFalse(lv["数据不足"])
        self.assertEqual(lv["观察位"], 100.0)
        self.assertEqual(lv["低吸位"], (97.0, 98.0))        # -3% ~ -2%
        self.assertEqual(lv["突破位"], 110.0)                # 近20日高点
        self.assertEqual(lv["止损参考位"], 95.0)             # max(MA20, -8%)
        self.assertEqual(lv["第一目标位"], (108.0, 110.0))   # +8% ~ +10%
        self.assertEqual(lv["第二目标位"], (115.0, 120.0))   # +15% ~ +20%
        self.assertFalse(lv["high_risk"])

    def test_stop_uses_minus8_when_ma20_lower(self):
        lv = op._levels({"close": 100.0, "ma20": 80.0, "high_recent": 100.0, "pct_5d": 0.05})
        self.assertEqual(lv["止损参考位"], 92.0)  # MA20=80 < -8%=92 → 取 92

    def test_high_risk_surge(self):
        lv = op._levels({"close": 100.0, "ma20": 99.0, "high_recent": 105.0, "pct_5d": 0.25})
        self.assertTrue(lv["high_risk"])  # 近5日≥20%

    def test_high_risk_far_from_ma20(self):
        lv = op._levels({"close": 100.0, "ma20": 80.0, "high_recent": 100.0, "pct_5d": 0.05})
        self.assertTrue(lv["high_risk"])  # 高出 MA20 25% ≥15%

    def test_insufficient(self):
        self.assertTrue(op._levels({"close": None, "ma20": 95.0})["数据不足"])
        self.assertTrue(op._levels({"close": 100.0, "ma20": None})["数据不足"])


if __name__ == "__main__":
    unittest.main()
