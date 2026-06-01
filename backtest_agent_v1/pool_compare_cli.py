"""股票池横向对比报告 CLI（只汇总已有回测结果，不重新跑回测）。

用法：
  python -m backtest_agent_v1.pool_compare_cli

输出：
  pool_compare_reports/pool_compare_<时间>.md
  pool_compare_exports/pool_compare_<时间>.csv

只读：不接实盘、不下单、不接交易接口、不出买卖建议。
"""

from __future__ import annotations

import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config

from . import pool_compare as pc


def main(argv=None) -> int:
    config.assert_readonly()
    comp = pc.build_comparison()

    if comp["n_have"] == 0:
        print("selection_backtest_exports 下没有可用的 summary CSV，无法对比。"
              "请先用 selection_backtest_cli 跑回测。", file=sys.stderr)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep = config.output_dir("pool_compare", "reports")
    exp = config.output_dir("pool_compare", "exports")
    rep.mkdir(parents=True, exist_ok=True)
    exp.mkdir(parents=True, exist_ok=True)

    md_path = rep / f"pool_compare_{ts}.md"
    csv_path = exp / f"pool_compare_{ts}.csv"
    md_path.write_text(pc.build_markdown(comp), encoding="utf-8")
    pc.comparison_dataframe(comp).to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"股票池横向对比｜有数据池 {comp['n_have']} 个｜尚未回测 {comp['n_missing']} 个")
    for r in sorted([x for x in comp["rows"] if x["数据状态"].startswith("已回测")],
                    key=lambda x: x.get("排名", 999)):
        print(f"  #{r.get('排名')} {r['股票池']:<12} 综合分 {r.get('综合分')}"
              f"｜年化 {pc._fmt('年化收益率', r.get('年化收益率'))}"
              f"｜收益/回撤比 {pc._fmt('收益/回撤比', r.get('收益/回撤比'))}"
              f"｜盈亏比 {pc._fmt('盈亏比', r.get('盈亏比'))}")
    if comp["best"]:
        print(f"\n当前最佳适配池：{comp['best']}" + ("（仅1池有数据，占位）" if comp["n_have"] < 2 else ""))
    print(f"\n报告：{md_path}\n导出：{csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
