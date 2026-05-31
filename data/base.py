"""数据层基类与数据结构（骨架，无具体实现）。

约定：所有数据获取都是**只读**的，返回的数据块都应带 source（来源）与 fetched_at（抓取时间）。
任何子类都不得实现下单/交易/实盘订阅；如需新数据维度，扩展 ReadOnlyDataSource 的只读方法即可。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class DataBundle:
    """单只标的的标准化数据包（占位结构，字段后续按需填充）。"""

    symbol: str
    market: str = "A股"
    name: str = ""
    history: Any = None                       # 历史K线（pandas.DataFrame，后续实现）
    info: Dict[str, Any] = field(default_factory=dict)        # 基础信息/估值
    financials: Dict[str, Any] = field(default_factory=dict)  # 财务
    capital_flow: Dict[str, Any] = field(default_factory=dict)  # 资金面
    news: List[Dict[str, Any]] = field(default_factory=list)  # 消息面
    sources: List[str] = field(default_factory=list)          # 数据来源摘要
    fetched_at: str = ""
    data_quality: Dict[str, str] = field(default_factory=dict)  # 各块质量标注

    def stamp(self) -> "DataBundle":
        """补抓取时间（缺失时填当前时刻）。"""
        if not self.fetched_at:
            self.fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self


class ReadOnlyDataSource(ABC):
    """只读数据源接口。实现类只能「读」，不得有任何写/下单/交易能力。"""

    #: 数据源可读维度（子类可覆盖）
    capabilities: tuple = ("history", "info", "financials", "capital_flow", "news")

    @abstractmethod
    def validate_symbol(self, symbol: str) -> bool:
        """校验代码是否为受支持的沪深 A 股。"""
        raise NotImplementedError

    @abstractmethod
    def get_history(self, symbol: str, start: str, end: str, period: str = "daily") -> Any:
        """取历史K线（标准化 DataFrame）。只读。"""
        raise NotImplementedError

    @abstractmethod
    def get_bundle(self, symbol: str, start: str = "", end: str = "") -> DataBundle:
        """取单只标的的完整标准化数据包。只读。"""
        raise NotImplementedError

    def get_universe(self, spec: str) -> List[str]:
        """解析股票池（指数成分/清单/代码串）→ 代码列表。默认未实现。"""
        raise NotImplementedError
