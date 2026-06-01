"""成分贡献诊断：聚合 + 踢出规则（纯离线）。"""

import unittest

import pandas as pd

from backtest_agent_v1 import pool_diagnosis as pdg


def _g(rets, reasons, t1s, holds):
    return pd.DataFrame({
        "代码": ["688981"] * len(rets), "名称": ["x"] * len(rets),
        "收益率%": rets, "退出原因": reasons, "曾达第一目标": t1s, "持仓天数": holds,
    })


class TestAgg(unittest.TestCase):
    def test_agg_symbol(self):
        g = _g([10, -5, 8], ["第二目标", "止损", "持有到期"], ["是", "否", "是"], [5, 2, 7])
        r = pdg._agg_symbol("688981", "x", g)
        self.assertEqual(r["交易次数"], 3)
        self.assertAlmostEqual(r["总收益贡献"], 0.13, places=6)
        self.assertAlmostEqual(r["胜率"], 2 / 3, places=6)
        self.assertEqual(r["止损次数"], 1)
        self.assertAlmostEqual(r["止损占比"], 1 / 3, places=6)
        self.assertEqual(r["第一目标达成次数"], 2)
        self.assertEqual(r["第二目标达成次数"], 1)
        self.assertAlmostEqual(r["最大单笔盈利"], 0.10, places=6)
        self.assertAlmostEqual(r["最大单笔亏损"], -0.05, places=6)


class TestEject(unittest.TestCase):
    def _row(self, **kw):
        base = {"交易次数": 1, "总收益贡献": 0.05, "胜率": 0.6, "止损占比": 0.0,
                "平均单笔收益": 0.05, "最大单笔亏损": -0.02}
        base.update(kw)
        return base

    def test_clean_no_eject(self):
        hits = pdg._eject_conditions(self._row(), contrib_rank=1, n_total=10, median_trades=2)
        self.assertEqual(hits, [])

    def test_cond1_neg_contrib(self):
        hits = pdg._eject_conditions(self._row(交易次数=3, 总收益贡献=-0.05),
                                     contrib_rank=1, n_total=10, median_trades=2)
        self.assertIn("交易≥3且总贡献为负", hits)

    def test_cond_winrate_stop_avg_maxloss(self):
        r = self._row(胜率=0.30, 止损占比=0.5, 平均单笔收益=-0.02, 最大单笔亏损=-0.08)
        hits = pdg._eject_conditions(r, contrib_rank=1, n_total=10, median_trades=99)
        self.assertIn("胜率<35%", hits)
        self.assertIn("止损占比>40%", hits)
        self.assertIn("平均单笔<-1%", hits)
        self.assertIn("最大单笔亏损≤-8%", hits)

    def test_cond6_many_trades_low_rank(self):
        # 交易次数≥中位数 且 排名在后 1/3
        r = self._row(交易次数=5)
        hits = pdg._eject_conditions(r, contrib_rank=9, n_total=9, median_trades=3)
        self.assertIn("入选较多但贡献排名靠后", hits)

    def test_eject_threshold_is_two(self):
        self.assertEqual(pdg.EJECT_NEEDED, 2)


class TestComposite(unittest.TestCase):
    def test_dominant_scores_higher(self):
        rows = [{"代码": "A", "总收益贡献": 0.2, "胜率": 0.6, "盈亏比": 3.0,
                 "平均单笔收益": 0.05, "止损占比": 0.1, "最大单笔亏损": -0.03},
                {"代码": "B", "总收益贡献": -0.1, "胜率": 0.2, "盈亏比": 0.5,
                 "平均单笔收益": -0.03, "止损占比": 0.6, "最大单笔亏损": -0.08}]
        s = pdg._composite(rows)
        self.assertGreater(s["A"], s["B"])


if __name__ == "__main__":
    unittest.main()
