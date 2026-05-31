"""选股模型库——当前只实现【模型A：短线强势股模型】。

模型A 在 strict / loose 两套阈值下判定一只股票是否为短线强势候选，并给出：
- passed：是否入选
- reasons：满足的条件（入选理由）
- fails：未满足的条件（未入选原因）
- missing：数据不可用而按中性处理的项
- score：用于候选股排名的综合分

纯逻辑、不联网、不依赖具体数据源。输入是上游算好的 metrics dict。
**只做研究筛选，绝不输出买入/卖出建议或目标价。**
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODEL_A = "strong"          # 模型A 标识
MODES = ("strict", "loose")

# 阈值表（strict / loose）
_THRESH = {
    "strict": {"pct5d": 0.08, "amount": 3e8, "vol_mult": 1.5, "need_ma20": True},
    "loose": {"pct5d": 0.05, "amount": 1e8, "vol_mult": 1.1, "need_ma20": False},
}


@dataclass
class ModelVerdict:
    symbol: str
    passed: bool = False
    reasons: List[str] = field(default_factory=list)
    fails: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    score: float = 0.0


def _yi(v: Optional[float]) -> str:
    return "不足以判断" if v is None else f"{v / 1e8:.2f}亿"


def evaluate_model_a(metrics: Dict, mode: str = "loose") -> ModelVerdict:
    """判定单只股票是否为模型A短线强势候选。metrics 来自 stock_scanner._compute_metrics。"""
    mode = mode if mode in _THRESH else "loose"
    t = _THRESH[mode]
    v = ModelVerdict(symbol=metrics.get("symbol", ""))

    # 数据充分性
    if metrics.get("insufficient"):
        v.passed = False
        v.fails.append("历史K线不足，不足以判断")
        return v

    # 条件1：非ST、非退市风险
    if metrics.get("is_st") or metrics.get("delisting_risk"):
        v.fails.append("属于 ST / 退市风险标的（条件1不满足）")
        v.passed = False
        # ST/退市直接淘汰，仍计算其它项用于摘要，但不入选
    else:
        v.reasons.append("非ST、非退市风险")

    # 条件2：近5日涨幅
    pct5 = metrics.get("pct_5d")
    if pct5 is None:
        v.fails.append("近5日涨幅缺失")
    elif pct5 > t["pct5d"]:
        v.reasons.append(f"近5日涨幅 {pct5*100:.2f}% > {t['pct5d']*100:.0f}%")
    else:
        v.fails.append(f"近5日涨幅 {pct5*100:.2f}% ≤ {t['pct5d']*100:.0f}%")

    # 条件3：今日成交额
    amt = metrics.get("amount_today")
    if amt is None:
        v.fails.append("今日成交额缺失")
    elif amt > t["amount"]:
        v.reasons.append(f"今日成交额 {_yi(amt)} > {_yi(t['amount'])}")
    else:
        v.fails.append(f"今日成交额 {_yi(amt)} ≤ {_yi(t['amount'])}")

    # 条件4：放量
    vr = metrics.get("vol_ratio")
    if vr is None:
        v.fails.append("量比（今日量/5日均量）缺失")
    elif vr > t["vol_mult"]:
        v.reasons.append(f"今日成交量为5日均量 {vr:.2f} 倍 > {t['vol_mult']}倍")
    else:
        v.fails.append(f"今日成交量为5日均量 {vr:.2f} 倍 ≤ {t['vol_mult']}倍")

    # 条件5：均线多头站位
    a5, a10, a20 = metrics.get("above_ma5"), metrics.get("above_ma10"), metrics.get("above_ma20")
    if mode == "strict":
        if a5 and a10 and a20:
            v.reasons.append("收盘价站上 MA5/MA10/MA20")
        else:
            miss = [m for m, ok in (("MA5", a5), ("MA10", a10), ("MA20", a20)) if not ok]
            v.fails.append("未站上 " + "/".join(miss) if miss else "均线站位不足")
    else:  # loose：MA5、MA10 为硬条件，MA20 仅评分
        if a5 and a10:
            v.reasons.append("收盘价站上 MA5/MA10")
        else:
            miss = [m for m, ok in (("MA5", a5), ("MA10", a10)) if not ok]
            v.fails.append("未站上 " + "/".join(miss))
        if a20:
            v.reasons.append("（加分）收盘价亦站上 MA20")

    # 条件6：板块近3日强于市场（板块数据可用时）
    bs = metrics.get("board_strong")  # True/False/None(暂无)
    if bs is None:
        v.missing.append("板块数据暂无（按中性处理）")
    elif bs:
        v.reasons.append("所属板块近3日表现强于市场平均")
    else:
        if mode == "strict":
            v.fails.append("所属板块近3日未强于市场平均")
        else:
            v.missing.append("板块近3日未强于市场（loose 不作硬过滤）")

    # 换手率（取不到时中性）
    if metrics.get("turnover_rate") is None:
        v.missing.append("换手率暂无（按中性处理）")

    # 综合判定：除“缺失项”外的硬条件全部满足
    v.passed = (len(v.fails) == 0)
    v.score = _score(metrics, mode)
    return v


def _score(metrics: Dict, mode: str) -> float:
    """候选股排名用综合分（越高越强）。仅用于排序，不构成任何买卖建议。"""
    pct5 = metrics.get("pct_5d") or 0.0
    vr = metrics.get("vol_ratio") or 0.0
    amt = metrics.get("amount_today") or 0.0
    score = 0.0
    score += pct5 * 100 * 0.45                      # 近5日涨幅
    score += min(vr, 5.0) * 8.0 * 0.25              # 放量（封顶防异常）
    score += math.log10(max(amt, 1.0)) * 2.0 * 0.15  # 成交额（对数）
    ma_cnt = sum(1 for k in ("above_ma5", "above_ma10", "above_ma20") if metrics.get(k))
    score += ma_cnt * 3.0 * 0.10                    # 均线站位数
    tr = metrics.get("turnover_rate")
    if tr is not None:
        score += min(tr, 20.0) * 0.5 * 0.05         # 换手率（封顶）
    if metrics.get("board_strong"):
        score += 5.0
    return round(score, 4)
