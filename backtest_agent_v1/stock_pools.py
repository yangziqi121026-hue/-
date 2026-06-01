"""常用股票池管理（预设清单，方便回测不同板块）。

提供 5 个**有界**预设池（均为人工挑选的常见标的，**绝非全市场扫描**）：
  core_30 / tech_30 / ai_robot_30 / new_energy_30 / core_50

以及 resolve()：统一从 --symbols / --pool 解析出代码列表。
规则：**同时传入 --symbols 与 --pool 时，优先用 --symbols。**

纯数据 + 纯解析，不联网、不下单、不接实盘。仅作研究用的标的清单，不构成任何投资建议。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# ---- 30 只大盘核心权重股 ----
CORE_30: List[str] = [
    "600519", "000858", "600036", "601318", "000333", "600276", "300750", "002594",
    "601899", "600030", "000651", "600887", "601012", "600028", "000725", "600585",
    "002475", "601166", "600000", "601398", "600900", "600309", "000001", "601288",
    "601988", "600031", "002415", "000568", "600104", "601088",
]

# core_50 = core_30 + 20 只额外大盘蓝筹
_CORE_EXTRA_20: List[str] = [
    "601628", "600009", "600690", "603259", "600438", "601668", "601857", "600048",
    "000002", "600050", "601601", "601688", "600406", "002304", "600436", "603288",
    "000538", "601225", "600660", "601919",
]
CORE_50: List[str] = CORE_30 + _CORE_EXTRA_20

# ---- 30 只科技股（半导体/消费电子/通信/软件/安防）----
TECH_30: List[str] = [
    "688981", "002230", "300308", "002463", "300502", "000063", "002415", "002475",
    "688012", "603501", "002371", "603986", "002241", "000725", "688008", "688111",
    "300661", "002049", "300223", "603160", "002916", "600584", "000938", "002236",
    "300454", "688036", "603019", "000977", "002405", "300033",
]

# ---- 30 只 AI / 机器人 / 算力 ----
AI_ROBOT_30: List[str] = [
    "002230", "300308", "300502", "688256", "688041", "000977", "300474", "603019",
    "000938", "300024", "002472", "300124", "603728", "688017", "002527", "300496",
    "002405", "300033", "688111", "300223", "002049", "300661", "603501", "002241",
    "002415", "002236", "688008", "603986", "688012", "688521",
]

# ---- 30 只新能源（锂电/光伏/风电/电网/整车）----
NEW_ENERGY_30: List[str] = [
    "300750", "002594", "601012", "600438", "002129", "300274", "688599", "002460",
    "002466", "300014", "002812", "300769", "600905", "601865", "688223", "603799",
    "002709", "300450", "002340", "688772", "601877", "600089", "000591", "601727",
    "600875", "002202", "601615", "300751", "688390", "605117",
]

POOLS = {
    "core_30": CORE_30,
    "tech_30": TECH_30,
    "ai_robot_30": AI_ROBOT_30,
    "new_energy_30": NEW_ENERGY_30,
    "core_50": CORE_50,
}

POOL_LABELS = {
    "core_30": "大盘核心权重 30",
    "tech_30": "科技（半导体/电子/通信/软件）30",
    "ai_robot_30": "AI / 机器人 / 算力 30",
    "new_energy_30": "新能源（锂电/光伏/风电）30",
    "core_50": "大盘核心权重 50",
}


def list_pools() -> List[str]:
    return list(POOLS.keys())


def get_pool(name: str) -> Optional[List[str]]:
    """按名取池（返回去重保序的代码列表）；未知名返回 None。"""
    codes = POOLS.get(name)
    if codes is None:
        return None
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def parse_symbols(spec: str) -> List[str]:
    """从逗号/空白分隔串解析 6 位 A 股代码，去重保序。"""
    out, seen = [], set()
    for tok in re.split(r"[,\s]+", spec or ""):
        m = re.search(r"\d{6}", tok)
        if m and m.group(0) not in seen:
            seen.add(m.group(0))
            out.append(m.group(0))
    return out


def resolve(symbols: Optional[str], pool: Optional[str]) -> Tuple[List[str], str, str]:
    """解析最终标的列表。

    返回 (codes, source, note)。
    规则：同时传入 symbols 与 pool 时**优先 symbols**（note 会提示忽略了 pool）。
    """
    has_symbols = bool(symbols and symbols.strip())
    if has_symbols:
        codes = parse_symbols(symbols)
        note = f"（已忽略 --pool {pool}，--symbols 优先）" if pool else ""
        return codes, "symbols", note
    if pool:
        codes = get_pool(pool)
        if codes is None:
            return [], f"pool:{pool}", f"未知股票池：{pool}，可选 {list_pools()}"
        return codes, f"pool:{pool}（{POOL_LABELS.get(pool, pool)}）", ""
    return [], "none", "需要 --symbols 或 --pool 之一"
