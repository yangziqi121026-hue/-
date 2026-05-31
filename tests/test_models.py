"""模型层测试：因子 / 策略，含【防前视】关键测试。"""

import unittest

from models import MultiFactorStrategy
from models import factors
from tests.helpers import make_bundle, make_df


class TestAntiLookahead(unittest.TestCase):
    def test_factors_ignore_future(self):
        closes = [10 + i * 0.1 for i in range(80)]
        df_now = make_df(closes)
        as_of = df_now["date"].iloc[-1]
        df_future = make_df(closes + [closes[-1] * (1 + 0.1 * k) for k in range(1, 21)])
        f_now = factors.compute_all(df_now)
        f_sliced = factors.compute_all(factors.slice_until(df_future, as_of))
        self.assertEqual(f_now, f_sliced, "因子被未来K线污染（前视偏差）！")

    def test_strategy_ranking_ignores_future(self):
        a = [10 + i * 0.2 for i in range(80)]
        b = [10 + i * 0.05 for i in range(80)]
        as_of = make_df(a)["date"].iloc[-1]
        clean = {"AAA": make_bundle("AAA", a), "BBB": make_bundle("BBB", b)}
        fut = {"AAA": make_bundle("AAA", a),
               "BBB": make_bundle("BBB", b + [b[-1] * (1 + 0.2 * k) for k in range(1, 30)])}
        s = MultiFactorStrategy(min_bars=60)
        r1 = {x["symbol"]: x["composite"] for x in s.select(clean, as_of, top_n=2).ranked}
        r2 = {x["symbol"]: x["composite"] for x in s.select(fut, as_of, top_n=2).ranked}
        self.assertEqual(r1, r2, "排名被未来K线影响（前视偏差）！")


class TestStrategy(unittest.TestCase):
    def test_select_top_n_and_grades(self):
        bundles = {f"S{i}": make_bundle(f"S{i}", [10 + j * (0.01 * (i + 1)) for j in range(80)])
                   for i in range(4)}
        as_of = bundles["S0"].history["date"].iloc[-1]
        res = MultiFactorStrategy(min_bars=60).select(bundles, as_of, top_n=2)
        self.assertEqual(len(res.selected), 2)
        for r in res.ranked:
            self.assertIn(r["grade"], ("观察", "谨慎关注", "暂不参与", "高风险"))

    def test_insufficient_excluded(self):
        bundles = {"OK": make_bundle("OK", [10 + j * 0.2 for j in range(80)]),
                   "SHORT": make_bundle("SHORT", [10.0] * 20)}
        as_of = bundles["OK"].history["date"].iloc[-1]
        res = MultiFactorStrategy(min_bars=60).select(bundles, as_of, top_n=5)
        syms = {r["symbol"] for r in res.ranked}
        self.assertIn("OK", syms)
        self.assertNotIn("SHORT", syms)

    def test_grade_mapping(self):
        s = MultiFactorStrategy()
        self.assertEqual(s.grade({}), "观察")
        self.assertEqual(s.grade({"surge_60d": True}), "谨慎关注")
        self.assertEqual(s.grade({"deep_drop_20d": True}), "暂不参与")
        self.assertEqual(s.grade({"deep_drop_20d": True, "surge_60d": True}), "高风险")


if __name__ == "__main__":
    unittest.main()
