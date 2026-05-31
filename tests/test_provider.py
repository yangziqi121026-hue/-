"""data 层 provider 测试（离线，不联网）。"""

import unittest

import config
from data import AkshareDataSource


class TestProvider(unittest.TestCase):
    def setUp(self):
        self.ds = AkshareDataSource()

    def test_readonly_guard(self):
        # 构造即自检：只读约束必须成立
        config.assert_readonly()
        self.assertTrue(config.ONLY_READONLY)
        self.assertFalse(config.ENABLE_TRADING)
        self.assertFalse(config.ENABLE_LIVE)

    def test_validate_symbol(self):
        self.assertTrue(self.ds.validate_symbol("600519"))
        self.assertTrue(self.ds.validate_symbol("000001"))
        self.assertFalse(self.ds.validate_symbol("838000"))  # 北交所
        self.assertFalse(self.ds.validate_symbol("abc"))

    def test_resolve_universe_codestring(self):
        u = self.ds.resolve_universe("600519,000858,838000,300750")
        self.assertEqual(u["codes"], ["600519", "000858", "300750"])
        self.assertFalse(u["is_mock"])

    def test_normalize_sina_turnover_decimal(self):
        # 新浪源：turnover 小数 ×100 → turnover_rate%；amount 直接保留
        import pandas as pd
        sina = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"],
            "open": [10, 11], "high": [11, 12], "low": [9, 10], "close": [10.5, 11.5],
            "volume": [1000, 2000], "amount": [1.0e7, 2.0e7], "turnover": [0.012, 0.034],
        })
        out = AkshareDataSource._normalize(sina)
        self.assertIn("turnover_rate", out.columns)
        self.assertAlmostEqual(float(out["turnover_rate"].iloc[0]), 1.2, places=6)
        self.assertAlmostEqual(float(out["turnover_rate"].iloc[1]), 3.4, places=6)
        self.assertAlmostEqual(float(out["amount"].iloc[0]), 1.0e7, places=2)

    def test_normalize_em_turnover_percent_unchanged(self):
        # 东财源「换手率」已是百分比，重命名为 turnover_rate 后不应再 ×100
        import pandas as pd
        em = pd.DataFrame({
            "日期": ["2024-01-02"], "开盘": [10], "最高": [11], "最低": [9], "收盘": [10.5],
            "成交量": [1000], "成交额": [1.0e7], "换手率": [1.2],
        })
        out = AkshareDataSource._normalize(em)
        self.assertAlmostEqual(float(out["turnover_rate"].iloc[0]), 1.2, places=6)

    def test_mock_history_offline(self):
        h = self.ds._mock_history("600519", "2024-01-01", "2024-06-30")
        self.assertFalse(h.empty)
        self.assertTrue(h.attrs.get("is_mock"))
        for c in ("date", "open", "high", "low", "close", "volume"):
            self.assertIn(c, h.columns)


if __name__ == "__main__":
    unittest.main()
