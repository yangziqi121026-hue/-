"""失败案例复盘（基于已有回测交易明细，**不重跑回测、不改模型A、不改 selection_backtest**）。

读取某池（默认 tech_30_v2）最新一次回测的 trades CSV，对**亏损交易**做：
失败类型归类 / 失败股票排名 / 失败原因统计 / 改进观察建议。

只读历史复盘，不接实盘、不下单、不出买卖建议。改进建议为**研究性观察方向**，非交易指令。
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from reporting.base import sanitize

from . import pool_diagnosis

# 失败类型（9 类）
FAILURE_TYPES = ["假突破", "追高后回落", "放量不延续", "跌破MA20", "时间退出无效",
                 "止损触发", "数据异常", "期末平仓", "其他"]


def _to_f(v) -> Optional[float]:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def classify_failure(row: Dict, end_date: str, max_hold: int) -> str:
    """把一笔【亏损】交易归到 9 类之一（启发式，规则在报告中说明）。"""
    ret = _to_f(row.get("收益率%"))
    ep = _to_f(row.get("入场价"))
    xp = _to_f(row.get("出场价"))
    reason = str(row.get("退出原因", ""))
    t1 = str(row.get("曾达第一目标", "")) == "是"
    hold = int(_to_f(row.get("持仓天数")) or 0)
    exit_date = str(row.get("出场日", ""))

    if ep is None or xp is None or ep <= 0 or xp <= 0 or ret is None:
        return "数据异常"
    # 持有到期：区分回测边界强平 vs 趋势平淡
    if reason == "持有到期":
        if exit_date == end_date and hold < max_hold:
            return "期末平仓"
        return "时间退出无效"
    # 曾冲到第一目标(+8%)又回落成亏损
    if t1:
        return "追高后回落"
    if reason == "止损":
        return "假突破" if hold <= 2 else "止损触发"
    if reason == "跌破MA20":
        if hold <= 2:
            return "假突破"
        if hold <= 5:
            return "放量不延续"
        return "跌破MA20"
    return "其他"


def review(pool: str = "tech_30_v2") -> Dict:
    config.assert_readonly()
    loc = pool_diagnosis.find_pool_trades(pool)
    if loc is None:
        return {"pool": pool, "error": f"未找到 {pool} 的回测交易明细（请先跑回测）。",
                "losers": [], "type_counts": {}, "stock_rank": [], "reason_stats": {}, "advice": []}
    df = pool_diagnosis.load_trades(loc["trades_path"])
    if df.empty:
        return {"pool": pool, "error": "交易明细为空。", "losers": [],
                "type_counts": {}, "stock_rank": [], "reason_stats": {}, "advice": []}

    ret = pd.to_numeric(df["收益率%"], errors="coerce")
    n_total = len(df)
    end_date = str(df["出场日"].max())
    hold_exp = pd.to_numeric(df.loc[df["退出原因"] == "持有到期", "持仓天数"], errors="coerce")
    max_hold = int(hold_exp.max()) if len(hold_exp.dropna()) else 10

    losers: List[Dict] = []
    for _, r in df[ret < 0].iterrows():
        rd = r.to_dict()
        ftype = classify_failure(rd, end_date, max_hold)
        losers.append({
            "代码": rd.get("代码", ""), "名称": "" if pd.isna(rd.get("名称")) else str(rd.get("名称")),
            "入场日": rd.get("入场日", ""), "出场日": rd.get("出场日", ""),
            "入场价": _to_f(rd.get("入场价")), "出场价": _to_f(rd.get("出场价")),
            "收益率%": round(_to_f(rd.get("收益率%")) or 0, 2),
            "持仓天数": int(_to_f(rd.get("持仓天数")) or 0),
            "退出原因": str(rd.get("退出原因", "")),
            "曾达第一目标": str(rd.get("曾达第一目标", "")),
            "失败类型": ftype,
        })
    losers.sort(key=lambda x: x["收益率%"])  # 亏得最多在前

    # 失败类型归类计数
    type_counts = {t: 0 for t in FAILURE_TYPES}
    for x in losers:
        type_counts[x["失败类型"]] = type_counts.get(x["失败类型"], 0) + 1
    type_counts = {k: v for k, v in type_counts.items() if v > 0}

    # 失败股票排名（按亏损交易数 + 累计亏损）
    by_stock: Dict[str, Dict] = {}
    for x in losers:
        s = by_stock.setdefault(x["代码"], {"代码": x["代码"], "名称": x["名称"],
                                            "亏损交易数": 0, "累计亏损%": 0.0, "类型": {}})
        s["亏损交易数"] += 1
        s["累计亏损%"] += x["收益率%"]
        s["类型"][x["失败类型"]] = s["类型"].get(x["失败类型"], 0) + 1
    stock_rank = sorted(by_stock.values(), key=lambda s: (s["累计亏损%"], -s["亏损交易数"]))
    for s in stock_rank:
        s["累计亏损%"] = round(s["累计亏损%"], 2)
        s["主要类型"] = max(s["类型"], key=s["类型"].get) if s["类型"] else "—"

    # 失败原因统计（退出原因 + 失败类型 + 各类型平均亏损）
    reason_by_exit = df[ret < 0]["退出原因"].value_counts().to_dict()
    type_avg_loss = {}
    for t in type_counts:
        vals = [x["收益率%"] for x in losers if x["失败类型"] == t]
        type_avg_loss[t] = round(float(np.mean(vals)), 2) if vals else None

    advice = _build_advice(type_counts, len(losers))

    return {"pool": pool, "token": loc["token"], "trades_path": loc["trades_path"],
            "n_total": n_total, "n_loss": len(losers), "end_date": end_date, "max_hold": max_hold,
            "losers": losers, "type_counts": type_counts, "type_avg_loss": type_avg_loss,
            "stock_rank": stock_rank, "reason_by_exit": reason_by_exit, "advice": advice}


_ADVICE_MAP = {
    "假突破": "假突破占比偏高——可加严「突破确认」（如要求站稳数日/放量持续）后再纳入观察。",
    "追高后回落": "冲高回落较多——回避近5日涨幅过大的标的，或在接近第一目标时降低观察确定性预期。",
    "放量不延续": "放量后量能未延续——可加入「量能持续性」过滤，避免单日脉冲放量。",
    "跌破MA20": "破位较多——可把 MA20 作为更前置的过滤条件（入场即要求离 MA20 不过远）。",
    "时间退出无效": "持有到期多为平淡走势——可缩短持有窗口或加趋势强度过滤。",
    "止损触发": "止损触发偏多——入场时点可能偏晚，或止损过紧，可观察入场择时。",
    "期末平仓": "期末强制平仓属回测边界效应，非策略缺陷，统计时应单独区分、不计入策略失败。",
    "数据异常": "存在数据异常交易——建议核查数据源完整性，剔除异常样本后再评估。",
    "其他": "未归入明确类型，建议逐笔人工复核。",
}


def _build_advice(type_counts: Dict[str, int], n_loss: int) -> List[str]:
    if not type_counts:
        return ["无亏损交易，无需改进观察建议。"]
    out = []
    for t, c in sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True):
        pct = f"（{c} 笔，占亏损 {c/n_loss*100:.0f}%）" if n_loss else ""
        out.append(f"{t}{pct}：{_ADVICE_MAP.get(t, '建议人工复核。')}")
    return out


# =====================================================
# 导出 / 报告
# =====================================================

_CSV_COLS = ["代码", "名称", "入场日", "出场日", "入场价", "出场价", "收益率%",
             "持仓天数", "退出原因", "曾达第一目标", "失败类型"]


def losers_dataframe(rv: Dict) -> pd.DataFrame:
    return pd.DataFrame([{c: x.get(c) for c in _CSV_COLS} for x in rv.get("losers", [])],
                        columns=_CSV_COLS)


def build_markdown(rv: Dict) -> str:
    pool = rv.get("pool", "?")
    if rv.get("error"):
        return sanitize(f"# 失败案例复盘（{pool}）\n\n**{rv['error']}**\n\n---\n> {config.DISCLAIMER}")

    p = [f"# 失败案例复盘（{pool}）", "",
         f"- 复盘时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
         f"- 数据来源：{Path(rv['trades_path']).name}（已有回测交易明细，未重跑回测）",
         f"- 总交易 {rv['n_total']} 笔，其中**亏损 {rv['n_loss']} 笔**"
         f"（亏损率 {rv['n_loss']/rv['n_total']*100:.1f}%）", "",
         "> 本复盘仅对历史模拟亏损交易做归因统计；「改进观察建议」为研究性观察方向，"
         "**非买入/卖出建议、非交易指令**。\n"]

    # 失败类型归类
    p.append("## 失败类型归类\n")
    p.append("| 失败类型 | 笔数 | 占亏损% | 平均亏损% |")
    p.append("|:---|---:|---:|---:|")
    for t, c in sorted(rv["type_counts"].items(), key=lambda kv: kv[1], reverse=True):
        avg = rv["type_avg_loss"].get(t)
        p.append(f"| {t} | {c} | {c/rv['n_loss']*100:.0f}% | "
                 f"{'—' if avg is None else f'{avg:.2f}%'} |")

    # 失败原因统计（退出原因）
    p.append("\n## 失败原因统计（退出原因）\n")
    for k, v in sorted(rv["reason_by_exit"].items(), key=lambda kv: kv[1], reverse=True):
        p.append(f"- {k}：{v} 笔")

    # 失败股票排名
    p.append("\n## 失败股票排名（按累计亏损）\n")
    p.append("| 排名 | 代码 | 名称 | 亏损交易数 | 累计亏损% | 主要失败类型 |")
    p.append("|---:|:---|:---|---:|---:|:---|")
    for i, s in enumerate(rv["stock_rank"], 1):
        p.append(f"| {i} | {s['代码']} | {s['名称'] or '—'} | {s['亏损交易数']} "
                 f"| {s['累计亏损%']:.2f}% | {s['主要类型']} |")

    # 亏损交易列表
    p.append("\n## 亏损交易列表（按亏损幅度排序）\n")
    p.append("| 代码 | 名称 | 入场日 | 出场日 | 收益率% | 持仓天数 | 退出原因 | 失败类型 |")
    p.append("|:---|:---|:---|:---|---:|---:|:---|:---|")
    for x in rv["losers"]:
        p.append(f"| {x['代码']} | {x['名称'] or '—'} | {x['入场日']} | {x['出场日']} "
                 f"| {x['收益率%']:.2f}% | {x['持仓天数']} | {x['退出原因']} | {x['失败类型']} |")

    # 改进观察建议
    p.append("\n## 改进观察建议（研究方向，非交易指令）\n")
    for a in rv["advice"]:
        p.append(f"- {a}")

    p.append("\n## 失败类型判定规则（启发式）\n")
    p.append("- 数据异常：入场/出场价缺失或非正、收益率缺失。\n"
             "- 期末平仓：「持有到期」且出场日为回测末日且持仓<最大持有日（回测边界，非策略失败）。\n"
             "- 时间退出无效：「持有到期」且非期末强平的亏损。\n"
             "- 追高后回落：曾达第一目标(+8%)后仍以亏损收场。\n"
             "- 假突破：止损/破MA20 且持仓≤2日（入场即反转）。\n"
             "- 放量不延续：破MA20 且持仓 3–5 日（短期动能/量能未延续）。\n"
             "- 止损触发 / 跌破MA20：其余对应退出原因的亏损。")

    p.append("\n## 风险提示与免责\n")
    p.append("- 失败归因基于单段历史模拟样本，启发式分类可能有误差，仅供研究参考。")
    p.append("- 本系统只读、不接实盘、不下单、不接任何交易接口。")
    p.append(f"\n---\n> {config.DISCLAIMER}")
    return sanitize("\n".join(p))
