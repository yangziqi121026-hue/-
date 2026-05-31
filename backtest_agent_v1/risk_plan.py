"""风险提示生成（纯定性，研究口径）。

明确边界：本模块只产出**定性风险警示**用于研究参考，
**绝不输出止损位/止盈位/目标价/仓位/买卖指令**。短线强势股波动天然较大，
这些提示用于提醒研究者关注风险，不构成任何投资建议。
"""

from __future__ import annotations

from typing import Dict, List

# 触发阈值（仅用于生成定性提示）
_SURGE_5D = 0.20        # 近5日涨幅过大
_VOL_BLOWOFF = 3.0      # 放量过猛
_HIGH_TURNOVER = 15.0   # 换手率过高（%）
_NEAR_HIGH = 0.97       # 接近近期高点


def build_risk_notes(metrics: Dict) -> List[str]:
    """针对单只候选股给出定性风险点（可能为空）。"""
    notes: List[str] = []
    pct5 = metrics.get("pct_5d")
    if pct5 is not None and pct5 >= _SURGE_5D:
        notes.append(f"近5日已涨 {pct5*100:.1f}%，短期涨幅较大，注意追高与回调风险")
    vr = metrics.get("vol_ratio")
    if vr is not None and vr >= _VOL_BLOWOFF:
        notes.append(f"今日量能达5日均量 {vr:.1f} 倍，放量过猛，警惕情绪化资金与冲高回落")
    tr = metrics.get("turnover_rate")
    if tr is not None and tr >= _HIGH_TURNOVER:
        notes.append(f"换手率 {tr:.1f}%，交投过热，分歧加大")
    close, hi = metrics.get("close"), metrics.get("high_recent")
    if close and hi and hi > 0 and close / hi >= _NEAR_HIGH:
        notes.append("已接近近期高点，存在上方套牢/压力风险")
    if metrics.get("board_strong") is None:
        notes.append("板块数据暂无，无法判断板块联动，结论确定性下降")
    return notes


def general_risk_text(model: str, mode: str) -> str:
    """报告级通用风险提示段落（不含任何买卖指令）。"""
    return (
        "## 风险提示\n\n"
        f"- 本扫描为「{model}/{mode}」研究筛选，入选仅表示**当前满足该模型的量价特征**，"
        "不代表未来走势，更**不构成任何买入/卖出建议**。\n"
        "- 短线强势股波动大、回撤快，量价指标具滞后性，可能在入选后迅速逆转。\n"
        "- 成交额/放量可能由情绪化或事件性资金驱动，持续性不确定。\n"
        "- 数据来源于公开行情接口，可能存在缺失/延迟；标注「暂无数据」处确定性下降。\n"
        "- 本系统只读、不接实盘、不下单，所有结论仅供研究学习，风险自负。"
    )
