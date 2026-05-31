"""股票扫描器：编排「数据 → 指标 → 模型A 判定 → 排名 → 报告/CSV」。

只读：用 data.AkshareDataSource 取公开日K + 名称，绝不下单/接实盘/接交易接口。
输出研究候选清单，**不输出买入/卖出建议**（含禁词安全网 sanitize 兜底）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import config
from reporting.base import sanitize

from . import risk_plan, selection_models

_MIN_BARS = 20  # MA20 需要 20 根


def _is_st(name: str) -> bool:
    return "ST" in (name or "").upper()


def _delisting_risk(name: str) -> bool:
    n = (name or "").upper()
    return ("*ST" in n) or ("退" in (name or ""))


class StockScanner:
    def __init__(self, source, fetch_industry: bool = True):
        self.source = source
        self.fetch_industry = fetch_industry
        self._ind_cache: Dict[str, Optional[str]] = {}

    # ---------- 指标 ----------
    def _industry(self, symbol: str) -> Optional[str]:
        """行业/板块（best-effort）。取不到返回 None（报告显示「暂无数据」）。"""
        if not self.fetch_industry:
            return None
        if symbol in self._ind_cache:
            return self._ind_cache[symbol]
        ind = None
        try:
            import akshare as ak
            df = ak.stock_individual_info_em(symbol=symbol)
            if df is not None and not df.empty:
                kv = dict(zip(df["item"].astype(str), df["value"]))
                ind = str(kv.get("行业") or "").strip() or None
        except Exception:
            ind = None
        self._ind_cache[symbol] = ind
        return ind

    def _compute_metrics(self, symbol: str, name: str, hist: pd.DataFrame) -> Dict:
        m: Dict[str, Any] = {"symbol": symbol, "name": name,
                             "is_st": _is_st(name), "delisting_risk": _delisting_risk(name),
                             "industry": None, "board_strong": None, "insufficient": False}
        if hist is None or hist.empty or "close" not in hist.columns:
            m["insufficient"] = True
            return m
        df = hist.sort_values("date").reset_index(drop=True)
        close = pd.to_numeric(df["close"], errors="coerce")
        vol = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series(dtype=float)
        if close.dropna().shape[0] < _MIN_BARS:
            m["insufficient"] = True
            return m

        last = float(close.iloc[-1])
        m["close"] = round(last, 2)
        m["ma5"] = round(float(close.rolling(5).mean().iloc[-1]), 2)
        m["ma10"] = round(float(close.rolling(10).mean().iloc[-1]), 2)
        m["ma20"] = round(float(close.rolling(20).mean().iloc[-1]), 2)
        m["above_ma5"] = last >= m["ma5"]
        m["above_ma10"] = last >= m["ma10"]
        m["above_ma20"] = last >= m["ma20"]

        if close.dropna().shape[0] >= 6:
            base = float(close.iloc[-6])
            m["pct_5d"] = (last / base - 1.0) if base > 0 else None
        else:
            m["pct_5d"] = None

        if len(vol) >= 5 and not vol.iloc[-5:].isna().all():
            vt = float(vol.iloc[-1]); vma5 = float(vol.iloc[-5:].mean())
            m["vol_today"] = vt
            m["vol_ma5"] = round(vma5, 1)
            m["vol_ratio"] = round(vt / vma5, 3) if vma5 > 0 else None
        else:
            m["vol_today"] = m["vol_ma5"] = m["vol_ratio"] = None

        m["amount_today"] = float(pd.to_numeric(df["amount"], errors="coerce").iloc[-1]) \
            if "amount" in df.columns and pd.notna(pd.to_numeric(df["amount"], errors="coerce").iloc[-1]) else None
        m["turnover_rate"] = float(pd.to_numeric(df["turnover_rate"], errors="coerce").iloc[-1]) \
            if "turnover_rate" in df.columns and pd.notna(pd.to_numeric(df["turnover_rate"], errors="coerce").iloc[-1]) else None
        if "high" in df.columns:
            m["high_recent"] = round(float(pd.to_numeric(df["high"], errors="coerce").tail(20).max()), 2)

        m["industry"] = self._industry(symbol)
        # 板块近3日强弱：数据源暂不可得 → None（报告显示暂无数据，模型按中性处理）
        m["board_strong"] = None
        return m

    # ---------- 扫描 ----------
    def scan(self, symbols: List[str], mode: str = "loose", limit: Optional[int] = None,
             model: str = selection_models.MODEL_A,
             on_progress=None) -> "ScanResult":
        config.assert_readonly()
        if limit and limit > 0:
            symbols = symbols[:limit]
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

        candidates: List[Dict] = []
        rejected: List[Dict] = []
        for i, sym in enumerate(symbols, 1):
            bundle = self.source.get_bundle(sym, start, end)
            metrics = self._compute_metrics(sym, getattr(bundle, "name", ""), bundle.history)
            verdict = selection_models.evaluate_model_a(metrics, mode=mode)
            row = {"metrics": metrics, "verdict": verdict,
                   "risk_notes": risk_plan.build_risk_notes(metrics)}
            if verdict.passed:
                candidates.append(row)
            else:
                rejected.append(row)
            if on_progress:
                on_progress(i, len(symbols), sym, verdict.passed)

        candidates.sort(key=lambda r: r["verdict"].score, reverse=True)
        for rank, r in enumerate(candidates, 1):
            r["rank"] = rank
        return ScanResult(scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          model=model, mode=mode, universe_size=len(symbols),
                          candidates=candidates, rejected=rejected)


@dataclass
class ScanResult:
    scan_time: str
    model: str
    mode: str
    universe_size: int
    candidates: List[Dict] = field(default_factory=list)
    rejected: List[Dict] = field(default_factory=list)

    # ---------- 导出 ----------
    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in self.candidates:
            m, v = r["metrics"], r["verdict"]
            rows.append({
                "排名": r["rank"], "代码": m["symbol"], "名称": m.get("name") or "",
                "综合分": v.score, "近5日涨幅%": None if m.get("pct_5d") is None else round(m["pct_5d"] * 100, 2),
                "成交额(亿)": None if m.get("amount_today") is None else round(m["amount_today"] / 1e8, 2),
                "量比(今/5日均)": m.get("vol_ratio"),
                "收盘": m.get("close"), "MA5": m.get("ma5"), "MA10": m.get("ma10"), "MA20": m.get("ma20"),
                "站上MA5/10/20": f"{int(bool(m.get('above_ma5')))}/{int(bool(m.get('above_ma10')))}/{int(bool(m.get('above_ma20')))}",
                "换手率%": "暂无数据" if m.get("turnover_rate") is None else round(m["turnover_rate"], 2),
                "行业": m.get("industry") or "暂无数据",
                "板块近3日强弱": "暂无数据" if m.get("board_strong") is None else ("强" if m["board_strong"] else "弱"),
                "入选理由": "；".join(v.reasons),
                "风险提示": "；".join(r["risk_notes"]) or "—",
            })
        return pd.DataFrame(rows)

    def _reject_summary(self) -> List[str]:
        from collections import Counter
        c = Counter()
        for r in self.rejected:
            fails = r["verdict"].fails
            c[fails[0] if fails else "未知原因"] += 1
        return [f"{reason}（{n} 只）" for reason, n in c.most_common()]

    def to_markdown(self) -> str:
        mode_cn = {"strict": "strict（严格）", "loose": "loose（宽松）"}.get(self.mode, self.mode)
        p = [f"# 短线强势股扫描报告（模型A）", "",
             f"- 扫描时间：{self.scan_time}",
             f"- 模型：{self.model}（短线强势股模型A）",
             f"- 模式：{mode_cn}",
             f"- 市场：{config.ONLY_MARKET}（只读分析，不下单/不接实盘）",
             f"- 股票池数量：{self.universe_size}",
             f"- 入选候选数量：{len(self.candidates)}", ""]

        p.append("## 候选股排名\n")
        if self.candidates:
            p.append("| 排名 | 代码 | 名称 | 综合分 | 近5日涨幅 | 成交额 | 量比 | 收盘/MA5/10/20 | 换手率 | 行业 |")
            p.append("|---:|:---|:---|---:|---:|---:|---:|:---|---:|:---|")
            for r in self.candidates:
                m, v = r["metrics"], r["verdict"]
                pct = "—" if m.get("pct_5d") is None else f"{m['pct_5d']*100:.2f}%"
                amt = "—" if m.get("amount_today") is None else f"{m['amount_today']/1e8:.2f}亿"
                vr = "—" if m.get("vol_ratio") is None else f"{m['vol_ratio']:.2f}"
                tr = "暂无" if m.get("turnover_rate") is None else f"{m['turnover_rate']:.1f}%"
                ind = m.get("industry") or "暂无数据"
                mas = f"{m.get('close')}/{m.get('ma5')}/{m.get('ma10')}/{m.get('ma20')}"
                p.append(f"| {r['rank']} | {m['symbol']} | {m.get('name') or '—'} | {v.score:.2f} "
                         f"| {pct} | {amt} | {vr} | {mas} | {tr} | {ind} |")
        else:
            p.append("（本次无股票满足模型A条件。）")

        p.append("\n## 入选理由\n")
        for r in self.candidates:
            m, v = r["metrics"], r["verdict"]
            p.append(f"- **{m['symbol']} {m.get('name') or ''}**（综合分 {v.score:.2f}）：" + "；".join(v.reasons))
            if v.missing:
                p.append(f"  - 数据说明：{'；'.join(v.missing)}")
            if r["risk_notes"]:
                p.append(f"  - 个股风险点：{'；'.join(r['risk_notes'])}")
        if not self.candidates:
            p.append("（无）")

        p.append("\n## 未入选原因摘要\n")
        summ = self._reject_summary()
        if summ:
            for s in summ:
                p.append(f"- {s}")
        else:
            p.append("- 无未入选标的。")

        p.append("\n" + risk_plan.general_risk_text(self.model, self.mode))
        p.append(f"\n---\n> {config.DISCLAIMER}")
        return sanitize("\n".join(p))
