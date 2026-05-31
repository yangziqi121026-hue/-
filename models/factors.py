"""模型层具体因子（量价类纯函数，可逐日切片 → point-in-time 无前视）。

最小闭环用 3 个因子：动量 / 均线多头 / 量能温和度。约定分值越高越「值得观察」。
均为纯计算，输入已按 as_of 切片的历史K DataFrame。绝不输出买卖指令。
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .base import Factor

_VOL_SWEET = 1.2  # 量比 v5/v20 的理想温和放大


def slice_until(df: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """只保留 date <= as_of 的行（防前视核心）。"""
    if df is None or getattr(df, "empty", True) or "date" not in df.columns:
        return df if df is not None else pd.DataFrame()
    return df[df["date"] <= as_of].reset_index(drop=True)


def _closes(df: pd.DataFrame) -> Optional[pd.Series]:
    if df is None or df.empty or "close" not in df.columns:
        return None
    s = pd.to_numeric(df["close"], errors="coerce").dropna()
    return s if len(s) else None


class MomentumFactor(Factor):
    name = "momentum"

    def __init__(self, n: int = 60):
        self.n = n

    def compute(self, df: pd.DataFrame, as_of: str = "") -> Optional[float]:
        s = _closes(df)
        if s is None or len(s) < self.n + 1:
            return None
        base = float(s.iloc[-1 - self.n])
        return None if base <= 0 else float(s.iloc[-1]) / base - 1.0


class MABullFactor(Factor):
    name = "ma_bull"

    def compute(self, df: pd.DataFrame, as_of: str = "") -> Optional[float]:
        s = _closes(df)
        if s is None or len(s) < 60:
            return None
        ma5 = float(s.rolling(5).mean().iloc[-1])
        ma20 = float(s.rolling(20).mean().iloc[-1])
        ma60 = float(s.rolling(60).mean().iloc[-1])
        if ma20 <= 0 or ma60 <= 0:
            return None
        return (ma5 / ma20 - 1.0) + (ma20 / ma60 - 1.0)


class VolZoneFactor(Factor):
    name = "vol"

    def compute(self, df: pd.DataFrame, as_of: str = "") -> Optional[float]:
        if df is None or df.empty or "volume" not in df.columns:
            return None
        v = pd.to_numeric(df["volume"], errors="coerce").dropna()
        if len(v) < 20:
            return None
        v20 = float(v.iloc[-20:].mean())
        if v20 <= 0:
            return None
        return -abs(float(v.iloc[-5:].mean()) / v20 - _VOL_SWEET)


DEFAULT_FACTORS = [MomentumFactor(), MABullFactor(), VolZoneFactor()]
FACTOR_KEYS = tuple(f.name for f in DEFAULT_FACTORS)


def compute_all(df: pd.DataFrame, factors=None) -> Dict[str, Optional[float]]:
    factors = factors or DEFAULT_FACTORS
    out: Dict[str, Optional[float]] = {}
    for f in factors:
        try:
            out[f.name] = f.compute(df)
        except Exception:
            out[f.name] = None
    return out


def warning_flags(df: pd.DataFrame) -> Dict[str, bool]:
    """风险警示（用于研究分级，非交易指令）：近20日深跌 / 60日过热。"""
    flags = {"deep_drop_20d": False, "surge_60d": False}
    s = _closes(df)
    if s is not None and len(s) >= 21 and float(s.iloc[-21]) > 0:
        flags["deep_drop_20d"] = (float(s.iloc[-1]) / float(s.iloc[-21]) - 1.0) <= -0.15
    if s is not None and len(s) >= 61 and float(s.iloc[-61]) > 0:
        flags["surge_60d"] = (float(s.iloc[-1]) / float(s.iloc[-61]) - 1.0) >= 0.60
    return flags


def zscore(values: Dict[str, Optional[float]]) -> Dict[str, float]:
    """横截面 z-score；None / 全相同 / 单样本 → 0（中性）。"""
    pairs = [(k, v) for k, v in values.items()
             if v is not None and not (isinstance(v, float) and np.isnan(v))]
    out = {k: 0.0 for k in values}
    if len(pairs) < 2:
        return out
    arr = np.array([v for _, v in pairs], dtype=float)
    mu, sd = arr.mean(), arr.std()
    if sd <= 0:
        return out
    for k, v in pairs:
        out[k] = float((v - mu) / sd)
    return out
