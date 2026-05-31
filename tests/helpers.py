"""测试公共构造（合成数据，不联网）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

from data.base import DataBundle


def make_df(closes: List[float], start: str = "2023-01-01", volume: float = 1_000_000) -> pd.DataFrame:
    dates = [(datetime.strptime(start, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
             for i in range(len(closes))]
    return pd.DataFrame({
        "date": dates, "open": closes,
        "high": [c * 1.01 for c in closes], "low": [c * 0.99 for c in closes],
        "close": closes, "volume": [float(volume)] * len(closes),
    })


def make_bundle(symbol: str, closes: List[float], name: str = "", start: str = "2023-01-01") -> DataBundle:
    return DataBundle(symbol=symbol, name=name, history=make_df(closes, start=start)).stamp()
