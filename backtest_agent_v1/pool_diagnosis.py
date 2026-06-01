"""股票池成分贡献诊断（基于已有回测交易明细，**不重跑回测、不改模型A、不改回测核心**）。

读取某个池（默认 tech_30）对应的 selection_backtest_trades CSV，按成分股聚合每只的贡献，
给出 保留 / 观察 / 踢出 建议与理由。替补候选**只生成观察名单，不直接替换**。

只读分析，不接实盘、不下单、不出买卖建议。
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

from . import pool_compare, stock_pools

_SB_EXPORTS = config.output_dir("selection_backtest", "exports")

# ---- 踢出阈值 ----
EJECT_MIN_TRADES = 3
EJECT_WIN = 0.35
EJECT_STOP_RATIO = 0.40
EJECT_AVG = -0.01
EJECT_MAXLOSS = -0.08
EJECT_NEEDED = 2  # 满足任意 N 条即建议踢出


def find_pool_trades(pool: str = "tech_30") -> Optional[Dict]:
    """定位某池最新一次回测的 trades CSV。复用 pool_compare 的归属逻辑。"""
    runs = pool_compare.load_runs()
    latest = pool_compare.latest_by_pool(runs)
    run = latest.get(pool)
    if run is None:
        return None
    token = run["token"]
    trades = _SB_EXPORTS / f"modelA_selection_trades_{token}.csv"
    if not trades.exists():
        return None
    return {"pool": pool, "token": token, "trades_path": trades}


def load_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str})
    if "代码" in df.columns:
        df["代码"] = df["代码"].astype(str).str.extract(r"(\d+)")[0].str.zfill(6)
    return df


def _agg_symbol(code: str, name: str, g: pd.DataFrame) -> Dict:
    rets = pd.to_numeric(g["收益率%"], errors="coerce").dropna() / 100.0
    n = len(rets)
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    pl = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else None
    stops = int((g["退出原因"] == "止损").sum()) if "退出原因" in g.columns else 0
    t1 = int((g.get("曾达第一目标", pd.Series(dtype=str)) == "是").sum())
    t2 = int((g["退出原因"] == "第二目标").sum()) if "退出原因" in g.columns else 0
    hold = pd.to_numeric(g.get("持仓天数", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "代码": code, "名称": name, "交易次数": n,
        "总收益贡献": float(rets.sum()),            # 各笔收益率之和（等仓位下 ∝ 盈亏）
        "平均单笔收益": float(rets.mean()) if n else None,
        "胜率": float(len(wins) / n) if n else None,
        "盈亏比": pl,
        "最大单笔盈利": float(rets.max()) if n else None,
        "最大单笔亏损": float(rets.min()) if n else None,
        "止损次数": stops,
        "止损占比": float(stops / n) if n else None,
        "第一目标达成次数": t1,
        "第二目标达成次数": t2,
        "平均持仓天数": float(hold.mean()) if len(hold) else None,
    }


_SCORE_SPEC = [("总收益贡献", 0.30, 1), ("胜率", 0.20, 1), ("盈亏比", 0.20, 1),
               ("平均单笔收益", 0.15, 1), ("止损占比", 0.10, -1), ("最大单笔亏损", 0.05, 1)]


def _composite(rows: List[Dict]) -> Dict[str, float]:
    scores = {r["代码"]: 0.0 for r in rows}
    if len(rows) < 2:
        return scores
    for key, w, sign in _SCORE_SPEC:
        vals = {r["代码"]: r.get(key) for r in rows if r.get(key) is not None}
        if len(vals) < 2:
            continue
        arr = np.array(list(vals.values()), dtype=float)
        mu, sd = arr.mean(), arr.std()
        if sd <= 0:
            continue
        for code, v in vals.items():
            scores[code] += w * sign * (v - mu) / sd
    return scores


def _eject_conditions(r: Dict, contrib_rank: int, n_total: int, median_trades: float) -> List[str]:
    hit = []
    if r["交易次数"] >= EJECT_MIN_TRADES and r["总收益贡献"] is not None and r["总收益贡献"] < 0:
        hit.append(f"交易≥{EJECT_MIN_TRADES}且总贡献为负")
    if r["胜率"] is not None and r["胜率"] < EJECT_WIN:
        hit.append("胜率<35%")
    if r["止损占比"] is not None and r["止损占比"] > EJECT_STOP_RATIO:
        hit.append("止损占比>40%")
    if r["平均单笔收益"] is not None and r["平均单笔收益"] < EJECT_AVG:
        hit.append("平均单笔<-1%")
    if r["最大单笔亏损"] is not None and r["最大单笔亏损"] <= EJECT_MAXLOSS:
        hit.append("最大单笔亏损≤-8%")
    # 条件6：入选次数较多（≥中位数）但贡献排名靠后（后 1/3）
    if r["交易次数"] >= median_trades and contrib_rank > math.ceil(n_total * 2 / 3):
        hit.append("入选较多但贡献排名靠后")
    return hit


def diagnose(pool: str = "tech_30") -> Dict:
    config.assert_readonly()
    loc = find_pool_trades(pool)
    if loc is None:
        return {"pool": pool, "error": f"未找到 {pool} 的回测交易明细（请先用 selection_backtest_cli --pool {pool} 跑回测）。",
                "rows": [], "untraded": [], "counts": {}}
    df = load_trades(loc["trades_path"])
    if df.empty or "代码" not in df.columns:
        return {"pool": pool, "error": "交易明细为空或缺列。", "rows": [], "untraded": [], "counts": {}}

    rows: List[Dict] = []
    for code, g in df.groupby("代码"):
        raw = g["名称"].iloc[0] if "名称" in g.columns and len(g) else ""
        name = "" if (raw is None or (isinstance(raw, float) and math.isnan(raw))
                      or str(raw).strip().lower() == "nan") else str(raw).strip()
        rows.append(_agg_symbol(code, name, g))

    # 贡献排名（降序）
    rows.sort(key=lambda r: r["总收益贡献"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["贡献排名"] = i
    n_total = len(rows)
    median_trades = float(np.median([r["交易次数"] for r in rows])) if rows else 0.0

    scores = _composite(rows)
    for r in rows:
        r["综合评分"] = round(scores.get(r["代码"], float("nan")), 4)
        hits = _eject_conditions(r, r["贡献排名"], n_total, median_trades)
        r["_eject_hits"] = hits
        if len(hits) >= EJECT_NEEDED:
            r["建议"] = "踢出"
            r["建议理由"] = "触发 " + "、".join(hits)
        elif len(hits) == 1:
            r["建议"] = "观察"
            r["建议理由"] = "触发 " + hits[0]
        else:
            if r["总收益贡献"] is not None and r["总收益贡献"] > 0:
                r["建议"] = "保留"
                r["建议理由"] = (f"正贡献 {r['总收益贡献']*100:.1f}%、"
                                 f"胜率 {(r['胜率'] or 0)*100:.0f}%，无触发踢出条件")
            else:
                r["建议"] = "观察"
                r["建议理由"] = "无触发踢出条件，但总贡献非正，待观察"

    # 池内未交易成分（替补候选 → 只进观察名单）
    members = stock_pools.get_pool(pool) or []
    traded = {r["代码"] for r in rows}
    untraded = [c for c in members if c not in traded]

    counts = {"保留": sum(1 for r in rows if r["建议"] == "保留"),
              "观察": sum(1 for r in rows if r["建议"] == "观察"),
              "踢出": sum(1 for r in rows if r["建议"] == "踢出"),
              "未交易": len(untraded)}
    return {"pool": pool, "token": loc["token"], "trades_path": loc["trades_path"],
            "rows": rows, "untraded": untraded, "counts": counts, "n_total": n_total}


# =====================================================
# 导出 / 报告
# =====================================================

_CSV_COLS = ["代码", "名称", "交易次数", "总收益贡献", "平均单笔收益", "胜率", "盈亏比",
             "最大单笔盈利", "最大单笔亏损", "止损次数", "止损占比",
             "第一目标达成次数", "第二目标达成次数", "平均持仓天数",
             "贡献排名", "综合评分", "建议", "建议理由"]
_PCT_COLS = {"总收益贡献", "平均单笔收益", "胜率", "最大单笔盈利", "最大单笔亏损", "止损占比"}


def _fmt(key: str, v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if key in _PCT_COLS:
        return f"{v * 100:.2f}%"
    if key in ("盈亏比", "综合评分"):
        return f"{v:.2f}"
    if key == "平均持仓天数":
        return f"{v:.1f}"
    if key in ("交易次数", "止损次数", "第一目标达成次数", "第二目标达成次数", "贡献排名"):
        return str(int(v))
    return str(v)


def diagnosis_dataframe(diag: Dict) -> pd.DataFrame:
    rows = [{c: r.get(c) for c in _CSV_COLS} for r in diag.get("rows", [])]
    return pd.DataFrame(rows, columns=_CSV_COLS)


def build_markdown(diag: Dict) -> str:
    pool = diag.get("pool", "?")
    if diag.get("error"):
        return sanitize(f"# 股票池成分贡献诊断（{pool}）\n\n**{diag['error']}**\n\n"
                        f"---\n> {config.DISCLAIMER}")
    c = diag["counts"]
    rows = sorted(diag["rows"], key=lambda r: (r["综合评分"] if r["综合评分"] == r["综合评分"] else -1e9),
                  reverse=True)
    p = [f"# 股票池成分贡献诊断（{pool}）", "",
         f"- 诊断时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
         f"- 数据来源：{Path(diag['trades_path']).name}（已有回测交易明细，未重跑回测）",
         f"- 成分内有交易：{diag['n_total']} 只；未交易：{c['未交易']} 只",
         f"- 建议分布：保留 {c['保留']} · 观察 {c['观察']} · 踢出 {c['踢出']}", ""]

    p.append("## 成分股贡献明细（按综合评分排序）\n")
    cols = ["代码", "名称", "交易次数", "总收益贡献", "平均单笔收益", "胜率", "盈亏比",
            "最大单笔亏损", "止损占比", "第一目标达成次数", "第二目标达成次数",
            "平均持仓天数", "综合评分", "建议"]
    p.append("| " + " | ".join(cols) + " |")
    p.append("|" + "|".join([":---:" if x in ("代码", "建议") else (":---" if x == "名称" else "---:")
                             for x in cols]) + "|")
    for r in rows:
        p.append("| " + " | ".join(_fmt(x, r.get(x)) for x in cols) + " |")

    p.append("\n## 建议明细\n")
    for tag in ("踢出", "观察", "保留"):
        sub = [r for r in rows if r["建议"] == tag]
        if not sub:
            continue
        p.append(f"### {tag}（{len(sub)} 只）")
        for r in sub:
            p.append(f"- **{r['代码']} {r['名称'] or ''}**（综合 {_fmt('综合评分', r['综合评分'])}，"
                     f"贡献 {_fmt('总收益贡献', r['总收益贡献'])}）：{r['建议理由']}")
        p.append("")

    if diag["untraded"]:
        p.append("## 替补候选观察名单（成分内未被选中交易的标的）\n")
        p.append("> 仅作**观察**，不直接替换被踢出标的；是否纳入需另行回测验证。\n")
        p.append("、".join(diag["untraded"]))

    p.append("\n## 风险提示与免责\n")
    p.append("- 诊断基于单段历史模拟样本，样本量有限，结论可能不稳健；"
             "「踢出/保留」为**研究性分级**，不代表未来，**不构成任何买入/卖出建议**。")
    p.append("- 替补候选仅生成观察名单，**不自动替换、不自动调整股票池**。")
    p.append("- 本系统只读、不接实盘、不下单、不接任何交易接口。")
    p.append(f"\n---\n> {config.DISCLAIMER}")
    return sanitize("\n".join(p))
