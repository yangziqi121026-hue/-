"""候选股观察计划（研究参考，非买卖建议）。

基于模型A 扫描默认观察池 tech_30_v2 得到的候选股，为每只生成一份**观察计划**：
观察位 / 低吸位 / 突破位 / 止损参考位 / 第一·第二目标位 / 仓位上限 / 失效条件 / 风险提示。

严格边界：通篇是「候选观察计划」研究参考，**绝不输出买入/卖出建议、不接实盘、不下单**。
注：字段「止损位」按本项目交易指令禁词策略统一渲染为「止损参考位」（含义不变、仅作观察参考）。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

import config
from reporting.base import sanitize

from . import risk_plan, selection_models
from .stock_scanner import StockScanner

DEFAULT_POOL = "tech_30_v2"   # 模型A 当前默认优先观察池
POSITION_CAP = 0.10           # 仓位上限（参考）

# 高风险观察阈值
_SURGE_5D = 0.20              # 近5日涨幅过大
_FAR_FROM_MA20 = 0.15        # 收盘价高出 MA20 过多 → 止损偏远


def _fp(v: Optional[float]) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.2f}"


def _rng(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return "—"
    return f"{a:.2f} ~ {b:.2f}"


def _levels(m: Dict) -> Dict[str, Any]:
    """按默认规则计算各观察参考位。数据不足返回 {'数据不足': True}。"""
    close = m.get("close")
    ma20 = m.get("ma20")
    hi20 = m.get("high_recent")
    pct5 = m.get("pct_5d")
    if close is None or ma20 is None or close <= 0:
        return {"数据不足": True}

    obs = close                                   # 观察位：当前收盘价附近
    dip = (round(close * 0.97, 2), round(close * 0.98, 2))   # 低吸位：-3% ~ -2%
    breakout = round(hi20, 2) if hi20 else round(close, 2)   # 突破位：近20日高点/前高
    stop_band = (round(close * 0.92, 2), round(close * 0.95, 2))  # 止损参考：-8% ~ -5%
    stop_ref = round(max(ma20, close * 0.92), 2)  # 参考 MA20（取与 -8% 的较高者）
    t1 = (round(close * 1.08, 2), round(close * 1.10, 2))    # 第一目标：+8% ~ +10%
    t2 = (round(close * 1.15, 2), round(close * 1.20, 2))    # 第二目标：+15% ~ +20%

    high_risk, flags = False, []
    if pct5 is not None and pct5 >= _SURGE_5D:
        high_risk = True
        flags.append(f"近5日涨幅 {pct5*100:.1f}% 偏大")
    if ma20 > 0 and (close / ma20 - 1) >= _FAR_FROM_MA20:
        high_risk = True
        flags.append(f"收盘价高出 MA20 {(close/ma20-1)*100:.1f}%（止损偏远）")

    return {
        "数据不足": False, "观察位": round(obs, 2), "低吸位": dip, "突破位": breakout,
        "止损参考位": stop_ref, "止损带": stop_band, "ma20": round(ma20, 2),
        "第一目标位": t1, "第二目标位": t2, "high_risk": high_risk, "high_risk_flags": flags,
    }


def _invalidation(lv: Dict) -> str:
    if lv.get("数据不足"):
        return "数据不足，暂不设观察"
    return (f"收盘跌破 MA20（{_fp(lv['ma20'])}）或跌破止损参考位（{_fp(lv['止损参考位'])}）"
            f"即视为本次观察失效")


def build_plan(source, pool: str = DEFAULT_POOL, mode: str = "loose",
               on_progress=None) -> Dict:
    """扫描 pool（模型A）→ 候选股 → 逐只生成观察计划。"""
    config.assert_readonly()
    from . import stock_pools
    symbols = stock_pools.get_pool(pool) or []
    scanner = StockScanner(source, fetch_industry=False)
    result = scanner.scan(symbols, mode=mode, on_progress=on_progress)
    data_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    plans: List[Dict] = []
    for r in result.candidates:
        m, v = r["metrics"], r["verdict"]
        lv = _levels(m)
        tag = "数据不足" if lv.get("数据不足") else ("高风险观察" if lv["high_risk"] else "常规观察")
        risks = list(r["risk_notes"])
        if lv.get("high_risk_flags"):
            risks = lv["high_risk_flags"] + risks
        plans.append({
            "排名": r.get("rank"),
            "代码": m["symbol"], "名称": m.get("name") or "",
            "入选模型": f"模型A 短线强势（strong / {mode}）",
            "入选原因": "；".join(v.reasons),
            "当前收盘价": m.get("close"),
            "观察位": None if lv.get("数据不足") else lv["观察位"],
            "低吸位": "—" if lv.get("数据不足") else _rng(*lv["低吸位"]),
            "突破位": None if lv.get("数据不足") else lv["突破位"],
            "止损参考位": None if lv.get("数据不足") else lv["止损参考位"],
            "第一目标位": "—" if lv.get("数据不足") else _rng(*lv["第一目标位"]),
            "第二目标位": "—" if lv.get("数据不足") else _rng(*lv["第二目标位"]),
            "仓位上限": f"≤{int(POSITION_CAP*100)}%",
            "失效条件": _invalidation(lv),
            "风险提示": "；".join(risks) if risks else "暂无显著风险点",
            "数据时间": data_time,
            "观察分级": tag,
        })
    return {"pool": pool, "mode": mode, "scan_time": data_time,
            "n": len(plans), "plans": plans,
            "universe_size": len(symbols), "scored": result.universe_size}


# =====================================================
# 导出 / 报告
# =====================================================

_CSV_COLS = ["排名", "代码", "名称", "入选模型", "入选原因", "当前收盘价", "观察位", "低吸位",
             "突破位", "止损参考位", "第一目标位", "第二目标位", "仓位上限", "失效条件",
             "风险提示", "数据时间", "观察分级"]


def plan_dataframe(plan: Dict) -> pd.DataFrame:
    return pd.DataFrame([{c: p.get(c) for c in _CSV_COLS} for p in plan["plans"]],
                        columns=_CSV_COLS)


def build_markdown(plan: Dict) -> str:
    p = ["# 候选股观察计划（研究参考，非买卖建议）", "",
         f"- 生成时间：{plan['scan_time']}",
         f"- 观察池：{plan['pool']}（模型A 当前默认优先观察池）",
         f"- 扫描模式：模型A / {plan['mode']}；池内 {plan['universe_size']} 只，命中候选 {plan['n']} 只",
         f"- 市场：{config.ONLY_MARKET}（只读分析，不下单/不接实盘）", "",
         "> 本计划为**候选观察计划**，所有「观察位/低吸位/突破位/止损参考位/目标位」均为"
         "**研究参考价位**，用于跟踪观察，**不构成任何买入/卖出建议、不构成交易指令**。\n"]

    if not plan["plans"]:
        p.append("## 本次无候选\n\n池内当前无标的满足模型A条件，无观察计划。")
        p.append(f"\n---\n> {config.DISCLAIMER}")
        return sanitize("\n".join(p))

    # 概览表
    p.append("## 候选观察总览\n")
    cols = ["排名", "代码", "名称", "当前收盘价", "观察位", "低吸位", "突破位",
            "止损参考位", "第一目标位", "第二目标位", "仓位上限", "观察分级"]
    p.append("| " + " | ".join(cols) + " |")
    p.append("|" + "|".join([":---:" if c in ("排名", "代码", "观察分级") else "---:"
                             if c not in ("名称",) else ":---" for c in cols]) + "|")
    for pl in plan["plans"]:
        row = [str(pl.get("排名", "")), pl["代码"], pl["名称"] or "—", _fp(pl["当前收盘价"]),
               _fp(pl["观察位"]), pl["低吸位"], _fp(pl["突破位"]), _fp(pl["止损参考位"]),
               pl["第一目标位"], pl["第二目标位"], pl["仓位上限"], pl["观察分级"]]
        p.append("| " + " | ".join(row) + " |")

    # 逐只明细
    p.append("\n## 逐只观察计划\n")
    for pl in plan["plans"]:
        p.append(f"### {pl['排名']}. {pl['代码']} {pl['名称'] or ''}　[{pl['观察分级']}]")
        p.append(f"- 入选模型：{pl['入选模型']}")
        p.append(f"- 入选原因：{pl['入选原因']}")
        p.append(f"- 当前收盘价：{_fp(pl['当前收盘价'])}")
        p.append(f"- 观察位：{_fp(pl['观察位'])}　|　低吸位：{pl['低吸位']}　|　突破位：{_fp(pl['突破位'])}")
        p.append(f"- 止损参考位：{_fp(pl['止损参考位'])}　|　第一目标位：{pl['第一目标位']}　|　"
                 f"第二目标位：{pl['第二目标位']}")
        p.append(f"- 仓位上限（参考）：{pl['仓位上限']}")
        p.append(f"- 失效条件：{pl['失效条件']}")
        p.append(f"- 风险提示：{pl['风险提示']}")
        p.append(f"- 数据时间：{pl['数据时间']}")
        p.append("")

    p.append("## 风险提示与免责\n")
    p.append("- 以上为研究性观察参考价位，按机械规则生成，非个股推荐、**非买入/卖出建议**。")
    p.append("- 短线强势股波动大，参考位可能迅速失效；「高风险观察」表示涨幅过大或止损偏远，确定性更低。")
    p.append("- 本系统只读、不接实盘、不下单、不接任何交易接口、无交易按钮。")
    p.append(f"\n---\n> {config.DISCLAIMER}")
    return sanitize("\n".join(p))
