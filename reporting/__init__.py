"""报告层（reporting）：把研究结果渲染为报告/导出，并守住「只读、不下单」底线。

职责：统一报告头部（数据来源 + 抓取时间 + 免责声明）、4 档研究分级文案、
以及交易指令禁词安全网（sanitize）。各业务域的具体报告模板继承 ReportBuilder。

当前为基础骨架：提供禁词安全网与基类，具体模板待填充。
"""

from .base import FORBIDDEN_WORDS, ReportBuilder, sanitize

__all__ = ["sanitize", "FORBIDDEN_WORDS", "ReportBuilder"]
