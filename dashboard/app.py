"""看板入口（占位骨架，不做复杂页面）。

当前仅打印项目状态与硬约束，作为后续轻量看板的挂载点。
真正的展示（如 streamlit）后续按需填充，且永远保持只读、无任何交易交互。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python dashboard/app.py` 直接运行：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def summary() -> dict:
    """返回看板可展示的基础信息（占位）。"""
    return {
        "project": "a_share_agent_v2",
        "market": config.ONLY_MARKET,
        "readonly": config.ONLY_READONLY,
        "trading_enabled": config.ENABLE_TRADING,
        "live_enabled": config.ENABLE_LIVE,
        "domains": list(config.OUTPUT_DIRS.keys()),
    }


def main() -> None:
    config.assert_readonly()
    info = summary()
    print("=== a_share_agent_v2 Dashboard（占位）===")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print(f"\n{config.DISCLAIMER}")
    print("\n（看板为轻量只读展示，不做复杂页面，不含任何下单/交易交互。）")


if __name__ == "__main__":
    main()
