"""V2-2 选股回测：交易模拟 + 指标（纯离线，不联网）。"""

import unittest

import pandas as pd

from backtest_agent_v1 import selection_backtest as sb


def _df(bars):
    """bars: list of (date, open, high, low, close, ma20)。"""
    return pd.DataFrame([
        {"date": d, "open": o, "high": h, "low": lo, "close": c, "ma20": m}
        for (d, o, h, lo, c, m) in bars
    ])


class TestSimulateTrade(unittest.TestCase):
    def test_stop_loss(self):
        df = _df([("d0", 100, 101, 99, 100, 90),
                  ("d1", 100, 102, 94, 96, 90)])  # low 94 ≤ 95 触发止损
        t = sb._simulate_trade(df, 0, 10)
        self.assertEqual(t.exit_reason, "止损")
        self.assertAlmostEqual(t.exit_price, 95.0, places=4)
        self.assertEqual(t.hold_days, 2)

    def test_second_target(self):
        df = _df([("d0", 100, 101, 99, 100, 90),
                  ("d1", 100, 116, 100, 114, 95)])  # high 116 ≥ 115
        t = sb._simulate_trade(df, 0, 10)
        self.assertEqual(t.exit_reason, "第二目标")
        self.assertAlmostEqual(t.exit_price, 115.0, places=4)
        self.assertTrue(t.target1_hit)

    def test_break_ma20(self):
        df = _df([("d0", 100, 101, 99, 100, 98),
                  ("d1", 100, 101, 98, 97, 98)])  # close 97 < ma20 98
        t = sb._simulate_trade(df, 0, 10)
        self.assertEqual(t.exit_reason, "跌破MA20")
        self.assertAlmostEqual(t.exit_price, 97.0, places=4)

    def test_time_expiry_with_target1(self):
        df = _df([("d0", 100, 109, 99, 105, 90)])  # high 109 ≥ 108 里程碑；无其它触发
        t = sb._simulate_trade(df, 0, 1)
        self.assertEqual(t.exit_reason, "持有到期")
        self.assertAlmostEqual(t.exit_price, 105.0, places=4)
        self.assertTrue(t.target1_hit)
        self.assertEqual(t.hold_days, 1)

    def test_stop_priority_over_target(self):
        # 同日既破止损又触第二目标 → 保守按止损
        df = _df([("d0", 100, 116, 94, 100, 90)])
        t = sb._simulate_trade(df, 0, 10)
        self.assertEqual(t.exit_reason, "止损")


def _trade(ret, reason, t1=False, hold=5):
    return sb.Trade("X", "x", "s", "e", 100.0, "x", 100 * (1 + ret),
                    round(ret, 6), 1000 * ret, hold, reason, t1)


class TestSummary(unittest.TestCase):
    def test_counts_and_ratios(self):
        trades = [
            _trade(0.15, "第二目标", t1=True),
            _trade(0.08, "持有到期", t1=True),
            _trade(-0.05, "止损"),
            _trade(-0.05, "止损"),
        ]
        eq = [("d0", 100000.0), ("d1", 101000.0), ("d2", 99000.0), ("d3", 104600.0)]
        s = sb._compute_summary(trades, eq, 100000.0, "6m")
        self.assertEqual(s["交易次数"], 4)
        self.assertEqual(s["止损次数"], 2)
        self.assertEqual(s["第二目标达成次数"], 1)
        self.assertEqual(s["第一目标达成次数"], 2)
        self.assertEqual(s["失败案例数量"], 2)
        self.assertAlmostEqual(s["胜率"], 0.5, places=6)
        # 盈亏比 = 平均盈利 / |平均亏损| = 0.115 / 0.05 = 2.3
        self.assertAlmostEqual(s["盈亏比"], 0.115 / 0.05, places=4)

    def test_empty(self):
        s = sb._compute_summary([], [], 100000.0, "6m")
        self.assertEqual(s["交易次数"], 0)
        self.assertEqual(s["止损次数"], 0)


if __name__ == "__main__":
    unittest.main()
