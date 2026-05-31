"""data 层具体实现：AKShare 只读数据源（A股）。

只读——只调用 AKShare 的公开行情/成分接口，绝不调用任何下单/交易/实盘订阅接口。
任何子接口失败都降级（mock / 空），不抛出，保证无网络时也能跑通闭环。

实现 ReadOnlyDataSource 接口：validate_symbol / get_history / get_bundle / get_universe。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from .base import DataBundle, ReadOnlyDataSource

# pandas 3 / pyarrow 兼容（必须在 import akshare 前生效）
try:
    pd.set_option("future.infer_string", False)
    pd.set_option("mode.string_storage", "python")
except Exception:
    pass

_CODE_RE = re.compile(r"^\d{6}$")
_HIST_COLS = {
    "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
    "收盘": "close", "成交量": "volume", "成交额": "amount", "换手率": "turnover_rate",
}
_INDEX_ALIASES = {"hs300": "000300", "zz500": "000905", "sz50": "000016",
                  "000300": "000300", "000905": "000905", "000016": "000016"}
_MOCK_UNIVERSE = ["600519", "000858", "600036", "000001", "601318",
                  "600900", "000333", "600276", "300750", "002594"]


def _try_ak():
    try:
        import akshare as ak
        return ak
    except Exception:
        return None


def _is_a_share(code: str) -> bool:
    code = (code or "").strip()
    return bool(_CODE_RE.match(code)) and code[0] in ("6", "0", "3")


def _exchange_prefix(symbol: str) -> str:
    return {"6": "sh"}.get(symbol[:1], "sz") if symbol else ""


def _extract_codes(values) -> List[str]:
    out, seen = [], set()
    for v in values:
        m = re.search(r"\d{6}", str(v))
        code = m.group(0) if m else ""
        if _is_a_share(code) and code not in seen:
            seen.add(code)
            out.append(code)
    return out


class AkshareDataSource(ReadOnlyDataSource):
    """基于 AKShare 的只读 A股数据源。"""

    capabilities = ("history", "info", "universe")

    def __init__(self) -> None:
        config.assert_readonly()  # 启动自检：禁止下单/实盘
        self._name_cache: Dict[str, str] = {}
        self.last_universe_meta: Dict = {}

    # ---------- 校验 ----------
    def validate_symbol(self, symbol: str) -> bool:
        return _is_a_share((symbol or "").strip())

    # ---------- 名称 ----------
    def _load_names(self) -> Dict[str, str]:
        if self._name_cache:
            return self._name_cache
        ak = _try_ak()
        if ak is None:
            return {}
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and not df.empty:
                self._name_cache = dict(zip(df["code"].astype(str), df["name"].astype(str)))
        except Exception:
            pass
        return self._name_cache

    # ---------- 历史K ----------
    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        df = df.rename(columns={k: v for k, v in _HIST_COLS.items() if k in df.columns})
        for c in ("date", "open", "high", "low", "close", "volume"):
            if c not in df.columns:
                df[c] = np.nan
        try:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        except Exception:
            df["date"] = df["date"].astype(str)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        # 换手率：东财源「换手率」已是百分比（上面已重命名为 turnover_rate）；
        # 新浪源 stock_zh_a_daily 给的是 turnover（小数 = 成交量/流通股），×100 才是换手率%。
        if "turnover_rate" in df.columns:
            df["turnover_rate"] = pd.to_numeric(df["turnover_rate"], errors="coerce")
        elif "turnover" in df.columns:
            df["turnover_rate"] = pd.to_numeric(df["turnover"], errors="coerce") * 100
        return df.sort_values("date").reset_index(drop=True)

    def get_history(self, symbol: str, start: str, end: str, period: str = "daily") -> pd.DataFrame:
        symbol = (symbol or "").strip()
        s, e = start.replace("-", ""), end.replace("-", "")
        ak = _try_ak()
        if ak is None or not self.validate_symbol(symbol):
            return self._mock_history(symbol, start, end)
        # 1) 东财日K
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=s, end_date=e, adjust="")
            if df is not None and not df.empty:
                out = self._normalize(df)
                out.attrs["source"] = "stock_zh_a_hist（东财）"
                return out
        except Exception:
            pass
        # 2) 新浪日K
        try:
            df = ak.stock_zh_a_daily(symbol=_exchange_prefix(symbol) + symbol,
                                     adjust="", start_date=s, end_date=e)
            if df is not None and not df.empty:
                out = self._normalize(df)
                out.attrs["source"] = "stock_zh_a_daily（新浪）"
                return out
        except Exception:
            pass
        return self._mock_history(symbol, start, end)

    @staticmethod
    def _mock_history(symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            sd = datetime.strptime(start.replace("-", ""), "%Y%m%d")
            ed = datetime.strptime(end.replace("-", ""), "%Y%m%d")
        except Exception:
            ed = datetime.now(); sd = ed - timedelta(days=365)
        if ed <= sd:
            ed = sd + timedelta(days=200)
        dates = pd.date_range(sd, ed, freq="B")
        n = len(dates)
        if n == 0:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        rng = np.random.default_rng(abs(hash(symbol)) % (2 ** 32))
        closes, p = [], 30.0
        for r in rng.normal(0, 0.015, size=n):
            p = max(1.0, p * (1 + r)); closes.append(round(p, 2))
        closes = np.array(closes)
        df = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": np.round(closes * 0.99, 2), "high": np.round(closes * 1.01, 2),
            "low": np.round(closes * 0.98, 2), "close": closes,
            "volume": rng.integers(1_000_000, 9_000_000, size=n).astype(float),
        })
        df.attrs["is_mock"] = True
        df.attrs["source"] = "mock（akshare 不可用或代码非法）"
        return df

    # ---------- 数据包 ----------
    def get_bundle(self, symbol: str, start: str = "", end: str = "") -> DataBundle:
        end = end or datetime.now().strftime("%Y-%m-%d")
        start = start or (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        hist = self.get_history(symbol, start, end)
        names = self._load_names()
        b = DataBundle(symbol=symbol, name=names.get(symbol, ""), history=hist)
        src = (getattr(hist, "attrs", {}) or {}).get("source", "")
        if src:
            b.sources.append(src)
        b.data_quality["price_data"] = "mock" if (getattr(hist, "attrs", {}) or {}).get("is_mock") \
            else ("ok" if hist is not None and not hist.empty else "failed")
        return b.stamp()

    # ---------- 股票池 ----------
    def _index_cons(self, ak, index_code: str) -> Tuple[List[str], Dict[str, str]]:
        for fn, kw in ((getattr(ak, "index_stock_cons_csindex", None), {"symbol": index_code}),
                       (getattr(ak, "index_stock_cons", None), {"symbol": index_code})):
            if fn is None:
                continue
            try:
                df = fn(**kw)
                if df is None or df.empty:
                    continue
                col = next((c for c in ["成分券代码", "品种代码", "证券代码", "code"] if c in df.columns), None)
                ncol = next((c for c in ["成分券名称", "品种名称", "证券简称", "name"] if c in df.columns), None)
                if not col:
                    continue
                codes = _extract_codes(df[col].tolist())
                nmap = {}
                if ncol:
                    for _, row in df.iterrows():
                        m = re.search(r"\d{6}", str(row.get(col, "")))
                        if m:
                            nmap[m.group(0)] = str(row.get(ncol, "")).strip()
                if codes:
                    return codes, nmap
            except Exception:
                continue
        return [], {}

    def resolve_universe(self, spec: str, limit: Optional[int] = None) -> Dict:
        """解析 universe → {codes, name_map, source, is_mock}。供报告/批量使用。"""
        import os
        spec = (spec or "hs300").strip()
        name_map: Dict[str, str] = {}
        is_mock = False
        key = spec.lower()
        if key in _INDEX_ALIASES:
            ak = _try_ak()
            codes, name_map = ([], {})
            if ak is not None:
                codes, name_map = self._index_cons(ak, _INDEX_ALIASES[key])
            if not codes:
                codes, is_mock = list(_MOCK_UNIVERSE), True
            source = f"指数成分:{_INDEX_ALIASES[key]}" + ("（mock 兜底）" if is_mock else "")
        elif os.path.exists(spec):
            with open(spec, "r", encoding="utf-8") as f:
                lines = [ln.split("#", 1)[0].strip() for ln in f]
            codes = _extract_codes([x for x in lines if x])
            source = f"自定义清单:{os.path.basename(spec)}"
        else:
            codes = _extract_codes(re.split(r"[,\s]+", spec))
            if codes:
                source = "代码串"
            else:
                codes, is_mock, source = list(_MOCK_UNIVERSE), True, "无法识别（mock 兜底）"
        if limit and limit > 0:
            codes = codes[:limit]
        self.last_universe_meta = {"codes": codes, "name_map": name_map,
                                   "source": source, "is_mock": is_mock, "count": len(codes)}
        return self.last_universe_meta

    def get_universe(self, spec: str) -> List[str]:
        return self.resolve_universe(spec)["codes"]
