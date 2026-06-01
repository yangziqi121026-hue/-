"""V2-2：模型A 选股规则历史回测（事件驱动、交易级模拟）。

验证：若过去一段时间用模型A 扫描股票池、每个扫描日选评分前 top-n、下一交易日入场，
按既定退出规则持有，候选股后续表现如何。

**纯历史模拟，绝不接实盘 / 不自动下单 / 不新增交易接口 / 不改模型A 核心。**
复用 stock_scanner._compute_metrics + selection_models.evaluate_model_a（只调用、不修改）。

退出规则（模拟）：止损 / 第二目标 / 跌破MA20 / 持有到期，任一触发即平仓。
仓位：默认单票 10%，仅用于净值模拟，不对接任何账户。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config

from . import selection_models
from .stock_scanner import StockScanner

# ---- 模拟退出参数（仅用于回测，非投资建议、非交易指令）----
STOP_PCT = 0.05         # 止损：跌破入场价 5%
TARGET1_PCT = 0.08      # 第一目标：+8%（里程碑统计，不平仓）
TARGET2_PCT = 0.15      # 第二目标：+15%（触发平仓）
POSITION_PCT = 0.10     # 单票仓位 10%（模拟）

PERIOD_DAYS = {"3m": 90, "6m": 180, "1y": 365}
FREQ_STEP = {"daily": 1, "weekly": 5}
_WARMUP_DAYS = 70       # 预热日历天数，保证扫描日前有 ≥20 根K线
_TRADING_DAYS_YEAR = 252


@dataclass
class Trade:
    symbol: str
    name: str
    scan_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    ret: float
    pnl: float
    hold_days: int
    exit_reason: str
    target1_hit: bool


@dataclass
class BacktestResult:
    model: str
    mode: str
    period: str
    frequency: str
    cash: float
    top_n: int
    max_hold_days: int
    start: str
    end: str
    universe_size: int
    trades: List[Trade] = field(default_factory=list)
    equity: List[Tuple[str, float]] = field(default_factory=list)
    summary: Dict = field(default_factory=dict)
    note: str = ""


def _prep_history(source, symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """取单只历史K，加 MA20 列，按 date 升序。失败/不足返回 None。"""
    df = source.get_history(symbol, start, end)
    if df is None or df.empty or "close" not in df.columns:
        return None
    if getattr(df, "attrs", {}).get("is_mock"):
        df = df.copy()  # mock 也允许（离线跑通），但会在 note 标注
    df = df.sort_values("date").reset_index(drop=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["ma20"] = df["close"].rolling(20, min_periods=20).mean()
    return df


def _simulate_trade(df: pd.DataFrame, entry_pos: int, max_hold_days: int) -> Optional[Trade]:
    """从 entry_pos（次日）开始模拟一笔交易，返回 Trade（含退出原因）。"""
    n = len(df)
    if entry_pos >= n:
        return None
    entry_row = df.iloc[entry_pos]
    entry_price = float(entry_row.get("open") if pd.notna(entry_row.get("open")) else entry_row["close"])
    if not entry_price or entry_price <= 0:
        return None

    stop_px = entry_price * (1 - STOP_PCT)
    t1_px = entry_price * (1 + TARGET1_PCT)
    t2_px = entry_price * (1 + TARGET2_PCT)
    target1_hit = False

    last = min(entry_pos + max_hold_days - 1, n - 1)
    exit_pos, exit_price, reason = last, float(df.iloc[last]["close"]), "持有到期"
    for i in range(entry_pos, last + 1):
        row = df.iloc[i]
        hi = float(row["high"]) if "high" in df.columns and pd.notna(row.get("high")) else float(row["close"])
        lo = float(row["low"]) if "low" in df.columns and pd.notna(row.get("low")) else float(row["close"])
        cl = float(row["close"])
        ma20 = row.get("ma20")
        if hi >= t1_px:
            target1_hit = True
        # 同日多触发：保守地止损优先
        if lo <= stop_px:
            exit_pos, exit_price, reason = i, stop_px, "止损"
            break
        if hi >= t2_px:
            exit_pos, exit_price, reason = i, t2_px, "第二目标"
            break
        if ma20 is not None and pd.notna(ma20) and cl < float(ma20):
            exit_pos, exit_price, reason = i, cl, "跌破MA20"
            break

    ret = exit_price / entry_price - 1.0
    return Trade(
        symbol="", name="", scan_date="",
        entry_date=str(df.iloc[entry_pos]["date"]), entry_price=round(entry_price, 4),
        exit_date=str(df.iloc[exit_pos]["date"]), exit_price=round(exit_price, 4),
        ret=round(ret, 6), pnl=0.0, hold_days=exit_pos - entry_pos + 1,
        exit_reason=reason, target1_hit=target1_hit,
    )


def run_selection_backtest(source, symbols: List[str], mode: str = "loose",
                           period: str = "6m", frequency: str = "weekly",
                           cash: float = 100000.0, max_hold_days: int = 10,
                           top_n: int = 3, model: str = selection_models.MODEL_A,
                           on_progress=None) -> BacktestResult:
    config.assert_readonly()
    mode = mode if mode in selection_models.MODES else "loose"
    period = period if period in PERIOD_DAYS else "6m"
    frequency = frequency if frequency in FREQ_STEP else "weekly"
    step = FREQ_STEP[frequency]

    end = datetime.now().strftime("%Y-%m-%d")
    p_start = (datetime.now() - timedelta(days=PERIOD_DAYS[period])).strftime("%Y-%m-%d")
    fetch_start = (datetime.now() - timedelta(days=PERIOD_DAYS[period] + _WARMUP_DAYS)).strftime("%Y-%m-%d")

    scanner = StockScanner(source, fetch_industry=False)  # 回测不抓行业，避免逐日联网
    hist: Dict[str, pd.DataFrame] = {}
    is_mock = False
    for sym in symbols:
        df = _prep_history(source, sym, fetch_start, end)
        if df is not None:
            hist[sym] = df
            if getattr(df, "attrs", {}).get("is_mock"):
                is_mock = True
    # 名称（一次性）
    try:
        names = source._load_names()
    except Exception:
        names = {}

    # 交易日历（落在回测区间内的并集）
    cal = sorted({d for df in hist.values() for d in df["date"].tolist() if p_start <= d <= end})
    if len(cal) < step + 2:
        return BacktestResult(model, mode, period, frequency, cash, top_n, max_hold_days,
                              p_start, end, len(symbols), note="回测区间交易日不足，无法回测。")

    # 每只股票 date → 行号 映射
    pos_index = {sym: {d: i for i, d in enumerate(df["date"].tolist())} for sym, df in hist.items()}

    # 扫描日：每 step 个交易日一次（最后留出至少 1 天用于次日入场）
    scan_dates = cal[:-1:step]
    notional = cash * POSITION_PCT
    open_until: Dict[str, str] = {}  # symbol -> 当前持仓的退出日期（避免同票重复入场）
    trades: List[Trade] = []

    for si, scan_date in enumerate(scan_dates):
        # 1) 对每只票按 scan_date 切片 → 模型A 判定
        ranked = []
        for sym, df in hist.items():
            sl = df[df["date"] <= scan_date]
            metrics = scanner._compute_metrics(sym, names.get(sym, ""), sl)
            verdict = selection_models.evaluate_model_a(metrics, mode=mode)
            if verdict.passed:
                ranked.append((verdict.score, sym))
        ranked.sort(reverse=True)
        picks = [s for _, s in ranked[:top_n]]

        # 2) 次日入场 + 模拟持有
        for sym in picks:
            if open_until.get(sym) and scan_date <= open_until[sym]:
                continue  # 该票仍在持仓中，不重复入场
            df = hist[sym]
            sp = pos_index[sym].get(scan_date)
            if sp is None or sp + 1 >= len(df):
                continue
            entry_pos = sp + 1  # 下一交易日
            tr = _simulate_trade(df, entry_pos, max_hold_days)
            if tr is None:
                continue
            tr.symbol = sym
            tr.name = names.get(sym, "")
            tr.scan_date = scan_date
            tr.pnl = round(notional * tr.ret, 2)
            trades.append(tr)
            open_until[sym] = tr.exit_date
        if on_progress:
            on_progress(si + 1, len(scan_dates), scan_date, len(picks))

    equity = _build_equity(trades, cal, hist, pos_index, cash, notional)
    summary = _compute_summary(trades, equity, cash, period)
    note = "⚠️ 含 mock 数据（部分标的离线/接口失败），仅供跑通流程" if is_mock else ""
    return BacktestResult(model, mode, period, frequency, cash, top_n, max_hold_days,
                          p_start, end, len(symbols), trades=trades, equity=equity,
                          summary=summary, note=note)


def _build_equity(trades, cal, hist, pos_index, cash, notional) -> List[Tuple[str, float]]:
    """日净值：现金 + 已平仓盈亏 + 未平仓浮动盈亏（按收盘 mark-to-market）。"""
    out = []
    for d in cal:
        total = cash
        for t in trades:
            if d < t.entry_date:
                continue
            if d >= t.exit_date:
                total += notional * t.ret  # 已实现
            else:
                df = hist[t.symbol]
                pi = pos_index[t.symbol].get(d)
                if pi is not None:
                    px = float(df.iloc[pi]["close"])
                    total += notional * (px / t.entry_price - 1.0)  # 浮动
        out.append((d, round(total, 2)))
    return out


def _compute_summary(trades: List[Trade], equity, cash: float, period: str) -> Dict:
    n = len(trades)
    s: Dict = {
        "交易次数": n, "总收益率": float("nan"), "年化收益率": float("nan"),
        "胜率": float("nan"), "盈亏比": float("nan"), "最大回撤": float("nan"),
        "平均持仓天数": float("nan"), "平均单笔收益": float("nan"),
        "最大单笔盈利": float("nan"), "最大单笔亏损": float("nan"),
        "止损次数": 0, "第一目标达成次数": 0, "第二目标达成次数": 0, "失败案例数量": 0,
    }
    if equity and len(equity) >= 2 and equity[0][1] > 0:
        eq = pd.Series([v for _, v in equity], dtype=float)
        s["总收益率"] = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
        nn = len(eq) - 1
        growth = eq.iloc[-1] / eq.iloc[0]
        if growth > 0:
            s["年化收益率"] = float(growth ** (_TRADING_DAYS_YEAR / nn) - 1.0)
        dd = eq / eq.cummax() - 1.0
        s["最大回撤"] = float(dd.min())
    if n:
        rets = np.array([t.ret for t in trades], dtype=float)
        wins = rets[rets > 0]
        losses = rets[rets < 0]
        s["胜率"] = float(len(wins) / n)
        if len(wins) and len(losses):
            s["盈亏比"] = float(wins.mean() / abs(losses.mean()))
        s["平均持仓天数"] = float(np.mean([t.hold_days for t in trades]))
        s["平均单笔收益"] = float(rets.mean())
        s["最大单笔盈利"] = float(rets.max())
        s["最大单笔亏损"] = float(rets.min())
        s["止损次数"] = sum(1 for t in trades if t.exit_reason == "止损")
        s["第一目标达成次数"] = sum(1 for t in trades if t.target1_hit)
        s["第二目标达成次数"] = sum(1 for t in trades if t.exit_reason == "第二目标")
        s["失败案例数量"] = int((rets < 0).sum())
    return s


# =====================================================
# 导出 / 报告 / 图表
# =====================================================

def trades_dataframe(result: "BacktestResult") -> pd.DataFrame:
    rows = []
    for i, t in enumerate(result.trades, 1):
        rows.append({
            "序号": i, "代码": t.symbol, "名称": t.name, "扫描日": t.scan_date,
            "入场日": t.entry_date, "入场价": t.entry_price, "出场日": t.exit_date,
            "出场价": t.exit_price, "收益率%": round(t.ret * 100, 2), "盈亏(元)": t.pnl,
            "持仓天数": t.hold_days, "退出原因": t.exit_reason,
            "曾达第一目标": "是" if t.target1_hit else "否",
        })
    return pd.DataFrame(rows)


def summary_dataframe(result: "BacktestResult") -> pd.DataFrame:
    s = result.summary
    pct = {"总收益率", "年化收益率", "胜率", "最大回撤", "平均单笔收益", "最大单笔盈利", "最大单笔亏损"}
    rows = []
    for k, v in s.items():
        if isinstance(v, float) and (v != v):  # NaN
            disp = "不足以判断"
        elif k in pct and isinstance(v, (int, float)):
            disp = f"{v * 100:.2f}%"
        elif k == "盈亏比" and isinstance(v, (int, float)):
            disp = f"{v:.2f}"
        elif k == "平均持仓天数" and isinstance(v, (int, float)):
            disp = f"{v:.1f}"
        else:
            disp = str(v)
        rows.append({"指标": k, "数值": disp})
    return pd.DataFrame(rows)


def save_equity_chart(result: "BacktestResult", path) -> bool:
    """保存净值曲线 PNG（matplotlib Agg）。失败返回 False。"""
    if not result.equity:
        return False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager  # noqa: F401
        # 中文字体尽力而为，缺失则用英文标题不报错
        for fam in ("Microsoft YaHei", "SimHei", "Arial Unicode MS"):
            try:
                matplotlib.rcParams["font.sans-serif"] = [fam]
                matplotlib.rcParams["axes.unicode_minus"] = False
                break
            except Exception:
                continue
        dates = [d for d, _ in result.equity]
        vals = [v for _, v in result.equity]
        fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
        ax.plot(range(len(vals)), vals, color="#4ea1ff", linewidth=1.6)
        ax.fill_between(range(len(vals)), vals, min(vals), color="#4ea1ff", alpha=0.08)
        ax.set_title(f"模型A 选股回测净值曲线（{result.mode}/{result.period}，仅模拟·不构成投资建议）")
        ax.set_ylabel("模拟净值(元)")
        step = max(1, len(dates) // 8)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=30, ha="right", fontsize=8)
        ax.grid(True, alpha=0.2)
        fig.tight_layout()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path)
        plt.close(fig)
        return True
    except Exception:
        return False


def build_markdown(result: "BacktestResult", chart_name: str = "") -> str:
    from reporting.base import sanitize

    s = result.summary
    sd = summary_dataframe(result)
    p = ["# 模型A 选股规则历史回测报告", "",
         f"- 回测时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
         f"- 模型：{result.model}（短线强势股模型A）",
         f"- 模式：{result.mode}（{'严格' if result.mode == 'strict' else '宽松'}）",
         f"- 区间：{result.start} ~ {result.end}（{result.period}）",
         f"- 扫描频率：{result.frequency}（每 {FREQ_STEP[result.frequency]} 交易日扫描一次）",
         f"- 每次选 top-{result.top_n}，次日入场，最多持有 {result.max_hold_days} 交易日",
         f"- 模拟资金：{result.cash:.0f} 元，单票仓位 {POSITION_PCT*100:.0f}%（仅模拟、不接账户）",
         f"- 股票池数量：{result.universe_size}",
         f"- 模拟退出规则：止损 -{STOP_PCT*100:.0f}% / 第二目标 +{TARGET2_PCT*100:.0f}% / "
         f"跌破MA20 / 持有到期（第一目标 +{TARGET1_PCT*100:.0f}% 仅作里程碑统计）", ""]
    if result.note:
        p.append(f"> {result.note}\n")
    if not result.trades:
        p.append("> 本次回测区间内没有产生任何模拟交易（无标的通过模型A条件）。\n")

    p.append("## 回测指标\n")
    p.append("| 指标 | 数值 |")
    p.append("|:---|---:|")
    for _, row in sd.iterrows():
        p.append(f"| {row['指标']} | {row['数值']} |")

    if chart_name:
        p.append(f"\n## 净值曲线\n\n![净值曲线](../selection_backtest_charts/{chart_name})\n")

    p.append("\n## 交易明细\n")
    if result.trades:
        p.append("| # | 代码 | 名称 | 入场日 | 出场日 | 收益率 | 持仓天数 | 退出原因 | 曾达第一目标 |")
        p.append("|---:|:---|:---|:---|:---|---:|---:|:---|:---:|")
        for i, t in enumerate(result.trades, 1):
            p.append(f"| {i} | {t.symbol} | {t.name or '—'} | {t.entry_date} | {t.exit_date} "
                     f"| {t.ret*100:.2f}% | {t.hold_days} | {t.exit_reason} | "
                     f"{'是' if t.target1_hit else '否'} |")
    else:
        p.append("（无）")

    # 退出原因分布
    if result.trades:
        from collections import Counter
        c = Counter(t.exit_reason for t in result.trades)
        p.append("\n## 退出原因分布\n")
        for k, v in c.most_common():
            p.append(f"- {k}：{v} 次")

    p.append("\n## 风险提示\n")
    p.append("- 本回测为**历史模拟复盘**，退出规则与仓位为模拟参数，"
             "不代表未来、**不构成任何买入/卖出建议**。")
    p.append("- 短线强势股波动大、回撤快；模拟未计交易成本/滑点/涨跌停不可成交等现实摩擦，结果偏理想化。")
    p.append("- 样本量小时统计指标不稳健；同日多触发按「止损优先」假设处理。")
    p.append("- 本系统只读、不接实盘、不下单、不接任何交易接口。")
    p.append("\n## 免责声明\n")
    p.append(f"> {config.DISCLAIMER}")
    return sanitize("\n".join(p))
