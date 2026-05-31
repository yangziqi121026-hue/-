"""模型层基类（骨架，无具体实现）。

纪律：
- 因子/策略只用 `截止某日（as_of）` 的数据计算，保证 point-in-time、可回测、无前视。
- 选股结果用 4 档研究分级（观察/谨慎关注/暂不参与/高风险），**不输出买卖指令**。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class Factor(ABC):
    """单因子接口。输入「已按 as_of 切片」的数据，输出一个分值或 None（数据不足）。"""

    #: 因子名（子类覆盖）
    name: str = "factor"

    @abstractmethod
    def compute(self, bundle: Any, as_of: str) -> Optional[float]:
        """计算因子原始值（约定：越高越「值得观察」）。只读、纯计算。"""
        raise NotImplementedError


@dataclass
class ScreenResult:
    """选股结果（占位结构）。"""

    as_of: str
    ranked: List[Dict[str, Any]] = field(default_factory=list)   # 按综合分降序
    selected: List[str] = field(default_factory=list)            # 入选代码（top_n）
    insufficient: List[Dict[str, Any]] = field(default_factory=list)  # 数据不足，标「不足以判断」
    weights: Dict[str, float] = field(default_factory=dict)


class Strategy(ABC):
    """选股策略接口：在 as_of 这天对股票池打分排名并选出 top_n。"""

    name: str = "strategy"

    @abstractmethod
    def select(self, bundles: Dict[str, Any], as_of: str, top_n: int = 20) -> ScreenResult:
        """打分 → 排名 → 选 top_n。只用 date <= as_of 的数据（防前视）。"""
        raise NotImplementedError

    def grade(self, signals: Dict[str, Any]) -> str:
        """把信号映射到 4 档研究分级（默认未实现，子类按需覆盖）。"""
        raise NotImplementedError
