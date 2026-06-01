"""股票池对比：解析 / 归属 / 综合分（纯离线）。"""

import unittest

from backtest_agent_v1 import pool_compare as pc
from backtest_agent_v1 import stock_pools as sp


class TestParse(unittest.TestCase):
    def test_parse_pct(self):
        self.assertAlmostEqual(pc._parse_val("2.55%"), 0.0255, places=6)
        self.assertAlmostEqual(pc._parse_val("-7.63%"), -0.0763, places=6)

    def test_parse_num_and_na(self):
        self.assertEqual(pc._parse_val("3.14"), 3.14)
        self.assertEqual(pc._parse_val("9"), 9.0)
        self.assertIsNone(pc._parse_val("不足以判断"))
        self.assertIsNone(pc._parse_val(""))


class TestIdentify(unittest.TestCase):
    def test_original_10(self):
        traded = pc.ORIGINAL_10[:4]
        self.assertEqual(pc.identify_pool(traded, 10), "原10只池")

    def test_tech_30_by_exclusive(self):
        # 300454 深信服只在 tech_30（被 v2 踢出，故不在 tech_30_v2，也不在 ai_robot）
        self.assertIn("300454", sp.get_pool("tech_30"))
        self.assertNotIn("300454", sp.get_pool("tech_30_v2"))
        self.assertEqual(pc.identify_pool(["300454"], 30), "tech_30")

    def test_ai_robot_by_exclusive(self):
        # 单标的因 tech_30_v2 重叠已不唯一；用「ai_robot 独有组合」消歧：
        # 688008 在 ai_robot+tech_30(非v2)，688256 在 ai_robot+v2(非tech_30) → 仅 ai_robot 同时含两者
        self.assertEqual(pc.identify_pool(["688008", "688256"], 30), "ai_robot_30")

    def test_core_30_by_exclusive(self):
        self.assertEqual(pc.identify_pool(["600519"], 30), "core_30")  # 茅台

    def test_unknown_size(self):
        self.assertTrue(pc.identify_pool(["999999"], 7).startswith("自定义"))


class TestComposite(unittest.TestCase):
    def _row(self, pool, retdd, pl, ann, win, mdd):
        return {"股票池": pool, "数据状态": "已回测@x",
                "收益/回撤比": retdd, "盈亏比": pl, "年化收益率": ann,
                "胜率": win, "最大回撤": mdd}

    def test_best_is_dominant(self):
        rows = [self._row("A", 2.0, 3.0, 0.10, 0.5, -0.03),
                self._row("B", 0.5, 1.5, 0.05, 0.3, -0.10)]
        scores = pc._composite_scores(rows)
        self.assertGreater(scores["A"], scores["B"])

    def test_single_pool_zero(self):
        rows = [self._row("A", 2.0, 3.0, 0.10, 0.5, -0.03)]
        scores = pc._composite_scores(rows)
        self.assertEqual(scores["A"], 0.0)  # 单池无横截面，z=0


if __name__ == "__main__":
    unittest.main()
