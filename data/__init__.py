"""数据层（data）：只读数据获取与标准化。

职责：从公开数据源（如 AKShare）取行情/财务/资金/消息等，标准化为统一结构，
并标注数据来源与抓取时间。**只读**——绝不调用任何下单/交易/实盘订阅接口。

当前为基础骨架：仅定义接口与数据结构，具体 provider 实现待填充。
"""

from .akshare_source import AkshareDataSource
from .base import DataBundle, ReadOnlyDataSource

__all__ = ["DataBundle", "ReadOnlyDataSource", "AkshareDataSource"]
