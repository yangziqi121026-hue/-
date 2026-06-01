"""系统1 只读 Dashboard（本地网页，仅 GET）。

用标准库 http.server 实现，**只定义 do_GET**——POST/PUT/DELETE 等会被基类自动拒绝（501），
从机制上保证「只读、无写入、无交易接口」。展示最新 scan_exports 扫描结果。

严格边界：
- 不接实盘、不下单、不接 Alpaca/OKX、不输出买入/卖出建议。
- 无任何 POST/PUT/DELETE 路由、无交易按钮、无表单提交。
- 只读取本地 scan_reports / scan_exports 下的既有产物并展示。
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import pandas as pd

import config

_HERE = Path(__file__).resolve().parent
_TEMPLATE = _HERE / "web_templates" / "base.html"
_STATIC = _HERE / "web_static"

_SCAN_REPORTS = config.output_dir("scan", "reports")
_SCAN_EXPORTS = config.output_dir("scan", "exports")
_CSV_GLOB = "strong_stock_scan_*.csv"
_MD_GLOB = "strong_stock_scan_*.md"

_SB_REPORTS = config.output_dir("selection_backtest", "reports")
_SB_EXPORTS = config.output_dir("selection_backtest", "exports")
_SB_CHARTS = config.output_dir("selection_backtest", "charts")

_PC_REPORTS = config.output_dir("pool_compare", "reports")
_PC_EXPORTS = config.output_dir("pool_compare", "exports")

_PD_REPORTS = config.output_dir("pool_diagnosis", "reports")
_PD_EXPORTS = config.output_dir("pool_diagnosis", "exports")

_OB_REPORTS = config.output_dir("observation", "reports")
_OB_EXPORTS = config.output_dir("observation", "exports")

_FR_REPORTS = config.output_dir("failure_review", "reports")
_FR_EXPORTS = config.output_dir("failure_review", "exports")

# 外部 Streamlit 只读看板地址（嵌入用；本服务不托管、不迁移 Streamlit）
STREAMLIT_URL = "http://127.0.0.1:8501"


# =====================================================
# 数据读取（只读本地产物）
# =====================================================

def _latest(path: Path, pattern: str) -> Optional[Path]:
    files = sorted(path.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True) \
        if path.exists() else []
    return files[0] if files else None


def _token_of(p: Path) -> str:
    m = re.search(r"(\d{8}_\d{6})", p.name)
    return m.group(1) if m else ""


def _matching_md(token: str) -> Optional[Path]:
    if token:
        cand = _SCAN_REPORTS / f"strong_stock_scan_{token}.md"
        if cand.exists():
            return cand
    return _latest(_SCAN_REPORTS, _MD_GLOB)


def _parse_md_meta(md: str) -> Dict[str, str]:
    meta = {}
    for key in ("扫描时间", "模型", "模式", "股票池数量", "入选候选数量"):
        m = re.search(rf"-\s*{key}[:：]\s*([^\n]+)", md)
        if m:
            meta[key] = m.group(1).strip()
    return meta


def _md_section(md: str, header: str) -> str:
    """提取 '## header' 到下一个 '## ' 之间的正文。"""
    m = re.search(rf"##\s*{re.escape(header)}\s*\n(.*?)(?=\n##\s|\Z)", md, re.S)
    return m.group(1).strip() if m else ""


def load_latest_scan() -> Optional[Dict]:
    csv = _latest(_SCAN_EXPORTS, _CSV_GLOB)
    if csv is None:
        return None
    token = _token_of(csv)
    md_path = _matching_md(token)
    md_text = md_path.read_text(encoding="utf-8") if md_path else ""
    try:
        df = pd.read_csv(csv, encoding="utf-8-sig")
    except Exception:
        df = pd.DataFrame()
    return {
        "csv_path": csv, "md_path": md_path, "token": token,
        "df": df, "md_text": md_text,
        "meta": _parse_md_meta(md_text),
        "reject_summary": _md_section(md_text, "未入选原因摘要"),
        "general_risk": _md_section(md_text, "风险提示"),
    }


def load_latest_selection_backtest() -> Optional[Dict]:
    summ = _latest(_SB_EXPORTS, "modelA_selection_summary_*.csv")
    if summ is None:
        return None
    token = _token_of(summ)
    trades = _SB_EXPORTS / f"modelA_selection_trades_{token}.csv"
    md = _SB_REPORTS / f"modelA_selection_backtest_{token}.md"
    chart = _SB_CHARTS / f"modelA_selection_equity_{token}.png"

    def _read(p: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(p, encoding="utf-8-sig") if p.exists() else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    return {
        "token": token, "summary_path": summ,
        "trades_path": trades if trades.exists() else None,
        "md_path": md if md.exists() else None,
        "chart_path": chart if chart.exists() else None,
        "summary_df": _read(summ), "trades_df": _read(trades),
        "md_text": md.read_text(encoding="utf-8") if md.exists() else "",
    }


def load_latest_pool_compare() -> Optional[Dict]:
    csv = _latest(_PC_EXPORTS, "pool_compare_*.csv")
    if csv is None:
        return None
    token = _token_of(csv)
    md = _PC_REPORTS / f"pool_compare_{token}.md"
    try:
        df = pd.read_csv(csv, encoding="utf-8-sig")
    except Exception:
        df = pd.DataFrame()
    md_text = md.read_text(encoding="utf-8") if md.exists() else ""
    return {"token": token, "csv_path": csv, "md_path": md if md.exists() else None,
            "df": df, "md_text": md_text,
            "conclusion": _md_section(md_text, "结论（数据驱动）")}


def load_latest_pool_diagnosis() -> Optional[Dict]:
    csv = _latest(_PD_EXPORTS, "pool_diagnosis_*.csv")
    if csv is None:
        return None
    token = _token_of(csv)
    m = re.search(r"pool_diagnosis_(.+?)_\d{8}_\d{6}", csv.name)
    pool = m.group(1) if m else "?"
    mds = sorted(_PD_REPORTS.glob(f"pool_diagnosis_*_{token}.md"))
    md = mds[0] if mds else None
    try:
        df = pd.read_csv(csv, encoding="utf-8-sig", dtype={"代码": str})
    except Exception:
        df = pd.DataFrame()
    md_text = md.read_text(encoding="utf-8") if md else ""
    return {"token": token, "pool": pool, "csv_path": csv,
            "md_path": md if md else None, "df": df, "md_text": md_text,
            "watch": _md_section(md_text, "替补候选观察名单（成分内未被选中交易的标的）")}


def load_latest_observation_plan() -> Optional[Dict]:
    csv = _latest(_OB_EXPORTS, "observation_plan_*.csv")
    if csv is None:
        return None
    token = _token_of(csv)
    m = re.search(r"observation_plan_(.+?)_\d{8}_\d{6}", csv.name)
    pool = m.group(1) if m else "?"
    mds = sorted(_OB_REPORTS.glob(f"observation_plan_*_{token}.md"))
    md = mds[0] if mds else None
    try:
        df = pd.read_csv(csv, encoding="utf-8-sig", dtype={"代码": str})
    except Exception:
        df = pd.DataFrame()
    return {"token": token, "pool": pool, "csv_path": csv,
            "md_path": md if md else None, "df": df,
            "md_text": md.read_text(encoding="utf-8") if md else ""}


def load_latest_failure_review() -> Optional[Dict]:
    csv = _latest(_FR_EXPORTS, "failure_review_*.csv")
    if csv is None:
        return None
    token = _token_of(csv)
    md = _FR_REPORTS / f"failure_review_{token}.md"
    try:
        df = pd.read_csv(csv, encoding="utf-8-sig", dtype={"代码": str})
    except Exception:
        df = pd.DataFrame()
    md_text = md.read_text(encoding="utf-8") if md.exists() else ""
    return {"token": token, "csv_path": csv, "md_path": md if md.exists() else None,
            "df": df, "md_text": md_text,
            "type_section": _md_section(md_text, "失败类型归类"),
            "advice": _md_section(md_text, "改进观察建议（研究方向，非交易指令）")}


# =====================================================
# HTML 渲染
# =====================================================

def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _page(title: str, content: str) -> str:
    tpl = _TEMPLATE.read_text(encoding="utf-8")
    return (tpl.replace("{{TITLE}}", _esc(title))
               .replace("{{DISCLAIMER}}", _esc(config.DISCLAIMER))
               .replace("{{CONTENT}}", content))


def _intro_card() -> str:
    return (
        '<div class="card">'
        '<h1>系统1 · A股只读投研 Dashboard</h1>'
        '<p>本页面只读展示「模型A 短线强势股扫描器」已生成的扫描结果，'
        f'仅分析{_esc(config.ONLY_MARKET)}公开行情数据。</p>'
        '<p class="muted">系统能力边界：只读分析与展示。'
        '<b>不接实盘、不自动下单、不接券商/交易所接口（含 Alpaca/OKX）、'
        '不提供任何买入/卖出建议</b>。本服务仅提供 GET 浏览，无任何写入或交易功能。</p>'
        '</div>'
    )


def _disclaimer_card() -> str:
    return ('<div class="card"><h2>风险免责声明</h2>'
            f'<div class="disclaimer-box">{_esc(config.DISCLAIMER)}<br>'
            '短线强势股波动大、回撤快，量价指标具滞后性；入选仅表示当前满足模型量价特征，'
            '不代表未来走势，更不构成任何投资建议。</div></div>')


def _meta_card(scan: Dict) -> str:
    meta = scan["meta"]
    items = [
        ("扫描时间", meta.get("扫描时间", "—")),
        ("模型", meta.get("模型", "模型A 短线强势")),
        ("模式", meta.get("模式", "—")),
        ("股票池数量", meta.get("股票池数量", "—")),
        ("入选候选数量", meta.get("入选候选数量", str(len(scan["df"])))),
    ]
    cells = "".join(
        f'<div class="meta-item"><div class="k">{_esc(k)}</div>'
        f'<div class="v">{_esc(v)}</div></div>' for k, v in items)
    return f'<div class="card"><h2>最新扫描概览</h2><div class="meta-grid">{cells}</div></div>'


_TABLE_COLS = ["排名", "代码", "名称", "综合分", "近5日涨幅%", "成交额(亿)",
               "量比(今/5日均)", "收盘", "MA5", "MA10", "MA20",
               "站上MA5/10/20", "换手率%", "行业"]
_NUM_COLS = {"综合分", "近5日涨幅%", "成交额(亿)", "量比(今/5日均)", "收盘", "MA5", "MA10", "MA20", "换手率%"}


def _candidates_card(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ('<div class="card"><h2>候选股</h2>'
                '<div class="empty">本次扫描无入选候选股。</div></div>')
    cols = [c for c in _TABLE_COLS if c in df.columns]
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    rows = ""
    for _, r in df.iterrows():
        tds = "".join(
            f'<td class="{"num" if c in _NUM_COLS else ""}">{_esc(r.get(c, ""))}</td>'
            for c in cols)
        rows += f"<tr>{tds}</tr>"
    return (f'<div class="card"><h2>候选股排名</h2>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')


def _reasons_card(df: pd.DataFrame) -> str:
    if df is None or df.empty or "入选理由" not in df.columns:
        return ""
    blocks = ""
    for _, r in df.iterrows():
        reasons = [x for x in re.split(r"[；;]", str(r.get("入选理由", ""))) if x.strip()]
        lis = "".join(f"<li>{_esc(x.strip())}</li>" for x in reasons)
        blocks += (f'<div class="reason-block"><span class="code">'
                   f'{_esc(r.get("代码",""))} {_esc(r.get("名称",""))}</span>'
                   f'<ul class="reasons">{lis}</ul></div>')
    return f'<div class="card"><h2>入选理由</h2>{blocks}</div>'


def _risk_card(df: pd.DataFrame, general_risk: str) -> str:
    parts = ['<div class="card"><h2>风险提示</h2>']
    if df is not None and not df.empty and "风险提示" in df.columns:
        per = ""
        for _, r in df.iterrows():
            note = str(r.get("风险提示", "")).strip()
            if note and note != "—" and note.lower() != "nan":
                per += (f'<div class="reason-block"><span class="code">'
                        f'{_esc(r.get("代码",""))} {_esc(r.get("名称",""))}</span>'
                        f'<div class="risk">{_esc(note)}</div></div>')
        if per:
            parts.append("<h3 class=\"muted\">个股风险点</h3>" + per)
    if general_risk:
        items = [re.sub(r"^[-*]\s*", "", ln).strip()
                 for ln in general_risk.splitlines() if ln.strip().startswith(("-", "*"))]
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items)
        if lis:
            parts.append(f'<ul class="reasons">{lis}</ul>')
    parts.append("</div>")
    return "".join(parts)


def _reject_card(reject_summary: str) -> str:
    if not reject_summary:
        return ""
    items = [re.sub(r"^[-*]\s*", "", ln).strip()
             for ln in reject_summary.splitlines() if ln.strip().startswith(("-", "*"))]
    lis = "".join(f"<li>{_esc(x)}</li>" for x in items)
    return f'<div class="card"><h2>未入选原因摘要</h2><ul class="reasons">{lis}</ul></div>'


def _links_card(scan: Dict) -> str:
    links = []
    if scan["md_path"]:
        links.append('<a href="/report/latest">查看扫描报告（Markdown）</a>')
        links.append('<a href="/download/report">下载报告 .md</a>')
    links.append('<a href="/download/csv">下载候选 .csv</a>')
    return (f'<div class="card"><h2>报告与导出</h2><div class="links">{"".join(links)}</div>'
            f'<p class="muted">文件：{_esc(scan["csv_path"].name)}</p></div>')


def _selection_backtest_home_card() -> str:
    sbt = load_latest_selection_backtest()
    if sbt is None:
        return ('<div class="card"><h2>选股模型回测</h2>'
                '<div class="empty">暂无回测结果。运行：<br>'
                '<code>python -m backtest_agent_v1.selection_backtest_cli --model strong '
                '--mode loose --symbols 600519,000858 --period 6m</code></div></div>')
    df = sbt["summary_df"]
    kv = {str(r["指标"]): str(r["数值"]) for _, r in df.iterrows()} if not df.empty else {}
    keys = ["交易次数", "总收益率", "年化收益率", "胜率", "盈亏比", "最大回撤"]
    cells = "".join(
        f'<div class="meta-item"><div class="k">{_esc(k)}</div>'
        f'<div class="v">{_esc(kv.get(k, "—"))}</div></div>' for k in keys if k in kv)
    return (f'<div class="card"><h2>选股模型回测</h2>'
            f'<div class="meta-grid">{cells}</div>'
            f'<div class="links" style="margin-top:14px">'
            f'<a href="/selection-backtest">查看回测详情</a></div></div>')


def render_selection_backtest_page() -> Optional[str]:
    sbt = load_latest_selection_backtest()
    if sbt is None:
        return None
    parts = ['<div class="card"><h2>选股模型回测（模型A · 历史模拟）</h2>'
             '<div class="links"><a href="/">← 返回首页</a></div>'
             '<p class="muted">历史模拟复盘，含模拟退出规则与仓位，'
             '不代表未来，不构成任何买入/卖出建议。本页只读。</p></div>']

    # 指标表
    df = sbt["summary_df"]
    if not df.empty:
        rows = "".join(f'<tr><td>{_esc(r["指标"])}</td>'
                       f'<td class="num">{_esc(r["数值"])}</td></tr>' for _, r in df.iterrows())
        parts.append(f'<div class="card"><h2>回测指标</h2><table><thead><tr>'
                     f'<th>指标</th><th>数值</th></tr></thead><tbody>{rows}</tbody></table></div>')

    # 净值曲线
    if sbt["chart_path"]:
        parts.append('<div class="card"><h2>净值曲线</h2>'
                     '<img src="/selection-backtest/chart" alt="净值曲线" '
                     'style="width:100%;border-radius:8px;border:1px solid var(--border)"></div>')

    # 交易明细
    tdf = sbt["trades_df"]
    if not tdf.empty:
        cols = [c for c in ["序号", "代码", "名称", "入场日", "出场日", "收益率%",
                            "持仓天数", "退出原因", "曾达第一目标"] if c in tdf.columns]
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        body = ""
        for _, r in tdf.iterrows():
            tds = "".join(f'<td class="{"num" if c in ("收益率%","持仓天数","序号") else ""}">'
                          f'{_esc(r.get(c, ""))}</td>' for c in cols)
            body += f"<tr>{tds}</tr>"
        parts.append(f'<div class="card"><h2>交易明细（{len(tdf)} 笔）</h2>'
                     f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    # 链接
    links = []
    if sbt["md_path"]:
        links.append('<a href="/selection-backtest/download/report">下载回测报告 .md</a>')
    links.append('<a href="/selection-backtest/download/summary">下载汇总 .csv</a>')
    if sbt["trades_path"]:
        links.append('<a href="/selection-backtest/download/trades">下载交易明细 .csv</a>')
    parts.append(f'<div class="card"><h2>报告与导出</h2>'
                 f'<div class="links">{"".join(links)}</div></div>')
    return _page("选股模型回测", "".join(parts))


def _pool_compare_home_card() -> str:
    pc = load_latest_pool_compare()
    if pc is None:
        return ('<div class="card"><h2>股票池横向对比</h2>'
                '<div class="empty">暂无对比报告。运行：<br>'
                '<code>python -m backtest_agent_v1.pool_compare_cli</code></div></div>')
    best = ""
    m = re.search(r"当前最佳适配池：([^\s（(]+)", pc["md_text"])
    if m:
        best = m.group(1)
    return (f'<div class="card"><h2>股票池横向对比</h2>'
            f'<p>当前最佳适配池（数据驱动）：<b class="code">{_esc(best or "—")}</b></p>'
            f'<div class="links"><a href="/pool-compare">查看对比表</a></div></div>')


def render_pool_compare_page() -> Optional[str]:
    pc = load_latest_pool_compare()
    if pc is None:
        return None
    parts = ['<div class="card"><h2>股票池横向对比（模型A 选股回测）</h2>'
             '<div class="links"><a href="/">← 返回首页</a></div>'
             '<p class="muted">仅汇总已有回测结果，未重新跑回测；历史模拟，不构成任何买入/卖出建议。</p></div>']
    df = pc["df"]
    if not df.empty:
        cols = list(df.columns)
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        body = ""
        for _, r in df.iterrows():
            tds = "".join(f'<td class="{"num" if c not in ("排名","股票池","数据状态") else ""}">'
                          f'{_esc("" if pd.isna(r.get(c)) else r.get(c))}</td>' for c in cols)
            body += f"<tr>{tds}</tr>"
        parts.append(f'<div class="card"><h2>对比表</h2>'
                     f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    if pc["conclusion"]:
        items = [re.sub(r"^[-*]\s*", "", ln).strip()
                 for ln in pc["conclusion"].splitlines() if ln.strip().startswith(("-", "*"))]
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items)
        parts.append(f'<div class="card"><h2>结论（数据驱动）</h2><ul class="reasons">{lis}</ul></div>')
    links = []
    if pc["md_path"]:
        links.append('<a href="/pool-compare/download/report">下载对比报告 .md</a>')
    links.append('<a href="/pool-compare/download/csv">下载对比表 .csv</a>')
    parts.append(f'<div class="card"><h2>报告与导出</h2><div class="links">{"".join(links)}</div></div>')
    return _page("股票池横向对比", "".join(parts))


def _pool_diagnosis_home_card() -> str:
    pd_ = load_latest_pool_diagnosis()
    if pd_ is None:
        return ('<div class="card"><h2>股票池成分贡献诊断</h2>'
                '<div class="empty">暂无诊断。运行：<br>'
                '<code>python -m backtest_agent_v1.pool_diagnosis_cli --pool tech_30</code></div></div>')
    df = pd_["df"]
    cnt = df["建议"].value_counts().to_dict() if (not df.empty and "建议" in df.columns) else {}
    keys = [("保留", "保留"), ("观察", "观察"), ("踢出", "踢出")]
    cells = "".join(
        f'<div class="meta-item"><div class="k">{label}</div>'
        f'<div class="v">{int(cnt.get(k, 0))}</div></div>' for label, k in keys)
    return (f'<div class="card"><h2>股票池成分贡献诊断</h2>'
            f'<p class="muted">最新：{_esc(pd_["pool"])}</p>'
            f'<div class="meta-grid">{cells}</div>'
            f'<div class="links" style="margin-top:14px">'
            f'<a href="/pool-diagnosis">查看诊断详情</a></div></div>')


def render_pool_diagnosis_page() -> Optional[str]:
    pd_ = load_latest_pool_diagnosis()
    if pd_ is None:
        return None
    parts = [f'<div class="card"><h2>股票池成分贡献诊断（{_esc(pd_["pool"])}）</h2>'
             '<div class="links"><a href="/">← 返回首页</a></div>'
             '<p class="muted">基于已有回测交易明细，未重跑回测；保留/观察/踢出为研究分级，'
             '替补候选仅观察、不自动替换，不构成任何买入/卖出建议。</p></div>']
    df = pd_["df"]
    if not df.empty:
        show = [c for c in ["代码", "名称", "交易次数", "总收益贡献", "平均单笔收益", "胜率",
                            "盈亏比", "最大单笔亏损", "止损占比", "第一目标达成次数",
                            "第二目标达成次数", "平均持仓天数", "综合评分", "建议", "建议理由"]
                if c in df.columns]
        head = "".join(f"<th>{_esc(c)}</th>" for c in show)
        body = ""
        for _, r in df.iterrows():
            tds = ""
            for c in show:
                v = r.get(c)
                cls = "num" if c not in ("代码", "名称", "建议", "建议理由") else ""
                tds += f'<td class="{cls}">{_esc("" if pd.isna(v) else v)}</td>'
            body += f"<tr>{tds}</tr>"
        parts.append(f'<div class="card"><h2>成分股贡献明细</h2>'
                     f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    if pd_["watch"]:
        parts.append(f'<div class="card"><h2>替补候选观察名单（仅观察，不自动替换）</h2>'
                     f'<p class="muted">{_esc(pd_["watch"])}</p></div>')
    links = []
    if pd_["md_path"]:
        links.append('<a href="/pool-diagnosis/download/report">下载诊断报告 .md</a>')
    links.append('<a href="/pool-diagnosis/download/csv">下载诊断表 .csv</a>')
    parts.append(f'<div class="card"><h2>报告与导出</h2><div class="links">{"".join(links)}</div></div>')
    return _page("股票池成分贡献诊断", "".join(parts))


def _observation_home_card() -> str:
    ob = load_latest_observation_plan()
    if ob is None:
        return ('<div class="card"><h2>候选股观察计划</h2>'
                '<div class="empty">暂无观察计划。运行：<br>'
                '<code>python -m backtest_agent_v1.observation_plan_cli --pool tech_30_v2</code>'
                '</div></div>')
    n = 0 if ob["df"].empty else len(ob["df"])
    return (f'<div class="card"><h2>候选股观察计划</h2>'
            f'<p class="muted">最新观察池：{_esc(ob["pool"])}　|　候选 {n} 只'
            f'（研究参考，非买卖建议）</p>'
            f'<div class="links"><a href="/observation-plan">查看观察计划</a></div></div>')


def render_observation_plan_page() -> Optional[str]:
    ob = load_latest_observation_plan()
    if ob is None:
        return None
    parts = [f'<div class="card"><h2>候选股观察计划（{_esc(ob["pool"])}）</h2>'
             '<div class="links"><a href="/">← 返回首页</a></div>'
             '<p class="muted">所有「观察位/低吸位/突破位/止损参考位/目标位」均为研究参考价位，'
             '用于跟踪观察，<b>不构成任何买入/卖出建议、不构成交易指令</b>。本页只读、无交易按钮。</p></div>']
    df = ob["df"]
    if df.empty:
        parts.append('<div class="card"><div class="empty">本次无候选。</div></div>')
    else:
        show = [c for c in ["排名", "代码", "名称", "当前收盘价", "观察位", "低吸位", "突破位",
                            "止损参考位", "第一目标位", "第二目标位", "仓位上限", "失效条件",
                            "风险提示", "数据时间", "观察分级"] if c in df.columns]
        head = "".join(f"<th>{_esc(c)}</th>" for c in show)
        body = ""
        for _, r in df.iterrows():
            tds = "".join(
                f'<td class="{"num" if c in ("当前收盘价","观察位","突破位","止损参考位") else ""}">'
                f'{_esc("" if pd.isna(r.get(c)) else r.get(c))}</td>' for c in show)
            body += f"<tr>{tds}</tr>"
        parts.append(f'<div class="card"><h2>候选观察总览</h2>'
                     f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    links = []
    if ob["md_path"]:
        links.append('<a href="/observation-plan/download/report">下载观察计划 .md</a>')
    links.append('<a href="/observation-plan/download/csv">下载观察计划 .csv</a>')
    parts.append(f'<div class="card"><h2>报告与导出</h2><div class="links">{"".join(links)}</div></div>')
    return _page("候选股观察计划", "".join(parts))


def _failure_review_home_card() -> str:
    fr = load_latest_failure_review()
    if fr is None:
        return ('<div class="card"><h2>失败案例复盘</h2>'
                '<div class="empty">暂无复盘。运行：<br>'
                '<code>python -m backtest_agent_v1.failure_review_cli --pool tech_30_v2</code>'
                '</div></div>')
    n = 0 if fr["df"].empty else len(fr["df"])
    top_type = ""
    if not fr["df"].empty and "失败类型" in fr["df"].columns:
        vc = fr["df"]["失败类型"].value_counts()
        if len(vc):
            top_type = f"{vc.index[0]}（{int(vc.iloc[0])}笔）"
    return (f'<div class="card"><h2>失败案例复盘</h2>'
            f'<p class="muted">亏损交易 {n} 笔　|　最多失败类型：{_esc(top_type or "—")}</p>'
            f'<div class="links"><a href="/failure-review">查看复盘详情</a></div></div>')


def render_failure_review_page() -> Optional[str]:
    fr = load_latest_failure_review()
    if fr is None:
        return None
    parts = ['<div class="card"><h2>失败案例复盘（tech_30_v2 历史回测）</h2>'
             '<div class="links"><a href="/">← 返回首页</a></div>'
             '<p class="muted">仅对历史模拟亏损交易做归因；改进建议为研究方向，'
             '不构成任何买入/卖出建议。本页只读。</p></div>']
    df = fr["df"]
    if not df.empty and "失败类型" in df.columns:
        vc = df["失败类型"].value_counts()
        cells = "".join(f'<div class="meta-item"><div class="k">{_esc(t)}</div>'
                        f'<div class="v">{int(c)}</div></div>' for t, c in vc.items())
        parts.append(f'<div class="card"><h2>失败类型归类</h2>'
                     f'<div class="meta-grid">{cells}</div></div>')
    if not df.empty:
        show = [c for c in ["代码", "名称", "入场日", "出场日", "收益率%", "持仓天数",
                            "退出原因", "失败类型"] if c in df.columns]
        head = "".join(f"<th>{_esc(c)}</th>" for c in show)
        body = ""
        for _, r in df.iterrows():
            tds = "".join(f'<td class="{"num" if c in ("收益率%","持仓天数") else ""}">'
                          f'{_esc("" if pd.isna(r.get(c)) else r.get(c))}</td>' for c in show)
            body += f"<tr>{tds}</tr>"
        parts.append(f'<div class="card"><h2>亏损交易列表（{len(df)} 笔）</h2>'
                     f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
    if fr["advice"]:
        items = [re.sub(r"^[-*]\s*", "", ln).strip()
                 for ln in fr["advice"].splitlines() if ln.strip().startswith(("-", "*"))]
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items)
        parts.append(f'<div class="card"><h2>改进观察建议（研究方向，非交易指令）</h2>'
                     f'<ul class="reasons">{lis}</ul></div>')
    links = []
    if fr["md_path"]:
        links.append('<a href="/failure-review/download/report">下载复盘报告 .md</a>')
    links.append('<a href="/failure-review/download/csv">下载亏损明细 .csv</a>')
    parts.append(f'<div class="card"><h2>报告与导出</h2><div class="links">{"".join(links)}</div></div>')
    return _page("失败案例复盘", "".join(parts))


def render_realtime_page() -> str:
    """实时看板：优先 iframe 嵌入外部 Streamlit 只读看板，失败则用按钮在新标签打开。"""
    url = _esc(STREAMLIT_URL)
    content = (
        '<div class="card"><h2>实时看板（Streamlit 只读）</h2>'
        f'<p class="muted">下方嵌入外部 Streamlit 只读看板（{url}）。'
        '该看板由独立的 Streamlit 进程提供，本入口仅做只读嵌入，不托管、不迁移它。<br>'
        '若下方区域空白、加载失败或被浏览器/对方的 X-Frame-Options 拦截，请点下方按钮在新标签打开。</p>'
        f'<div class="links"><a class="btn" href="{url}" target="_blank" rel="noopener">'
        '在新标签打开实时看板 →</a></div></div>'
        '<div class="card">'
        f'<iframe src="{url}" class="rt-frame" title="实时看板" loading="lazy"'
        ' referrerpolicy="no-referrer"></iframe>'
        '<p class="muted">提示：如未显示，多为 Streamlit 未启动（请在 8501 端口运行你的 Streamlit 只读看板），'
        '或其禁止被 iframe 嵌入——此时用上方按钮跳转打开即可。本页只读，无任何交易/下单接口。</p>'
        '</div>'
    )
    return _page("实时看板", content)


def render_home() -> str:
    scan = load_latest_scan()
    if scan is None:
        content = (_intro_card() + _disclaimer_card() +
                   '<div class="card"><h2>暂无扫描结果</h2>'
                   '<div class="empty">scan_exports 下还没有扫描结果。请先运行：<br>'
                   '<code>python -m backtest_agent_v1.scan_cli --model strong --mode loose '
                   '--symbols 600519,000858 --limit 50</code></div></div>' +
                   _selection_backtest_home_card() + _pool_compare_home_card() +
                   _pool_diagnosis_home_card() + _observation_home_card() +
                   _failure_review_home_card())
        return _page("系统1 只读 Dashboard", content)
    content = (
        _intro_card() + _disclaimer_card() + _meta_card(scan) +
        _candidates_card(scan["df"]) + _reasons_card(scan["df"]) +
        _risk_card(scan["df"], scan["general_risk"]) +
        _reject_card(scan["reject_summary"]) + _links_card(scan) +
        _selection_backtest_home_card() + _pool_compare_home_card() +
        _pool_diagnosis_home_card() + _observation_home_card() +
        _failure_review_home_card()
    )
    return _page("系统1 只读 Dashboard", content)


def render_report_page() -> Optional[str]:
    scan = load_latest_scan()
    if not scan or not scan["md_path"]:
        return None
    body = (f'<div class="card"><h2>扫描报告：{_esc(scan["md_path"].name)}</h2>'
            f'<div class="links"><a href="/">← 返回首页</a>'
            f'<a href="/download/report">下载 .md</a></div>'
            f'<pre class="report">{_esc(scan["md_text"])}</pre></div>')
    return _page("扫描报告", body)


# =====================================================
# 仅 GET 的请求处理器
# =====================================================

class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ReadOnlyDashboard/1.0"

    # 只实现 do_GET；不实现 do_POST/do_PUT/do_DELETE（基类对其它方法返回 501）。
    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self._send_html(render_home())
        if path == "/static/style.css":
            return self._send_file(_STATIC / "style.css", "text/css; charset=utf-8")
        if path == "/realtime":
            return self._send_html(render_realtime_page())
        if path == "/report/latest":
            page = render_report_page()
            return self._send_html(page) if page else self._not_found()
        if path == "/download/csv":
            scan = load_latest_scan()
            if scan:
                return self._send_file(scan["csv_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        if path == "/download/report":
            scan = load_latest_scan()
            if scan and scan["md_path"]:
                return self._send_file(scan["md_path"], "text/markdown; charset=utf-8", download=True)
            return self._not_found()
        if path == "/selection-backtest":
            page = render_selection_backtest_page()
            return self._send_html(page) if page else self._not_found()
        if path == "/selection-backtest/chart":
            sbt = load_latest_selection_backtest()
            if sbt and sbt["chart_path"]:
                return self._send_file(sbt["chart_path"], "image/png")
            return self._not_found()
        if path == "/selection-backtest/download/report":
            sbt = load_latest_selection_backtest()
            if sbt and sbt["md_path"]:
                return self._send_file(sbt["md_path"], "text/markdown; charset=utf-8", download=True)
            return self._not_found()
        if path == "/selection-backtest/download/summary":
            sbt = load_latest_selection_backtest()
            if sbt:
                return self._send_file(sbt["summary_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        if path == "/selection-backtest/download/trades":
            sbt = load_latest_selection_backtest()
            if sbt and sbt["trades_path"]:
                return self._send_file(sbt["trades_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        if path == "/pool-compare":
            page = render_pool_compare_page()
            return self._send_html(page) if page else self._not_found()
        if path == "/pool-compare/download/report":
            pc = load_latest_pool_compare()
            if pc and pc["md_path"]:
                return self._send_file(pc["md_path"], "text/markdown; charset=utf-8", download=True)
            return self._not_found()
        if path == "/pool-compare/download/csv":
            pc = load_latest_pool_compare()
            if pc:
                return self._send_file(pc["csv_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        if path == "/pool-diagnosis":
            page = render_pool_diagnosis_page()
            return self._send_html(page) if page else self._not_found()
        if path == "/pool-diagnosis/download/report":
            pdg = load_latest_pool_diagnosis()
            if pdg and pdg["md_path"]:
                return self._send_file(pdg["md_path"], "text/markdown; charset=utf-8", download=True)
            return self._not_found()
        if path == "/pool-diagnosis/download/csv":
            pdg = load_latest_pool_diagnosis()
            if pdg:
                return self._send_file(pdg["csv_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        if path == "/observation-plan":
            page = render_observation_plan_page()
            return self._send_html(page) if page else self._not_found()
        if path == "/observation-plan/download/report":
            ob = load_latest_observation_plan()
            if ob and ob["md_path"]:
                return self._send_file(ob["md_path"], "text/markdown; charset=utf-8", download=True)
            return self._not_found()
        if path == "/observation-plan/download/csv":
            ob = load_latest_observation_plan()
            if ob:
                return self._send_file(ob["csv_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        if path == "/failure-review":
            page = render_failure_review_page()
            return self._send_html(page) if page else self._not_found()
        if path == "/failure-review/download/report":
            fr = load_latest_failure_review()
            if fr and fr["md_path"]:
                return self._send_file(fr["md_path"], "text/markdown; charset=utf-8", download=True)
            return self._not_found()
        if path == "/failure-review/download/csv":
            fr = load_latest_failure_review()
            if fr:
                return self._send_file(fr["csv_path"], "text/csv; charset=utf-8", download=True)
            return self._not_found()
        return self._not_found()

    def _send_html(self, body: str, code: int = 200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str, download: bool = False):
        if not path or not Path(path).exists():
            return self._not_found()
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{Path(path).name}"')
        self.end_headers()
        self.wfile.write(data)

    def _not_found(self):
        self._send_html(_page("未找到", '<div class="card"><div class="empty">'
                               '页面不存在。<a href="/">返回首页</a></div></div>'), code=404)

    def log_message(self, fmt, *args):
        print(f"[dashboard] {self.address_string()} {fmt % args}")


def serve(host: str = "127.0.0.1", port: int = 8030) -> None:
    config.assert_readonly()
    httpd = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"只读 Dashboard 已启动：http://localhost:{port}  （仅 GET，按 Ctrl+C 退出）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
