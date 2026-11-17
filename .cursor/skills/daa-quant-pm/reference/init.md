# Init — 沉淀产品真相

把可复用的产品事实写入 `PRODUCT.md`，量化专用约束写入 `QUANT.md`。不发明未确认事实，不在此阶段写视觉/UI。

## Step 1: 现状

- 已有 `PRODUCT.md` / `QUANT.md`：只问过时或缺失项，确认后再改。
- 都没有：探索仓库 + 访谈后新建。
- 仅有设计文档：保留不动，另建产品真相文件。

## Step 2: 探索仓库

扫描：README、现有 PRD、数据字典、因子/策略目录、监控配置、合规说明。把仓库证据当假设，标注待确认。

形成产品形态假设（可多选但要主次）：

- 投研平台（因子/回测/研究）
- 组合与风控
- 交易执行 / OMS-EMS 类
- 对客产品或业绩展示
- 内部数据与指标中台

## Step 3: 访谈（每轮 ≤3 问）

优先问会改变后续决策的未知：

1. 主用户是谁（研究员 / 交易员 / 风控 / 渠道 / 终端客户），在什么场景下完成什么任务？
2. 产品让什么事成为可能？与邻接系统的边界在哪？
3. 必须守住的硬约束：交易品种池、牌照/合规、延迟、容量、数据供应商、部署环境？

不要在 init 里问审美或页面布局。用户主动给出的绑定约束照实记录。

## Step 4: 写入

### PRODUCT.md（骨架）

```markdown
# Product

## Users
[主用户、场景、任务]

## Product Purpose
[存在理由与成功定义]

## Positioning
[机制差异：别人不好照抄的点]

## Capabilities
[已具备 / 规划中，分开写]

## Non-goals
[明确不做]

## Constraints
[合规、性能、组织、供应商]

## Terminology
[关键术语表]
```

### QUANT.md（骨架）

```markdown
# Quant Context

## Universe
[股票池 / 指数 / 板块；纳入剔除规则]

## Market Assumptions
[T+1、涨跌停、复权默认口径、成本默认假设]

## Signal → Order Contract
[信号时点、下单时点、成交模型]

## Risk & Compliance Red Lines
[硬限制；N/A 需理由]

## Data Authorities
[行情 / 基本面 / 另类；权威源与延迟]

## Open Decisions
[未定事项，禁止假装已定]
```

## Confirm and stop

展示变更摘要，请用户确认；`init` 不继续写 PRD，除非用户明确要求接着 `shape` / `prd`。
