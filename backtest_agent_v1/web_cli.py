"""只读 Dashboard 启动入口（仅 GET，本地访问）。

用法：
  python -m backtest_agent_v1.web_cli
  python -m backtest_agent_v1.web_cli --port 8030 --host 127.0.0.1

访问：http://localhost:8030

本服务只读：无 POST/PUT/DELETE、无交易按钮、不接实盘、不下单、不接 Alpaca/OKX。
"""

from __future__ import annotations

import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from . import web_dashboard


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="系统1 只读 Dashboard（仅 GET）")
    p.add_argument("--host", default="127.0.0.1", help="绑定地址（默认本机 127.0.0.1）")
    p.add_argument("--port", type=int, default=8030, help="端口（默认 8030）")
    args = p.parse_args(argv)

    config.assert_readonly()
    web_dashboard.serve(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
