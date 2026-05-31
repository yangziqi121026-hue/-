# a_share_agent_v2

A股投研 Agent v2 —— **只读分析脚手架**。本仓库目前只搭建基础目录结构与占位文件，
**尚未写入任何业务逻辑**。

## 硬约束（不可违反）

- ❌ **不接实盘**：不连接任何券商/交易所实盘行情或账户。
- ❌ **不自动下单**：系统不具备、也不会调用任何下单能力。
- ❌ **不做交易接口**：不实现买入/卖出/委托/撤单等交易 API。
- ✅ **只读研究**：仅基于公开数据做选股、回测、诊断、复盘等研究分析，产出报告与图表。
- ✅ **不做复杂页面**：Dashboard 仅做轻量展示，暂不实现复杂前端。

## 目录结构

```
a_share_agent_v2/
├── backtest_agent_v1/              # 回测 agent（占位，待实现）
├── data/                           # 数据层（原始/清洗后数据，占位）
├── models/                         # 模型/因子/策略层（占位）
├── dashboard/                      # 轻量看板（占位，不做复杂页面）
│
├── scan_reports/                   # 全市场扫描——报告
├── scan_exports/                   # 全市场扫描——导出（csv/json）
├── scan_charts/                    # 全市场扫描——图表
│
├── selection_backtest_reports/     # 选股回测——报告
├── selection_backtest_exports/     # 选股回测——导出
├── selection_backtest_charts/      # 选股回测——图表
│
├── pool_diagnosis_reports/         # 股票池诊断——报告
├── pool_diagnosis_exports/         # 股票池诊断——导出
│
├── observation_reports/            # 观察池——报告
├── observation_exports/            # 观察池——导出
│
├── failure_review_reports/         # 失败复盘——报告
├── failure_review_exports/         # 失败复盘——导出
│
├── realtime_scan_exports/          # 准实时扫描——导出（仅只读快照，非实盘）
├── realtime_scan_cache/            # 准实时扫描——缓存
│
├── README.md
└── requirements.txt
```

> 四个基础层：**数据（data）/ 模型（models）/ 报告（各 *_reports + *_exports + *_charts）/ 看板（dashboard）**。
> 各业务域（扫描 scan / 选股回测 selection_backtest / 池诊断 pool_diagnosis /
> 观察 observation / 失败复盘 failure_review / 准实时扫描 realtime_scan）各自独立产出目录。

## 状态

- [x] 目录骨架
- [x] 基础文件（README / requirements / .gitignore）
- [ ] 数据层
- [ ] 模型/因子层
- [ ] 报告生成
- [ ] 看板

## 备注

`realtime_scan_*` 的「实时」指**只读的准实时行情快照扫描**，用于研究观察，
**不等于实盘交易**，不涉及任何下单或交易接口。
