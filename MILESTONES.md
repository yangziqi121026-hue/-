# 里程碑记录 · MILESTONES

> 本文件仅记录版本里程碑，不含开发任务。

---

## 🏁 V2-8.6：统一入口成功版（封版）

- **封版日期**：2026-06-02
- **代码状态**：远端 `main` = `5d323d5`（GitHub: `yangziqi121026-hue/-`）
- **测试**：78 / 78 全过（纯标准库 unittest，不联网 / 不调实盘）
- **定位**：A股选股回测系统 V2，只读研究分析平台

### 已具备功能（16 项）

1. **模型A 短线强势股扫描**（`scan_cli`）——量价多条件研究筛选。
2. **strict / loose 双模式**——严格 / 宽松两套阈值。
3. **tech_30_v2 优先观察池**——基于 V2-4 诊断「踢 11 补 11」优化的默认观察池（原 tech_30 保留）。
4. **选股规则历史回测**（`selection_backtest_cli`）——事件驱动交易级模拟，次日入场 / 最多持有10日 / 止损·第二目标·跌破MA20·到期退出 / 10% 仓位（仅模拟）。
5. **股票池横向对比**（`pool_compare_cli`）——只读已有回测 summary，数据驱动选最佳池。
6. **成分贡献诊断**（`pool_diagnosis_cli`）——逐股贡献 + 保留/观察/踢出（6 条踢出规则任 2 触发）。
7. **tech_30_v2 三周期稳定性验证**（V2-6）——3m/6m/1y 多窗校验（结论：底盘正、风控达标，但 edge 随周期变长衰减；非长期稳定 alpha）。
8. **候选股观察计划**（`observation_plan_cli`）——15 字段研究参考位（观察位/低吸位/突破位/止损参考位/第一·第二目标位/仓位上限/失效条件等），统一「候选观察计划」口径。
9. **失败案例复盘**（`failure_review_cli`）——亏损交易 9 类失败归因 + 失败股票排名 + 改进观察建议。
10. **今日实时选股**——模型A 准实时快照扫描（只读，非实盘）。
11. **风险等级显示**——研究分级（观察 / 谨慎关注 / 暂不参与 / 高风险）+ 高风险观察 / 数据不足标记。
12. **8030 主入口**——只读 Web Dashboard。⚠️ 实现为 **Python 标准库 `http.server`（仅 GET 路由）**，非 FastAPI（用户惯称「FastAPI Dashboard」，实际无 FastAPI 依赖、机制上保证只读）。
13. **8501 Streamlit 只读看板**——主入口已提供 `/realtime` 嵌入入口（iframe + 跳转兜底）。⚠️ **本工程内尚无 Streamlit 应用**，8501 需由外部 Streamlit 进程提供；按「不迁移 Streamlit」当外部看板嵌入。
14. **统一入口**（V2-8.6）——8030 顶部导航「实时看板」→ `/realtime`：优先 iframe 嵌入 8501，失败时按钮在新标签打开。
15. **报告 / CSV 下载**——各业务域产出 md 报告 + csv/png 导出，Dashboard 提供只读下载链接。
16. **免责声明**——所有报告 / 页面统一附数据来源 + 抓取时间 + 免责声明；27 词交易指令禁词安全网（`sanitize`，幂等）。

### Dashboard 只读区（6 个 + 实时看板导航）

`scan` 候选 · `selection-backtest` 回测 · `pool-compare` 池对比 · `pool-diagnosis` 成分诊断 · `observation-plan` 观察计划 · `failure-review` 失败复盘 · `/realtime` 实时看板入口。
全部仅 GET；POST / PUT / DELETE 一律 501；无 `<form>` / 无交易按钮。

### 严格边界（不可违反）

- ❌ 不接实盘
- ❌ 不自动下单
- ❌ 不做 copy trading
- ❌ 不输出买入 / 卖出建议（字段「止损位」统一渲染为「止损参考位」，结论用研究分级）
- ❌ 不承诺收益（历史模拟不代表未来，统计样本有限）
- ✅ 只读研究分析，公开数据源（AKShare），仅 LLM/无密钥要求

### 模块清单（`backtest_agent_v1/`）

```
stock_scanner / selection_models / risk_plan / scan_cli          # 扫描
selection_backtest / selection_backtest_cli                       # 回测
stock_pools                                                       # 股票池（含 tech_30_v2）
pool_compare(_cli) / pool_diagnosis(_cli)                         # 对比 / 诊断
observation_plan(_cli) / failure_review(_cli)                     # 观察计划 / 失败复盘
web_dashboard / web_cli / web_templates/ / web_static/            # 只读 Web（8030，仅 GET）
```

---

> 本系统由程序基于公开数据自动生成，仅供研究学习，不构成任何投资建议，不构成买卖要约，不承诺收益，据此操作风险自负。
