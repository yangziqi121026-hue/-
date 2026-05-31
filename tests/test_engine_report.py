"""回测引擎 + 报告层测试（离线）。"""

import math
import unittest

from backtest_agent_v1 import engine
from models import MultiFactorStrategy
from reporting import sanitize
from reporting.backtest_report import BacktestReport
from reporting.screen_report import ScreenReport
from tests.helpers import make_bundle


def _bundles():
    return {"AAA": make_bundle("AAA", [10 + i * 0.1 for i in range(70)], name="测试A"),
            "BBB": make_bundle("BBB", [10 + (i % 3) * 0.01 for i in range(70)], name="测试B")}


class TestEngine(unittest.TestCase):
    def test_run_and_metrics(self):
        b = _bundles()
        start, end = b["AAA"].history["date"].iloc[0], b["AAA"].history["date"].iloc[-1]
        strat = MultiFactorStrategy(min_bars=5)
        bt = engine.run_backtest(strat, b, start, end, top_n=1, freq="monthly")
        self.assertNotIn("error", bt)
        self.assertGreater(len(bt["equity"]), 2)
        self.assertGreater(bt["equity"][-1][1], 1.0)  # 选中持续上涨的 AAA
        sm = engine.summarize(bt["equity"], bt["period_returns"])
        for k in ("total_return", "annualized_return", "sharpe", "max_drawdown", "win_rate"):
            self.assertIn(k, sm)

    def test_cost_reduces_return(self):
        b = _bundles()
        start, end = b["AAA"].history["date"].iloc[0], b["AAA"].history["date"].iloc[-1]
        strat = MultiFactorStrategy(min_bars=5)
        wc = engine.run_backtest(strat, b, start, end, top_n=1, cost_enabled=True)
        nc = engine.run_backtest(strat, b, start, end, top_n=1, cost_enabled=False)
        self.assertLessEqual(wc["equity"][-1][1], nc["equity"][-1][1])

    def test_empty_window(self):
        bt = engine.run_backtest(MultiFactorStrategy(min_bars=5), _bundles(),
                                 "2099-01-01", "2099-12-31", top_n=1)
        self.assertIn("error", bt)


class TestReporting(unittest.TestCase):
    def test_sanitize_softens(self):
        out = sanitize("强烈推荐立即满仓，设置止损位")
        self.assertIn("已移除交易指令", out)
        self.assertNotIn("强烈推荐", out.replace("已移除交易指令：强烈推荐", ""))

    def test_sanitize_idempotent(self):
        once = sanitize("建议买入")
        self.assertEqual(once, sanitize(once))

    def test_screen_report_pillars(self):
        b = _bundles()
        as_of = b["AAA"].history["date"].iloc[-1]
        res = MultiFactorStrategy(min_bars=5).select(b, as_of, top_n=2)
        md = ScreenReport().build(res, {"data_source": "测试"})
        self.assertIn("数据来源", md)
        self.assertIn("生成时间", md)
        self.assertTrue("不构成" in md)
        for w in ("买入信号", "卖出信号", "满仓", "止损位"):
            self.assertNotIn(w, md)

    def test_backtest_report(self):
        b = _bundles()
        start, end = b["AAA"].history["date"].iloc[0], b["AAA"].history["date"].iloc[-1]
        bt = engine.run_backtest(MultiFactorStrategy(min_bars=5), b, start, end, top_n=1)
        sm = engine.summarize(bt["equity"], bt["period_returns"])
        md = BacktestReport().build({"bt": bt, "summary": sm}, {})
        self.assertIn("绩效指标", md)
        self.assertIn("不构成", md)


if __name__ == "__main__":
    unittest.main()
