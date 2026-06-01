"""模型A 选股规则历史回测 CLI（只读模拟，不接实盘/不下单/不接交易接口）。

用法：
  python -m backtest_agent_v1.selection_backtest_cli --model strong --mode loose \
    --symbols 300308,688981,002463,601138,300502,300750,002230,300015,002236,603986 \
    --period 6m --frequency weekly --cash 100000 --max-hold-days 10 --top-n 3

输出：
  selection_backtest_reports/modelA_selection_backtest_<时间>.md
  selection_backtest_exports/modelA_selection_trades_<时间>.csv
  selection_backtest_exports/modelA_selection_summary_<时间>.csv
  selection_backtest_charts/modelA_selection_equity_<时间>.png
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from data import AkshareDataSource

from . import selection_backtest as sb
from . import selection_models, stock_pools


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="模型A 选股规则历史回测（只读模拟）")
    p.add_argument("--model", default="strong")
    p.add_argument("--mode", default="loose", choices=list(selection_models.MODES))
    p.add_argument("--symbols", default=None, help="逗号分隔 6 位代码（与 --pool 二选一；同传优先此项）")
    p.add_argument("--pool", default=None, choices=stock_pools.list_pools(),
                   help="预设股票池：" + " / ".join(stock_pools.list_pools()))
    p.add_argument("--period", default="6m", choices=list(sb.PERIOD_DAYS))
    p.add_argument("--frequency", default="weekly", choices=list(sb.FREQ_STEP))
    p.add_argument("--cash", type=float, default=100000.0)
    p.add_argument("--max-hold-days", type=int, default=10)
    p.add_argument("--top-n", type=int, default=3)
    args = p.parse_args(argv)

    if args.model != selection_models.MODEL_A:
        print(f"当前仅实现模型A（--model strong）；未实现：{args.model}。", file=sys.stderr)
        return 2
    symbols, source, note = stock_pools.resolve(args.symbols, args.pool)
    if not symbols:
        print(f"未得到有效标的：{note or '请提供 --symbols 或 --pool'}", file=sys.stderr)
        return 2

    config.assert_readonly()
    print(f"标的来源：{source}{('  ' + note) if note else ''}")
    print(f"模型A 选股回测｜{args.mode}｜{args.period}/{args.frequency}｜top-{args.top_n}"
          f"｜池 {len(symbols)} 只｜模拟资金 {args.cash:.0f}")

    source = AkshareDataSource()

    def _prog(i, total, d, npick):
        print(f"  扫描 [{i}/{total}] {d} → 选 {npick} 只", flush=True)

    result = sb.run_selection_backtest(
        source, symbols, mode=args.mode, period=args.period, frequency=args.frequency,
        cash=args.cash, max_hold_days=args.max_hold_days, top_n=args.top_n,
        model=args.model, on_progress=_prog)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep = config.output_dir("selection_backtest", "reports")
    exp = config.output_dir("selection_backtest", "exports")
    cha = config.output_dir("selection_backtest", "charts")
    for d in (rep, exp, cha):
        d.mkdir(parents=True, exist_ok=True)

    chart_name = f"modelA_selection_equity_{ts}.png"
    chart_ok = sb.save_equity_chart(result, cha / chart_name)

    md = sb.build_markdown(result, chart_name=chart_name if chart_ok else "")
    md_path = rep / f"modelA_selection_backtest_{ts}.md"
    md_path.write_text(md, encoding="utf-8")

    trades_path = exp / f"modelA_selection_trades_{ts}.csv"
    summary_path = exp / f"modelA_selection_summary_{ts}.csv"
    sb.trades_dataframe(result).to_csv(trades_path, index=False, encoding="utf-8-sig")
    sb.summary_dataframe(result).to_csv(summary_path, index=False, encoding="utf-8-sig")

    s = result.summary
    print(f"\n交易 {s['交易次数']} 笔｜"
          f"总收益 {_fmt(s['总收益率'])}｜年化 {_fmt(s['年化收益率'])}｜"
          f"胜率 {_fmt(s['胜率'])}｜盈亏比 {_fmt2(s['盈亏比'])}｜最大回撤 {_fmt(s['最大回撤'])}")
    print(f"止损 {s['止损次数']}｜第一目标 {s['第一目标达成次数']}｜第二目标 {s['第二目标达成次数']}｜失败 {s['失败案例数量']}")
    print(f"\n报告：{md_path}\n交易：{trades_path}\n汇总：{summary_path}")
    print(f"图表：{cha / chart_name}" if chart_ok else "图表：（matplotlib 不可用，已跳过 PNG）")
    return 0


def _fmt(v):
    return "不足以判断" if isinstance(v, float) and v != v else f"{v*100:.2f}%"


def _fmt2(v):
    return "不足以判断" if isinstance(v, float) and v != v else f"{v:.2f}"


if __name__ == "__main__":
    sys.exit(main())
