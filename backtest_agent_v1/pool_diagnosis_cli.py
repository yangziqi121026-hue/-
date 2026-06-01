"""股票池成分贡献诊断 CLI（只读已有回测明细，不重跑回测）。

用法：
  python -m backtest_agent_v1.pool_diagnosis_cli --pool tech_30

输出：
  pool_diagnosis_reports/pool_diagnosis_<pool>_<时间>.md
  pool_diagnosis_exports/pool_diagnosis_<pool>_<时间>.csv

只读：不接实盘、不下单、不接交易接口、不出买卖建议。
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

from . import pool_diagnosis as pd_diag
from . import stock_pools


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="股票池成分贡献诊断（只读）")
    p.add_argument("--pool", default="tech_30", choices=stock_pools.list_pools(),
                   help="诊断哪个预设池（默认 tech_30）")
    args = p.parse_args(argv)

    config.assert_readonly()
    diag = pd_diag.diagnose(args.pool)
    if diag.get("error"):
        print(diag["error"], file=sys.stderr)
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep = config.output_dir("pool_diagnosis", "reports")
    exp = config.output_dir("pool_diagnosis", "exports")
    rep.mkdir(parents=True, exist_ok=True)
    exp.mkdir(parents=True, exist_ok=True)

    md_path = rep / f"pool_diagnosis_{args.pool}_{ts}.md"
    csv_path = exp / f"pool_diagnosis_{args.pool}_{ts}.csv"
    md_path.write_text(pd_diag.build_markdown(diag), encoding="utf-8")
    pd_diag.diagnosis_dataframe(diag).to_csv(csv_path, index=False, encoding="utf-8-sig")

    c = diag["counts"]
    print(f"诊断 {args.pool}｜来源 {diag['trades_path'].name}")
    print(f"成分有交易 {diag['n_total']} 只｜保留 {c['保留']} · 观察 {c['观察']} · 踢出 {c['踢出']}"
          f"｜未交易 {c['未交易']}")
    eject = [r for r in diag["rows"] if r["建议"] == "踢出"]
    if eject:
        print("建议踢出：")
        for r in eject:
            print(f"  {r['代码']} {r['名称'] or '':<6} 贡献 {pd_diag._fmt('总收益贡献', r['总收益贡献'])}"
                  f"｜{r['建议理由']}")
    print(f"\n报告：{md_path}\n导出：{csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
