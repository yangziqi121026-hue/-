"""selection_backtest 最小可跑闭环入口（只读）。

数据(AkshareDataSource) → 因子/策略(MultiFactorStrategy) → 选股 + 回测(engine) → 报告(reporting)。
产出写入 config 登记的 selection_backtest_reports / selection_backtest_exports。

绝不下单、绝不接实盘、绝不接交易接口。无网络时自动走 mock 数据跑通流程。

示例：
  python selection_backtest_run.py --universe 600519,000858,600036 --top 2
  python selection_backtest_run.py --universe hs300 --limit 20 --top 5 --start 2023-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from backtest_agent_v1 import engine
from data import AkshareDataSource
from models import MultiFactorStrategy
from reporting.backtest_report import BacktestReport
from reporting.screen_report import ScreenReport

_WARMUP_DAYS = 220


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _shift(d: str, days: int) -> str:
    return (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def main() -> int:
    p = argparse.ArgumentParser(description="A股选股+回测最小闭环（只读，不下单）")
    p.add_argument("--universe", default="hs300", help="hs300/zz500/sz50 或清单文件或代码串")
    p.add_argument("--limit", type=int, default=None, help="截断股票池规模")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--freq", default="monthly", choices=["weekly", "monthly"])
    p.add_argument("--start", default=_shift(_today(), 365 * 2))
    p.add_argument("--end", default=_today())
    p.add_argument("--no-cost", action="store_true")
    args = p.parse_args()

    config.assert_readonly()
    ds = AkshareDataSource()
    uni = ds.resolve_universe(args.universe, limit=args.limit)
    codes, name_map = uni["codes"], uni["name_map"]
    if not codes:
        print("股票池为空。", file=sys.stderr)
        return 2
    tag = "  ⚠️mock" if uni["is_mock"] else ""
    print(f"股票池：{uni['source']}（{len(codes)} 只）{tag}")

    fetch_start = _shift(args.start, _WARMUP_DAYS)
    print(f"抓取历史K（含预热）：{fetch_start} ~ {args.end}")
    bundles = {}
    for i, sym in enumerate(codes, 1):
        b = ds.get_bundle(sym, fetch_start, args.end)
        bundles[sym] = b
        bars = 0 if b.history is None or b.history.empty else len(b.history)
        print(f"  [{i}/{len(codes)}] {sym} {b.name or '':<6} {bars} 根", flush=True)

    strat = MultiFactorStrategy()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta = {"data_source": "AKShare 日K（只读）" + ("｜mock" if uni["is_mock"] else ""),
            "universe_source": uni["source"]}

    # --- 选股（as_of = 区间内最后一个交易日）---
    all_dates = sorted({d for b in bundles.values()
                        if b.history is not None and not b.history.empty
                        for d in b.history["date"].tolist() if d <= args.end})
    as_of = all_dates[-1] if all_dates else args.end
    screen = strat.select(bundles, as_of, top_n=args.top)
    screen_md = ScreenReport().build(screen, meta)
    sp = _write(config.output_dir("selection_backtest", "reports") / f"选股_{as_of}_{ts}.md", screen_md)
    # 导出选股结果 json
    _write(config.output_dir("selection_backtest", "exports") / f"选股_{as_of}_{ts}.json",
           json.dumps({"as_of": as_of, "selected": screen.selected,
                       "ranked": screen.ranked[:args.top]}, ensure_ascii=False, indent=2))

    print(f"\n选股 as_of {as_of}：")
    for r in screen.ranked[:args.top]:
        print(f"  #{r['rank']} {r['symbol']} {r['name'] or '':<6} 综合{r['composite']:+.3f} [{r['grade']}]")

    # --- 回测 ---
    print("\n回测中（逐期 point-in-time 选股）…")
    bt = engine.run_backtest(strat, bundles, args.start, args.end,
                             top_n=args.top, freq=args.freq,
                             cost_enabled=not args.no_cost, name_map=name_map)
    summary = engine.summarize(bt.get("equity", []), bt.get("period_returns", []))
    bt_md = BacktestReport().build({"bt": bt, "summary": summary}, meta)
    bp = _write(config.output_dir("selection_backtest", "reports") / f"回测_{args.start}_{args.end}_{ts}.md", bt_md)
    _write(config.output_dir("selection_backtest", "exports") / f"回测净值_{ts}.json",
           json.dumps({"equity": bt.get("equity", []), "summary": summary,
                       "holdings": bt.get("holdings", [])}, ensure_ascii=False, indent=2,
                      default=str))

    if bt.get("error"):
        print(f"回测：{bt['error']}")
    else:
        print(f"回测 {bt['calendar_start']}~{bt['calendar_end']}，{bt['n_rebalances']} 次调仓：")
        print(f"  累计 {summary['total_return']*100:.2f}% | 年化 {summary['annualized_return']*100:.2f}% "
              f"| 回撤 {summary['max_drawdown']*100:.2f}% | 胜率 "
              f"{(summary['win_rate']*100 if summary['win_rate']==summary['win_rate'] else float('nan')):.1f}%")
    print(f"\n报告：\n  {sp}\n  {bp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
