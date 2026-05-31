"""模型A 短线强势股扫描 CLI（只读，不下单，不出买卖建议）。

用法：
  python -m backtest_agent_v1.scan_cli --model strong --mode loose \
    --symbols 300308,688981,002463,601138,300502,300750,002230,300015,002236,603986 --limit 50

输出：
  scan_reports/strong_stock_scan_<时间>.md
  scan_exports/strong_stock_scan_<时间>.csv
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from data import AkshareDataSource

from . import selection_models
from .stock_scanner import StockScanner


def _parse_symbols(spec: str) -> list:
    out, seen = [], set()
    for tok in re.split(r"[,\s]+", spec or ""):
        m = re.search(r"\d{6}", tok)
        if m and m.group(0) not in seen:
            seen.add(m.group(0))
            out.append(m.group(0))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="模型A 短线强势股扫描器（只读，不下单）")
    p.add_argument("--model", default="strong", help="选股模型（当前仅支持 strong=模型A）")
    p.add_argument("--mode", default="loose", choices=list(selection_models.MODES), help="strict / loose")
    p.add_argument("--symbols", required=True, help="逗号分隔的 6 位代码")
    p.add_argument("--limit", type=int, default=None, help="截断股票池规模")
    p.add_argument("--no-industry", action="store_true", help="跳过行业字段抓取（更快）")
    args = p.parse_args(argv)

    if args.model != selection_models.MODEL_A:
        print(f"当前仅实现模型A（--model strong）；未实现：{args.model}（模型B/C 不在本次范围）。",
              file=sys.stderr)
        return 2

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        print("未解析到有效 A 股代码。", file=sys.stderr)
        return 2

    config.assert_readonly()
    print(f"模型A 短线强势扫描｜模式 {args.mode}｜股票池 {len(symbols)} 只"
          f"{'（截断 ' + str(args.limit) + '）' if args.limit else ''}")

    source = AkshareDataSource()
    scanner = StockScanner(source, fetch_industry=not args.no_industry)

    def _prog(i, total, sym, passed):
        print(f"  [{i}/{total}] {sym} {'✓入选' if passed else '×未入选'}", flush=True)

    result = scanner.scan(symbols, mode=args.mode, limit=args.limit,
                          model=args.model, on_progress=_prog)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep_dir = config.output_dir("scan", "reports")
    exp_dir = config.output_dir("scan", "exports")
    rep_dir.mkdir(parents=True, exist_ok=True)
    exp_dir.mkdir(parents=True, exist_ok=True)

    md_path = rep_dir / f"strong_stock_scan_{ts}.md"
    csv_path = exp_dir / f"strong_stock_scan_{ts}.csv"
    md_path.write_text(result.to_markdown(), encoding="utf-8")
    result.to_dataframe().to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\n入选 {len(result.candidates)} / {result.universe_size} 只：")
    for r in result.candidates:
        m = r["metrics"]
        pct = "—" if m.get("pct_5d") is None else f"{m['pct_5d']*100:.2f}%"
        print(f"  #{r['rank']} {m['symbol']} {m.get('name') or '':<6} 综合分 {r['verdict'].score:.2f}｜近5日 {pct}")
    print(f"\n报告：{md_path}\n导出：{csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
