"""a_share_agent_v2 顶层配置：路径登记 + 系统级硬约束。

设计原则（写死，不可被参数/环境变量覆盖）：
- ONLY_READONLY = True：本系统只做只读研究分析。
- ENABLE_TRADING = ENABLE_LIVE = False：永不下单、永不接实盘/live。
- 不存在任何券商 / 交易所 / 下单 / 委托相关配置项。

本文件只登记目录与常量，不含任何业务逻辑。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# ---------- 不可变安全约束（系统级，不接受任何外部覆盖）----------
ONLY_READONLY = True       # 只读研究
ENABLE_TRADING = False     # 永远禁止真实/模拟下单
ENABLE_LIVE = False        # 永远禁止 live / 实盘订阅
ONLY_MARKET = "A股"        # 只分析 A 股

# 研究结论只允许这 4 档非交易指令标签（绝不出现「买入/卖出」）
ALLOWED_CONCLUSIONS = ("观察", "谨慎关注", "暂不参与", "高风险")
RISK_LEVELS = ("低", "中", "高", "不足以判断")

DISCLAIMER = (
    "本内容由程序基于公开数据自动生成，仅供研究学习，"
    "不构成任何投资建议，不构成买卖要约，据此操作风险自负。"
)

# ---------- 业务域产出目录登记 ----------
# 每个业务域独立产出，互不覆盖。键名即业务域。
OUTPUT_DIRS = {
    "scan": {
        "reports": PROJECT_ROOT / "scan_reports",
        "exports": PROJECT_ROOT / "scan_exports",
        "charts": PROJECT_ROOT / "scan_charts",
    },
    "selection_backtest": {
        "reports": PROJECT_ROOT / "selection_backtest_reports",
        "exports": PROJECT_ROOT / "selection_backtest_exports",
        "charts": PROJECT_ROOT / "selection_backtest_charts",
    },
    "pool_diagnosis": {
        "reports": PROJECT_ROOT / "pool_diagnosis_reports",
        "exports": PROJECT_ROOT / "pool_diagnosis_exports",
    },
    "observation": {
        "reports": PROJECT_ROOT / "observation_reports",
        "exports": PROJECT_ROOT / "observation_exports",
    },
    "failure_review": {
        "reports": PROJECT_ROOT / "failure_review_reports",
        "exports": PROJECT_ROOT / "failure_review_exports",
    },
    "realtime_scan": {  # 「实时」= 只读准实时快照扫描，非实盘、不下单
        "exports": PROJECT_ROOT / "realtime_scan_exports",
        "cache": PROJECT_ROOT / "realtime_scan_cache",
    },
}

# ---------- 基础层目录 ----------
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
BACKTEST_AGENT_DIR = PROJECT_ROOT / "backtest_agent_v1"


def output_dir(domain: str, kind: str) -> Path:
    """取某业务域某类产出目录（reports/exports/charts/cache），不存在则抛 KeyError。"""
    return OUTPUT_DIRS[domain][kind]


def assert_readonly() -> None:
    """供各层启动时自检：一旦交易/实盘开关被异常打开立即报错。"""
    if ENABLE_TRADING or ENABLE_LIVE or not ONLY_READONLY:
        raise RuntimeError("安全约束被破坏：本系统只读，禁止下单/实盘。")
