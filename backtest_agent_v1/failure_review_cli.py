"""失败案例复盘 CLI（只读已有回测明细，不重跑回测）。

用法：
  python -m backtest_agent_v1.failure_review_cli --pool tech_30_v2

输出：
  failure_review_reports/failure_review_<时间>.md
  failure_review_exports/failure_review_<时间>.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config

from . import failure_review as fr
from . import stock_pools


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="失败案例复盘（只读）")
    p.add_argument("--pool", default="tech_30_v2", choices=stock_pools.list_pools(),
                   help="复盘哪个池的回测（默认 tech_30_v2）")
    args = p.parse_args(argv)

    config.assert_readonly()
    rv = fr.review(args.pool)
    if rv.get("error"):
        print(rv["error"], file=sys.stderr)
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep = config.output_dir("failure_review", "reports")
    exp = config.output_dir("failure_review", "exports")
    rep.mkdir(parents=True, exist_ok=True)
    exp.mkdir(parents=True, exist_ok=True)
    md_path = rep / f"failure_review_{ts}.md"
    csv_path = exp / f"failure_review_{ts}.csv"
    md_path.write_text(fr.build_markdown(rv), encoding="utf-8")
    fr.losers_dataframe(rv).to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"失败复盘 {args.pool}｜来源 {rv['trades_path'].name}")
    print(f"总交易 {rv['n_total']}｜亏损 {rv['n_loss']}（{rv['n_loss']/rv['n_total']*100:.1f}%）")
    print("失败类型：" + "｜".join(f"{t} {c}" for t, c in
                              sorted(rv["type_counts"].items(), key=lambda kv: kv[1], reverse=True)))
    if rv["stock_rank"]:
        worst = rv["stock_rank"][0]
        print(f"亏损最多：{worst['代码']} {worst['名称'] or ''} 累计 {worst['累计亏损%']:.2f}%"
              f"（{worst['亏损交易数']}笔，主要 {worst['主要类型']}）")
    print(f"\n报告：{md_path}\n导出：{csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
