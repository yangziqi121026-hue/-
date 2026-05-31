"""回测报告（历史净值复盘，非投资建议）。"""

from __future__ import annotations

import math
from typing import Any, Dict

from .base import ReportBuilder


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "不足以判断"
    return f"{v * 100:.2f}%"


def _num(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "不足以判断"
    return f"{v:.2f}"


class BacktestReport(ReportBuilder):
    title = "A股选股策略回测报告"

    def build(self, payload: Any, meta: Dict[str, Any]) -> str:
        bt = payload.get("bt", {})
        sm = payload.get("summary", {})
        if bt.get("error"):
            return self.finalize(self.header(meta) + f"\n**回测失败**：{bt['error']}")

        parts = [self.header(meta)]
        parts.append("> 对「多因子选股规则」的**历史净值复盘**：等权买入持有、按周期调仓、已计入交易成本。"
                     "历史表现不代表未来，**不构成任何投资建议**。\n")
        parts.append("## 回测设置\n")
        parts.append(f"- 区间：{bt.get('calendar_start')} ~ {bt.get('calendar_end')}")
        parts.append(f"- 调仓：{bt.get('freq')}，每期 {bt.get('top_n')} 只等权，共 {bt.get('n_rebalances')} 次")
        parts.append(f"- 交易成本：{'计入（佣金万3双边+印花税千1卖出）' if bt.get('cost_enabled') else '未计入'}")

        parts.append("\n## 绩效指标\n")
        parts.append("| 指标 | 组合 | 基准 |")
        parts.append("|:---|---:|---:|")
        parts.append(f"| 累计收益 | {_pct(sm.get('total_return'))} | {_pct(sm.get('benchmark_total_return'))} |")
        parts.append(f"| 年化收益 | {_pct(sm.get('annualized_return'))} | {_pct(sm.get('benchmark_annualized_return'))} |")
        parts.append(f"| 年化波动 | {_pct(sm.get('annualized_vol'))} | — |")
        parts.append(f"| 夏普 | {_num(sm.get('sharpe'))} | — |")
        parts.append(f"| 最大回撤 | {_pct(sm.get('max_drawdown'))} | — |")
        parts.append(f"| 周期胜率 | {_pct(sm.get('win_rate'))} | — |")
        if sm.get("excess_annualized") is not None:
            parts.append(f"| 年化超额 | {_pct(sm.get('excess_annualized'))} | — |")

        parts.append("\n## 逐期持仓\n")
        parts.append("| 建仓日 | 调仓日 | 持仓数 | 当期收益 | 换手 |")
        parts.append("|:---|:---|---:|---:|---:|")
        for h in bt.get("holdings", []):
            parts.append(f"| {h['entry']} | {h['exit']} | {len(h['selected'])} "
                         f"| {_pct(h['period_return'])} | {_pct(h['turnover'])} |")
        return self.finalize("\n".join(parts))
