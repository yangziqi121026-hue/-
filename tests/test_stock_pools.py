"""股票池管理测试（纯离线）。"""

import unittest

from backtest_agent_v1 import stock_pools as sp


class TestPools(unittest.TestCase):
    def test_pool_names(self):
        self.assertEqual(set(sp.list_pools()),
                         {"core_30", "tech_30", "tech_30_v2", "ai_robot_30",
                          "new_energy_30", "core_50"})

    def test_pool_sizes(self):
        self.assertEqual(len(sp.get_pool("core_30")), 30)
        self.assertEqual(len(sp.get_pool("tech_30")), 30)
        self.assertEqual(len(sp.get_pool("tech_30_v2")), 30)
        self.assertEqual(len(sp.get_pool("ai_robot_30")), 30)
        self.assertEqual(len(sp.get_pool("new_energy_30")), 30)
        self.assertEqual(len(sp.get_pool("core_50")), 50)

    def test_tech_30_v2_derivation(self):
        v2 = set(sp.get_pool("tech_30_v2"))
        tech = set(sp.get_pool("tech_30"))
        ejected = {"300454", "300502", "002049", "688036", "002371",
                   "603501", "300308", "000977", "300223", "688008", "603986"}
        # 踢出的 11 只不在 v2；原 tech_30 不被修改
        self.assertEqual(v2 & ejected, set())
        self.assertEqual(len(sp.get_pool("tech_30")), 30)
        # 19 只来自 tech_30 + 11 只池外
        self.assertEqual(len(v2 & tech), 19)
        self.assertEqual(len(v2 - tech), 11)

    def test_pools_are_6digit_and_unique(self):
        for name in sp.list_pools():
            codes = sp.get_pool(name)
            self.assertEqual(len(codes), len(set(codes)), f"{name} 有重复")
            for c in codes:
                self.assertRegex(c, r"^\d{6}$", f"{name} 含非法代码 {c}")

    def test_core_50_contains_core_30(self):
        self.assertTrue(set(sp.get_pool("core_30")).issubset(set(sp.get_pool("core_50"))))

    def test_get_pool_unknown(self):
        self.assertIsNone(sp.get_pool("nope"))


class TestResolve(unittest.TestCase):
    def test_symbols_only(self):
        codes, source, note = sp.resolve("600519,000858", None)
        self.assertEqual(codes, ["600519", "000858"])
        self.assertEqual(source, "symbols")

    def test_pool_only(self):
        codes, source, note = sp.resolve(None, "tech_30")
        self.assertEqual(len(codes), 30)
        self.assertTrue(source.startswith("pool:tech_30"))

    def test_symbols_priority_over_pool(self):
        # 同传 → 优先 symbols，note 提示忽略 pool
        codes, source, note = sp.resolve("600519", "core_50")
        self.assertEqual(codes, ["600519"])
        self.assertEqual(source, "symbols")
        self.assertIn("core_50", note)

    def test_none(self):
        codes, source, note = sp.resolve(None, None)
        self.assertEqual(codes, [])
        self.assertEqual(source, "none")

    def test_unknown_pool(self):
        codes, source, note = sp.resolve(None, "ghost")
        self.assertEqual(codes, [])
        self.assertIn("未知", note)


if __name__ == "__main__":
    unittest.main()
