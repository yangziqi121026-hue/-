"""报告层基类 + 交易指令禁词安全网（基础实现）。

sanitize 是底线安全网：把任何遗漏的交易指令字样软化为研究口径，
两阶段占位符替换保证幂等且不嵌套包裹。报告模板本身只用 4 档研究分级。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

import config

_WRAPPED_RE = re.compile(r"（已移除交易指令：.*?）")

# 交易指令禁词表（与工作区既定口径一致）
FORBIDDEN_WORDS: List[str] = [
    "必须买入", "必须卖出", "建议买入", "建议卖出", "立即买入", "立即卖出",
    "满仓", "清仓", "加仓", "减仓", "买入信号", "卖出信号",
    "做多", "做空", "强烈推荐", "立即满仓", "梭哈", "逢低买入", "逢高减持",
    "BUY", "SELL", "建议入场价", "止损位", "止盈位", "建议止损", "建议止盈",
    "目标买价", "目标卖价",
]


def sanitize(text: str) -> str:
    """把交易指令字样软化为「（已移除交易指令：原词）」。长词优先 + 幂等，杜绝嵌套包裹。

    幂等性：先把「已存在的软化标记」整体藏成占位，避免其内部的原词被二次包裹，
    扫描结束再还原——这样对已软化过的文本再调用一次结果不变。
    """
    out = text or ""

    # 1) 保护已存在的软化标记（防止跨次调用时内部原词被再次包裹）
    stash: List[str] = []

    def _stash(m):
        stash.append(m.group(0))
        return f"\x00E{len(stash) - 1}\x00"

    out = _WRAPPED_RE.sub(_stash, out)

    # 2) 两阶段占位符替换：长词优先，避免「满仓」先于「立即满仓」命中
    pending: List = []
    for i, w in enumerate(sorted(FORBIDDEN_WORDS, key=len, reverse=True)):
        if w in out:
            placeholder = f"\x00S{i}\x00"
            pending.append((placeholder, f"（已移除交易指令：{w}）"))
            out = out.replace(w, placeholder)
    for placeholder, wrapped in pending:
        out = out.replace(placeholder, wrapped)

    # 3) 还原被保护的已有标记
    for i, frag in enumerate(stash):
        out = out.replace(f"\x00E{i}\x00", frag)
    return out


class ReportBuilder(ABC):
    """报告模板基类。各业务域继承并实现 build()，统一带头部 + 免责 + 禁词安全网。"""

    title: str = "研究报告"

    def header(self, meta: Dict[str, Any]) -> str:
        """统一报告头部：标题 + 生成时间 + 市场 + 数据来源。"""
        now = meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"# {self.title}", "",
                 f"- 生成时间：{now}",
                 f"- 市场：{config.ONLY_MARKET}（只读分析，不下单/不接实盘）"]
        if meta.get("data_source"):
            lines.append(f"- 数据来源：{meta['data_source']}")
        lines.append("")
        return "\n".join(lines)

    def footer(self) -> str:
        return f"\n---\n> {config.DISCLAIMER}"

    @abstractmethod
    def build(self, payload: Any, meta: Dict[str, Any]) -> str:
        """渲染报告正文（子类实现）。返回前应整体过一遍 sanitize。"""
        raise NotImplementedError

    def finalize(self, body: str) -> str:
        """统一收尾：拼免责 + 过禁词安全网。"""
        return sanitize(body + self.footer())
