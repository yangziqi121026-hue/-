"""模型层（models）：因子、打分、策略/选股规则。

职责：把数据层的标准化数据转成研究信号（因子值、综合分、研究分级）。
输出**只用于研究排序与回测**，绝不产出买卖指令或目标价。

当前为基础骨架：仅定义接口，具体因子/策略实现待填充。
"""

from .base import Factor, ScreenResult, Strategy
from .strategy import MultiFactorStrategy

__all__ = ["Factor", "Strategy", "ScreenResult", "MultiFactorStrategy"]
