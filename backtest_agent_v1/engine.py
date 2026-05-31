"""回测 agent v1：compact 滚动回测引擎 + 绩效指标。

纪律：每个调仓日只用 date <= 调仓日 的数据选股（point-in-time，无前视）；
等权买入持有到下期；默认扣单边成本（佣金双边 + 卖出印花税）。只读复盘，绝不下单。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import config

COMMISSION_RATE = 0.0003
STAMP_TAX_RATE = 0.001
TRADING_DAYS = 252


def _period_key(d: str, freq: str) -> str:
    dt = datetime.strptime(d, "%Y-%m-%d")
    if freq == "weekly":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{dt.year}-{dt.month:02d}"


def rebalance_dates(calendar: List[str], freq: str) -> List[str]:
    seen, out = set(), []
    for d in calendar:
        k = _period_key(d, freq)
        if k not in seen:
            seen.add(k); out.append(d)
    return out


def _close_panel(bundles: Dict[str, Any], calendar: List[str]) -> pd.DataFrame:
    cols = {}
    for sym, b in bundles.items():
        df = getattr(b, "history", None)
        if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
            continue
        s = pd.to_numeric(df.set_index("date")["close"], errors="coerce")
        cols[sym] = s[~s.index.duplicated(keep="last")].reindex(calendar).ffill()
    return pd.DataFrame(cols, index=calendar)


def _basket_rel(panel: pd.DataFrame, day: str, entry: Dict[str, float]) -> Optional[float]:
    rels = []
    for s, ep in entry.items():
        if ep and ep > 0 and s in panel.columns:
            px = panel.at[day, s]
            if px is not None and not (isinstance(px, float) and np.isnan(px)):
                rels.append(px / ep)
    return float(np.mean(rels)) if rels else None


def run_backtest(strategy, bundles: Dict[str, Any], start: str, end: str,
                 top_n: int = 20, freq: str = "monthly",
                 cost_enabled: bool = True, name_map: Optional[Dict[str, str]] = None,
                 benchmark: Optional[pd.DataFrame] = None) -> Dict:
    name_map = name_map or {}
    all_dates = set()
    for b in bundles.values():
        df = getattr(b, "history", None)
        if df is not None and not df.empty and "date" in df.columns:
            all_dates.update(df["date"].tolist())
    calendar = sorted(d for d in all_dates if start <= d <= end)
    if len(calendar) < 2:
        return {"error": "回测区间内交易日不足", "equity": [], "benchmark_equity": [],
                "period_returns": [], "holdings": []}

    panel = _close_panel(bundles, calendar)
    rebs = rebalance_dates(calendar, freq)
    cur, equity, period_returns, holdings, prev_sel = 1.0, [], [], [], set()

    for i, e in enumerate(rebs):
        exit_day = rebs[i + 1] if i + 1 < len(rebs) else calendar[-1]
        if e >= exit_day:
            continue
        sel = strategy.select(bundles, as_of=e, top_n=top_n).selected
        turnover = 1.0 if not prev_sel else len(set(sel) - prev_sel) / max(len(sel), 1)
        cost = turnover * (2 * COMMISSION_RATE + STAMP_TAX_RATE) if cost_enabled else 0.0
        cur *= (1.0 - cost)
        entry = {}
        for s in sel:
            if s in panel.columns:
                px = panel.at[e, s]
                if px and not (isinstance(px, float) and np.isnan(px)) and px > 0:
                    entry[s] = float(px)
        if not equity:
            equity.append((e, round(cur, 6)))
        base, last_rel = cur, 1.0
        for d in [x for x in calendar if e < x <= exit_day]:
            rel = _basket_rel(panel, d, entry)
            last_rel = rel if rel is not None else last_rel
            equity.append((d, round(base * last_rel, 6)))
        cur = base * last_rel
        period_returns.append(last_rel - 1.0)
        holdings.append({"entry": e, "exit": exit_day, "selected": sel,
                         "names": [name_map.get(s, "") for s in sel],
                         "period_return": round(last_rel - 1.0, 4), "turnover": round(turnover, 4)})
        prev_sel = set(sel)

    bench_eq = []
    if benchmark is not None and not benchmark.empty and equity:
        b = pd.to_numeric(benchmark.set_index("date")["close"], errors="coerce")
        b = b[~b.index.duplicated(keep="last")].reindex(calendar).ffill()
        anchor = b.get(equity[0][0])
        if anchor and not np.isnan(anchor) and anchor > 0:
            for d, _ in equity:
                bv = b.get(d)
                if bv is not None and not np.isnan(bv):
                    bench_eq.append((d, round(float(bv / anchor), 6)))

    return {"equity": equity, "benchmark_equity": bench_eq, "period_returns": period_returns,
            "holdings": holdings, "rebalances": rebs, "calendar_start": calendar[0],
            "calendar_end": calendar[-1], "n_rebalances": len(holdings),
            "freq": freq, "top_n": top_n, "cost_enabled": cost_enabled}


# ---------- 绩效指标 ----------

def _series(equity) -> pd.Series:
    if not equity:
        return pd.Series(dtype=float)
    return pd.Series([v for _, v in equity], index=[d for d, _ in equity], dtype=float)


def summarize(equity, period_returns=None, benchmark=None) -> Dict:
    s = _series(equity)
    out: Dict = {"total_return": float("nan"), "annualized_return": float("nan"),
                 "annualized_vol": float("nan"), "sharpe": float("nan"),
                 "max_drawdown": float("nan"), "win_rate": float("nan"), "n_points": len(s)}
    if len(s) >= 2 and s.iloc[0] > 0:
        out["total_return"] = float(s.iloc[-1] / s.iloc[0] - 1.0)
        n = len(s) - 1
        growth = s.iloc[-1] / s.iloc[0]
        if growth > 0:
            out["annualized_return"] = float(growth ** (TRADING_DAYS / n) - 1.0)
        r = s.pct_change().dropna()
        if len(r) >= 2:
            out["annualized_vol"] = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
            if out["annualized_vol"] > 0:
                out["sharpe"] = float(out["annualized_return"] / out["annualized_vol"])
        dd = s / s.cummax() - 1.0
        out["max_drawdown"] = float(dd.min())
    pr = [x for x in (period_returns or []) if x is not None and not (isinstance(x, float) and np.isnan(x))]
    if pr:
        out["win_rate"] = float(sum(1 for x in pr if x > 0) / len(pr))
    if benchmark:
        bs = _series(benchmark)
        if len(bs) >= 2 and bs.iloc[0] > 0:
            bn = len(bs) - 1
            bg = bs.iloc[-1] / bs.iloc[0]
            out["benchmark_total_return"] = float(bg - 1.0)
            if bg > 0:
                out["benchmark_annualized_return"] = float(bg ** (TRADING_DAYS / bn) - 1.0)
                if not math.isnan(out["annualized_return"]):
                    out["excess_annualized"] = out["annualized_return"] - out["benchmark_annualized_return"]
    return out
