"""选股清单报告（研究分级，非买卖指令）。"""

from __future__ import annotations

from typing import Any, Dict

from .base import ReportBuilder


class ScreenReport(ReportBuilder):
    title = "A股多因子选股清单"

    def build(self, payload: Any, meta: Dict[str, Any]) -> str:
        res = payload  # models.base.ScreenResult
        parts = [self.header(meta)]
        parts.append(f"as_of：{res.as_of}　|　入选 {len(res.selected)} 只　|　评分 {len(res.ranked)} 只\n")
        parts.append("> 以下为基于公开历史量价数据的**多因子研究排序**，标签为「观察/谨慎关注/"
                     "暂不参与/高风险」四档研究分级，**不构成任何买卖建议**。\n")
        parts.append("| 排名 | 代码 | 名称 | 综合分 | 研究分级 | 警示 |")
        parts.append("|---:|:---|:---|---:|:---:|:---|")
        sel = set(res.selected)
        for r in res.ranked:
            if r["symbol"] not in sel:
                continue
            warn = "、".join(r["warnings"]) if r["warnings"] else "—"
            parts.append(f"| {r['rank']} | {r['symbol']} | {r['name'] or '—'} "
                         f"| {r['composite']:.3f} | {r['grade']} | {warn} |")
        if res.insufficient:
            parts.append(f"\n数据不足（不纳入排名，{len(res.insufficient)} 只）："
                         + "、".join(f"{x['symbol']}({x['bars']}根)" for x in res.insufficient[:40]))
        parts.append("\n因子：动量(60日涨幅) / 均线多头(MA5/20/60) / 量能(量比距1.2)；"
                     "综合分 = 各因子横截面 z-score 等权和。")
        return self.finalize("\n".join(parts))
