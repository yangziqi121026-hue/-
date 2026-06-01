"""股票池横向对比（只汇总已有回测结果，**绝不重新跑回测、不改模型A、不改回测逻辑**）。

读取 selection_backtest_exports 下已生成的 summary CSV，自动归属到对应股票池，
汇总成一张横向对比表，并数据驱动地给出「当前最佳适配池」。

只读分析，不接实盘、不下单、不出买卖建议。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from reporting.base import sanitize

from . import stock_pools

# 原始 10 只示例池（不在 stock_pools 预设里，单独登记用于归属）
ORIGINAL_10 = ["300308", "688981", "002463", "601138", "300502",
               "300750", "002230", "300015", "002236", "603986"]

# 归属候选：预设池 + 原10只
_ALL_POOLS: Dict[str, List[str]] = {**stock_pools.POOLS, "原10只池": ORIGINAL_10}

_SB_EXPORTS = config.output_dir("selection_backtest", "exports")
_SB_REPORTS = config.output_dir("selection_backtest", "reports")

# 用户关心的对比池顺序（无数据则标「尚未回测」）
REQUESTED_POOLS = ["tech_30", "ai_robot_30", "core_30", "new_energy_30", "原10只池"]


# =====================================================
# 读取 + 归属
# =====================================================

def _parse_val(s) -> Optional[float]:
    s = str(s).strip()
    if s in ("不足以判断", "", "nan", "None"):
        return None
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _token(p: Path) -> str:
    m = re.search(r"(\d{8}_\d{6})", p.name)
    return m.group(1) if m else ""


def _read_summary(path: Path) -> Dict[str, Optional[float]]:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return {}
    return {str(r["指标"]): _parse_val(r["数值"]) for _, r in df.iterrows()
            if "指标" in df.columns and "数值" in df.columns}


def _universe_size(token: str) -> Optional[int]:
    md = _SB_REPORTS / f"modelA_selection_backtest_{token}.md"
    if md.exists():
        m = re.search(r"股票池数量[:：]\s*(\d+)", md.read_text(encoding="utf-8"))
        if m:
            return int(m.group(1))
    return None


def _traded_symbols(token: str) -> List[str]:
    f = _SB_EXPORTS / f"modelA_selection_trades_{token}.csv"
    if not f.exists():
        return []
    try:
        df = pd.read_csv(f, encoding="utf-8-sig")
        if "代码" in df.columns:
            return [f"{int(x):06d}" if str(x).isdigit() else str(x).strip()
                    for x in df["代码"].dropna().tolist()]
    except Exception:
        pass
    return []


def identify_pool(traded: List[str], size: Optional[int]) -> str:
    """把一次回测归属到股票池：要求 size 一致且交易过的标的都属于该池；
    多候选时用「候选间独有标的」消歧，仍不唯一则并列标注。"""
    tset = set(traded)
    cands = [name for name, codes in _ALL_POOLS.items()
             if (size is None or len(codes) == size) and tset <= set(codes)]
    if not cands:
        return f"自定义({size}只)" if size else "未知"
    if len(cands) == 1:
        return cands[0]
    for name in cands:
        others = set().union(*[set(_ALL_POOLS[o]) for o in cands if o != name])
        if tset - others:  # 交易过该池独有的标的 → 唯一确定
            return name
    return "/".join(cands)


def load_runs() -> List[Dict]:
    """读取所有 summary CSV → 每次回测一条记录（含归属池、解析后指标）。"""
    runs = []
    for path in sorted(_SB_EXPORTS.glob("modelA_selection_summary_*.csv")):
        tok = _token(path)
        metrics = _read_summary(path)
        if not metrics:
            continue
        size = _universe_size(tok)
        pool = identify_pool(_traded_symbols(tok), size)
        runs.append({"token": tok, "pool": pool, "size": size,
                     "metrics": metrics, "summary_path": path})
    return runs


def latest_by_pool(runs: List[Dict]) -> Dict[str, Dict]:
    """同一池多次回测取最新（token 时间戳最大）。"""
    out: Dict[str, Dict] = {}
    for r in sorted(runs, key=lambda x: x["token"]):
        out[r["pool"]] = r  # 后者覆盖前者 → 最新
    return out


# =====================================================
# 对比表 + 综合评分
# =====================================================

_COMPARE_METRICS = ["交易次数", "总收益率", "年化收益率", "胜率", "盈亏比",
                    "最大回撤", "收益/回撤比", "止损占比", "失败案例数量"]


def _row_for(pool: str, run: Optional[Dict]) -> Dict:
    if run is None:
        return {"股票池": pool, "数据状态": "尚未回测", **{k: None for k in _COMPARE_METRICS}}
    m = run["metrics"]
    trades = m.get("交易次数")
    mdd = m.get("最大回撤")
    ann = m.get("年化收益率")
    stop = m.get("止损次数")
    ret_dd = (ann / abs(mdd)) if (ann is not None and mdd not in (None, 0)) else None
    stop_ratio = (stop / trades) if (stop is not None and trades) else None
    return {
        "股票池": pool, "数据状态": f"已回测@{run['token']}",
        "交易次数": trades, "总收益率": m.get("总收益率"), "年化收益率": ann,
        "胜率": m.get("胜率"), "盈亏比": m.get("盈亏比"), "最大回撤": mdd,
        "收益/回撤比": None if ret_dd is None else round(ret_dd, 3),
        "止损占比": None if stop_ratio is None else round(stop_ratio, 4),
        "失败案例数量": m.get("失败案例数量"),
    }


# 综合评分权重（越大越好的项正向，回撤/止损占比/失败为反向）
_SCORE_SPEC = [("收益/回撤比", 0.30, 1), ("盈亏比", 0.25, 1), ("年化收益率", 0.20, 1),
               ("胜率", 0.15, 1), ("最大回撤", 0.10, 1)]  # 最大回撤为负值，越大(接近0)越好→正向


def _composite_scores(rows: List[Dict]) -> Dict[str, float]:
    """对有数据的池做横截面 z-score 加权综合分（透明、可复算）。"""
    have = [r for r in rows if r["数据状态"].startswith("已回测")]
    scores = {r["股票池"]: 0.0 for r in have}
    if len(have) < 1:
        return scores
    for key, w, sign in _SCORE_SPEC:
        vals = {r["股票池"]: r.get(key) for r in have if r.get(key) is not None}
        if len(vals) < 2:
            continue
        arr = np.array(list(vals.values()), dtype=float)
        mu, sd = arr.mean(), arr.std()
        if sd <= 0:
            continue
        for pool, v in vals.items():
            scores[pool] += w * sign * (v - mu) / sd
    return scores


def build_comparison() -> Dict:
    runs = load_runs()
    latest = latest_by_pool(runs)
    rows = [_row_for(p, latest.get(p)) for p in REQUESTED_POOLS]
    # 也纳入出现过但不在请求列表里的池（透明起见）
    extra = [p for p in latest if p not in REQUESTED_POOLS]
    for p in extra:
        rows.append(_row_for(p, latest[p]))

    scores = _composite_scores(rows)
    for r in rows:
        r["综合分"] = round(scores.get(r["股票池"], float("nan")), 4) \
            if r["股票池"] in scores else None
    have = [r for r in rows if r["数据状态"].startswith("已回测")]
    have_sorted = sorted(have, key=lambda r: scores.get(r["股票池"], -1e9), reverse=True)
    for i, r in enumerate(have_sorted, 1):
        r["排名"] = i
    best = have_sorted[0]["股票池"] if have_sorted else None
    return {"rows": rows, "best": best, "n_have": len(have),
            "n_missing": sum(1 for r in rows if r["数据状态"] == "尚未回测"),
            "scores": scores}


# =====================================================
# 导出 / 报告
# =====================================================

def _fmt(key: str, v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if key in ("总收益率", "年化收益率", "胜率", "最大回撤", "止损占比"):
        return f"{v * 100:.2f}%"
    if key in ("盈亏比", "收益/回撤比", "综合分"):
        return f"{v:.2f}"
    if key in ("交易次数", "失败案例数量", "排名"):
        return str(int(v))
    return str(v)


_CSV_COLS = ["排名", "股票池", "数据状态", "交易次数", "总收益率", "年化收益率", "胜率",
             "盈亏比", "最大回撤", "收益/回撤比", "止损占比", "失败案例数量", "综合分"]


def comparison_dataframe(comp: Dict) -> pd.DataFrame:
    rows = []
    for r in comp["rows"]:
        rows.append({c: r.get(c) for c in _CSV_COLS})
    df = pd.DataFrame(rows, columns=_CSV_COLS)
    return df


def build_markdown(comp: Dict) -> str:
    rows = comp["rows"]
    have = [r for r in rows if r["数据状态"].startswith("已回测")]
    p = ["# 股票池横向对比报告（模型A 选股回测）", "",
         f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
         f"- 数据来源：selection_backtest_exports 已有 summary CSV（**未重新跑回测**）",
         f"- 有数据池：{comp['n_have']} 个；尚未回测：{comp['n_missing']} 个", ""]

    cols = ["排名", "股票池", "交易次数", "总收益率", "年化收益率", "胜率", "盈亏比",
            "最大回撤", "收益/回撤比", "止损占比", "失败案例数量", "综合分"]
    p.append("## 横向对比表\n")
    p.append("| " + " | ".join(cols) + " |")
    p.append("|" + "|".join([":---:" if c in ("排名", "股票池") else "---:" for c in cols]) + "|")
    # 有数据的按排名在前，缺数据的列后
    ordered = sorted(have, key=lambda r: r.get("排名", 999)) + \
        [r for r in rows if not r["数据状态"].startswith("已回测")]
    for r in ordered:
        if r["数据状态"].startswith("已回测"):
            cells = [_fmt(c, r.get(c)) for c in cols]
        else:
            cells = [_fmt("排名", None), r["股票池"]] + ["尚未回测"] + ["—"] * (len(cols) - 3)
        p.append("| " + " | ".join(cells) + " |")

    p.append("\n> 指标口径：收益/回撤比 = 年化收益率 ÷ |最大回撤|；止损占比 = 止损次数 ÷ 交易次数。")
    p.append("> 综合分 = 各池在「收益/回撤比(0.30)·盈亏比(0.25)·年化(0.20)·胜率(0.15)·最大回撤(0.10)」"
             "上的横截面 z-score 加权（透明可复算，仅在有数据池之间比较）。")

    p.append("\n## 结论（数据驱动）\n")
    if comp["best"] and comp["n_have"] >= 1:
        best_row = next(r for r in have if r["股票池"] == comp["best"])
        p.append(f"- **当前最佳适配池：{comp['best']}**（综合分最高 = {_fmt('综合分', best_row.get('综合分'))}）。")
        p.append(f"  其 收益/回撤比 {_fmt('收益/回撤比', best_row.get('收益/回撤比'))}、"
                 f"盈亏比 {_fmt('盈亏比', best_row.get('盈亏比'))}、"
                 f"年化 {_fmt('年化收益率', best_row.get('年化收益率'))}、"
                 f"胜率 {_fmt('胜率', best_row.get('胜率'))}、"
                 f"最大回撤 {_fmt('最大回撤', best_row.get('最大回撤'))}。")
        if comp["n_have"] < 2:
            p.append("- ⚠️ 当前仅 1 个池有回测数据，结论缺乏横向参照，仅作占位；"
                     "补跑更多池后结论才有横向比较意义。")
        if comp["n_missing"]:
            miss = [r["股票池"] for r in rows if r["数据状态"] == "尚未回测"]
            p.append(f"- 尚未回测、未纳入比较的池：{('、'.join(miss))}。"
                     "如需纳入，请先用 selection_backtest_cli 跑对应 --pool，再重新生成本报告（本工具不会自动跑回测）。")
    else:
        p.append("- 暂无任何有数据的池，无法给出最佳适配池。请先跑回测。")

    p.append("\n## 风险提示与免责\n")
    p.append("- 本报告仅汇总历史模拟回测结果，样本区间/样本量有限，"
             "历史表现不代表未来，**不构成任何买入/卖出建议**。")
    p.append("- 不同池标的数不同（如 10 vs 30），分散度差异会影响回撤/胜率，横向比较需谨慎。")
    p.append("- 本系统只读、不接实盘、不下单、不接任何交易接口。")
    p.append(f"\n---\n> {config.DISCLAIMER}")
    return sanitize("\n".join(p))
