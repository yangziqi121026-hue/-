"""候选股观察计划 CLI（只读，不出买卖建议）。

用法：
  python -m backtest_agent_v1.observation_plan_cli --pool tech_30_v2 --mode loose

输出：
  observation_reports/observation_plan_<pool>_<时间>.md
  observation_exports/observation_plan_<pool>_<时间>.csv
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
from data import AkshareDataSource

from . import observation_plan as op
from . import selection_models, stock_pools


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="候选股观察计划（只读，非买卖建议）")
    p.add_argument("--pool", default=op.DEFAULT_POOL, choices=stock_pools.list_pools(),
                   help=f"观察池（默认 {op.DEFAULT_POOL}）")
    p.add_argument("--mode", default="loose", choices=list(selection_models.MODES))
    args = p.parse_args(argv)

    config.assert_readonly()
    source = AkshareDataSource()
    print(f"候选观察计划｜池 {args.pool}｜模型A/{args.mode}（扫描中…）")

    def _prog(i, total, sym, passed):
        if passed:
            print(f"  命中 {sym}", flush=True)

    plan = op.build_plan(source, pool=args.pool, mode=args.mode, on_progress=_prog)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep = config.output_dir("observation", "reports")
    exp = config.output_dir("observation", "exports")
    rep.mkdir(parents=True, exist_ok=True)
    exp.mkdir(parents=True, exist_ok=True)
    md_path = rep / f"observation_plan_{args.pool}_{ts}.md"
    csv_path = exp / f"observation_plan_{args.pool}_{ts}.csv"
    md_path.write_text(op.build_markdown(plan), encoding="utf-8")
    op.plan_dataframe(plan).to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\n命中候选 {plan['n']} / {plan['universe_size']} 只：")
    for pl in plan["plans"]:
        print(f"  #{pl['排名']} {pl['代码']} {pl['名称'] or '':<6} 收盘 {op._fp(pl['当前收盘价'])}"
              f"｜观察位 {op._fp(pl['观察位'])}｜止损参考 {op._fp(pl['止损参考位'])}｜[{pl['观察分级']}]")
    print(f"\n报告：{md_path}\n导出：{csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
