"""模型层具体策略：多因子选股（research-only）。

在 as_of 这天对一池 DataBundle 逐只算因子 → 横截面 z-score → 加权综合分 → 排名 → 取 top_n，
并给出 4 档研究分级。只用 date <= as_of 的数据（防前视）。绝不输出买卖指令。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import factors
from .base import ScreenResult, Strategy

DEFAULT_WEIGHTS = {"momentum": 1.0, "ma_bull": 1.0, "vol": 1.0}
MIN_BARS = 60


class MultiFactorStrategy(Strategy):
    name = "multi_factor"

    def __init__(self, weights: Optional[Dict[str, float]] = None,
                 factor_list=None, min_bars: int = MIN_BARS):
        self.weights = weights or DEFAULT_WEIGHTS
        self.factors = factor_list or factors.DEFAULT_FACTORS
        self.min_bars = min_bars

    def grade(self, flags: Dict[str, bool]) -> str:
        deep, surge = flags.get("deep_drop_20d"), flags.get("surge_60d")
        if deep and surge:
            return "高风险"
        if deep:
            return "暂不参与"
        if surge:
            return "谨慎关注"
        return "观察"

    def select(self, bundles: Dict[str, Any], as_of: str, top_n: int = 20) -> ScreenResult:
        raw: Dict[str, Dict[str, Optional[float]]] = {}
        flags_map: Dict[str, Dict[str, bool]] = {}
        bars_map: Dict[str, int] = {}
        insufficient: List[Dict] = []

        for sym, b in bundles.items():
            sl = factors.slice_until(getattr(b, "history", None), as_of)
            bars = 0 if sl is None or sl.empty else len(sl)
            bars_map[sym] = bars
            if bars < self.min_bars:
                insufficient.append({"symbol": sym, "name": getattr(b, "name", ""),
                                     "bars": bars, "reason": "历史K线不足，不足以判断"})
                continue
            raw[sym] = factors.compute_all(sl, self.factors)
            flags_map[sym] = factors.warning_flags(sl)

        z_by_factor = {k: factors.zscore({s: raw[s].get(k) for s in raw})
                       for k in factors.FACTOR_KEYS}

        ranked: List[Dict] = []
        for sym in raw:
            z = {k: z_by_factor[k].get(sym, 0.0) for k in factors.FACTOR_KEYS}
            comp = sum(self.weights.get(k, 0.0) * z.get(k, 0.0) for k in factors.FACTOR_KEYS)
            flags = flags_map.get(sym, {})
            ranked.append({
                "symbol": sym, "name": getattr(bundles[sym], "name", ""),
                "composite": round(comp, 4),
                "factors": {k: (None if v is None else round(float(v), 4)) for k, v in raw[sym].items()},
                "z": {k: round(v, 4) for k, v in z.items()},
                "grade": self.grade(flags),
                "warnings": [k for k, on in flags.items() if on],
                "bars": bars_map[sym],
            })
        ranked.sort(key=lambda r: r["composite"], reverse=True)
        for i, r in enumerate(ranked, 1):
            r["rank"] = i

        return ScreenResult(
            as_of=as_of, ranked=ranked,
            selected=[r["symbol"] for r in ranked[:top_n]],
            insufficient=insufficient, weights=dict(self.weights),
        )
