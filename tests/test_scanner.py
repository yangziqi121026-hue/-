"""模型A 选股逻辑测试（纯离线，不联网）。"""

import unittest

from backtest_agent_v1 import risk_plan, selection_models


def _metrics(**kw):
    base = {"symbol": "000001", "name": "测试", "is_st": False, "delisting_risk": False,
            "insufficient": False, "pct_5d": 0.10, "amount_today": 5e8, "vol_ratio": 2.0,
            "above_ma5": True, "above_ma10": True, "above_ma20": True,
            "turnover_rate": 5.0, "board_strong": None, "close": 10.0, "high_recent": 10.0}
    base.update(kw)
    return base


class TestModelA(unittest.TestCase):
    def test_strict_pass(self):
        v = selection_models.evaluate_model_a(_metrics(), mode="strict")
        self.assertTrue(v.passed)
        self.assertTrue(any("近5日涨幅" in r for r in v.reasons))

    def test_strict_fail_on_low_amount(self):
        v = selection_models.evaluate_model_a(_metrics(amount_today=2e8), mode="strict")
        self.assertFalse(v.passed)  # 2亿 ≤ 3亿

    def test_st_rejected(self):
        v = selection_models.evaluate_model_a(_metrics(is_st=True, name="ST测试"), mode="loose")
        self.assertFalse(v.passed)
        self.assertTrue(any("ST" in f for f in v.fails))

    def test_delisting_rejected(self):
        v = selection_models.evaluate_model_a(_metrics(delisting_risk=True), mode="loose")
        self.assertFalse(v.passed)

    def test_loose_ma20_not_hard(self):
        # 未站上 MA20，loose 仍可入选（MA20 仅评分）
        v = selection_models.evaluate_model_a(
            _metrics(above_ma20=False, pct_5d=0.06, amount_today=1.5e8, vol_ratio=1.2), mode="loose")
        self.assertTrue(v.passed)

    def test_strict_ma20_is_hard(self):
        v = selection_models.evaluate_model_a(_metrics(above_ma20=False), mode="strict")
        self.assertFalse(v.passed)  # strict 必须站上 MA20

    def test_loose_thresholds(self):
        # 近5日 6% > 5%、成交额 1.5亿 > 1亿、量比 1.2 > 1.1 → 入选
        v = selection_models.evaluate_model_a(
            _metrics(pct_5d=0.06, amount_today=1.5e8, vol_ratio=1.2), mode="loose")
        self.assertTrue(v.passed)

    def test_insufficient(self):
        v = selection_models.evaluate_model_a({"symbol": "x", "insufficient": True}, mode="loose")
        self.assertFalse(v.passed)

    def test_board_neutral_when_missing(self):
        # 板块 None：strict 下不因板块被否（仅按中性记 missing）
        v = selection_models.evaluate_model_a(_metrics(board_strong=None), mode="strict")
        self.assertTrue(v.passed)
        self.assertTrue(any("板块" in mssg for mssg in v.missing))

    def test_score_monotonic_in_pct(self):
        lo = selection_models._score(_metrics(pct_5d=0.06), "loose")
        hi = selection_models._score(_metrics(pct_5d=0.20), "loose")
        self.assertGreater(hi, lo)


class TestRiskPlan(unittest.TestCase):
    def test_surge_note(self):
        notes = risk_plan.build_risk_notes(_metrics(pct_5d=0.25))
        self.assertTrue(any("追高" in n for n in notes))

    def test_general_text_no_trade_words(self):
        txt = risk_plan.general_risk_text("strong", "loose")
        for w in ("止损位", "止盈位", "目标买价", "建议买入", "满仓"):
            self.assertNotIn(w, txt)


if __name__ == "__main__":
    unittest.main()
