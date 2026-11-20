# 技术方案 — 大A 指数虚拟盘

> 配套：`PRODUCT.md`（产品真相）· `QUANT.md`（量化约束）· `.impeccable/surfaces/web-index-html.md`（视觉方向）  
> 状态：2026-11-13 初稿。区分 **已确认** / **建议默认** / **待确认**。

## 1. 目标

本地单机「指数盘中准实时虚拟盘」：

- 行情约 **10s** 轮询（AKShare）
- 用户手动模拟下单；自研撮合与账本
- 主成功指标：下单 → 成交/拒单 → 现金/持仓/**可卖**/费用 **可对账**
- UI 风格：线路运营台（Operate）；技术栈前端为 **Vue 3**

**非目标（MVP）：** 实盘、个股/ETF、多用户公网、AKQuant 盘中撮合。

## 2. 总体架构

```
Vue 3 (Vite)  localhost:5173
    │  /api/*  proxy
    ▼
FastAPI + uvicorn  localhost:8000
    ├── market     AKShare 轮询 → quotes + quote_age + runtime
    ├── matching   限价/市价 vs 最新价
    ├── ledger     现金·持仓·可卖·费用·订单/成交（权威）
    ├── weekly     2026 周行情聚合 → 方舟 DeepSeek 摘要（缓存）
    ├── calendar   交易日 + 连续竞价时段
    └── store      SQLite
```

| 原则 | 说明 |
|---|---|
| 撮合与记账只在后端 | 浏览器不跑 AKShare / 不改账本 |
| 账本权威 = SQLite | UI 只展示 API 结果 |
| AKQuant 不进撮合路径 | 二期独立研究面 |
| 视觉参考 | 仓库内静态稿可作 token/布局参考；正式 UI 在 `frontend/` |

## 3. 技术选型

| 层 | 选型 | 状态 |
|---|---|---|
| 前端 | Vue 3 + Vite + TypeScript | 已确认 |
| 前端状态 | Pinia | 建议默认 |
| 前端请求 | fetch（或 axios） | 建议默认 |
| 后端 | FastAPI + uvicorn | 建议默认 |
| 行情 | AKShare | 已确认 |
| 持久化 | SQLite（`data/daa.db`） | 建议默认 |
| 配置 | `config.yaml` | 建议默认 |
| 包管理 | 前端 npm/pnpm；后端 uv 或 pip + `pyproject.toml` | 待确认 |

## 4. 目录结构

```
大a/
  PRODUCT.md
  QUANT.md
  TECH.md                 # 本文件
  config.yaml
  frontend/               # Vue 3 + Vite
    src/
      views/DeskView.vue
      views/WeeklyView.vue
      components/
        SideNav.vue
        StatusBar.vue
        QuoteLines.vue
        OrderForm.vue
        LedgerHub.vue
      stores/
        desk.ts
        weekly.ts
      api/client.ts
      styles/tokens.css
    vite.config.ts        # proxy /api → :8000
  backend/
    app/
      main.py
      market.py
      matching.py
      ledger.py
      weekly.py
      llm_ark.py
      calendar.py
      db.py
      schemas.py
    tests/
  data/
    daa.db
  .env.example            # ARK_API_KEY（真实 .env gitignore）
  web/                    # 可选：设计静态参考，不作为运行入口
```

### 周报 API（节选）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/weekly/weeks` | 2026 周列表 + `has_report` |
| GET | `/api/weekly/reports/{week_key}` | 已缓存报告 |
| POST | `/api/weekly/reports/{week_key}?force=` | 按需生成（方舟 `deepseek-v4-1-flash-261017`） |

Key：环境变量 `ARK_API_KEY`（或根目录 `.env`）；`config.yaml` 仅含 `ark.base_url` / `ark.model`。

## 5. 前端（Vue）

### 5.1 页面与组件

| 组件 | 职责 |
|---|---|
| `StatusBar` | 品牌、运营状态灯、报价年龄、降级/熔断文案、免责声明 |
| `QuoteLines` | 五指数线路色条 + 等宽点位/涨跌幅 + 行状态灯 |
| `OrderForm` | 标的/方向/数量/限价；买入主按钮；**卖出键隔离** |
| `LedgerHub` | 现金、市值、持仓、**可卖**、累计费用 |
| `OrderList` | 订单/拒单流水（可 P1） |

布局契约：顶栏 + 三栏（报价 \| 下单 \| 账本），见 surface brief。

### 5.2 视觉 token（实现约束）

| Token | 值 | 用途 |
|---|---|---|
| `--shell` | `#0B1F3A` | 顶栏 |
| `--platform` | `#E8ECF0` | 页面底 |
| `--amber` | `#F5A623` | 降级 |
| `--crimson` | `#C62828` | 熔断 / 上涨 |
| `--leaf` | `#1B7F5A` | 下跌 |
| UI 字体 | IBM Plex Sans Condensed（或等价 Condensed） | 标签 |
| 数字字体 | IBM Plex Mono tabular | 点位/涨跌/可卖 |

线路色仅用于行首约 8px 色条与状态灯，不得淹没数字对比度。

### 5.3 数据流

1. 启动：拉取 `/api/runtime`、`/api/quotes`、`/api/account`、`/api/positions`
2. 每 **10s** 刷新 quotes + runtime
3. 下单：`POST /api/orders` → 成功后刷新 account / positions / orders
4. runtime ≠ `normal` 时：按契约禁用成交类操作并展示原因

### 5.4 开发与代理

```ts
// vite.config.ts（示意）
server: {
  proxy: { '/api': 'http://127.0.0.1:8000' }
}
```

## 6. 后端

### 6.1 模块

| 模块 | 职责 |
|---|---|
| `market` | 定时拉 AKShare 指数快照；写 `fetched_at`；算 `quote_age`；更新 runtime |
| `matching` | 会话门禁、lot、资金/可卖校验；限价/市价 vs `last`；写 fill |
| `ledger` | 账户事务：cash / position / fee；唯一对账权威 |
| `calendar` | 交易日缓存；连续竞价窗 09:30–11:30、13:00–15:00 |
| `db` | SQLite 连接与迁移 |

### 6.2 运行时状态机

| 状态 | 进入 | 行为 |
|---|---|---|
| `normal` | 交易时段且行情年龄达标 | 可下单、可撮合 |
| `degraded` | `quote_age > 15s`（建议）或字段缺失 | 暂停新成交；UI 琥珀 |
| `halted` | 连续拉取失败 ≥ 3（建议） | 拒新单与成交；UI 朱红 |
| `closed` | 非交易时段 | 拒新单；账户只读 |

### 6.3 撮合规则（MVP）

| 项 | 口径 | 状态 |
|---|---|---|
| 标的池 | 000001 / 399001 / 000300 / 399006 / 000688 | 建议默认 |
| 撮合价 | AKShare 指数最新价 `last` | 已确认方向 |
| 市价 | 有有效报价则按 `last` 全成，否则拒单 | 建议默认 |
| 限价买 | `last <= limit` 全成，否则挂单 | 建议默认 |
| 限价卖 | `last >= limit` 全成，否则挂单 | 建议默认 |
| 未成交限价 | **当日收盘自动撤** | 建议默认 |
| 涨跌停 | **MVP N/A**（指数不做涨跌停拒单） | 建议默认 |
| 滑点 | 0 | 建议默认 |
| 部分成交 | 不做；全成或不成 | 建议默认 |
| lot | 100 整数倍 | 已确认方向 |
| T+1 | 当日买入 `qty_sellable=0`；**下一交易日 ≥09:30** 自动解锁（meta 按日幂等） | 已确认 |
| 做空 | 禁止 | 已确认 |

### 6.4 默认费用（可配置）

| 参数 | 默认 |
|---|---|
| `commission_rate` | 0.00025 |
| `min_commission` | 5 元 |
| `stamp_tax_rate` | 0.0005（仅卖出） |
| `transfer_fee_rate` | 0.00001 |
| `initial_cash` | 1_000_000 元 |
| `poll_interval_sec` | 10 |
| `degrade_age_sec` | 15 |
| `halt_fail_count` | 3 |

> 费用模板为 A 股股票近似，用于指数**虚拟**练习，非真实指数交易费率。

## 7. API 契约

统一前缀 `/api`。错误：`{ "code": string, "message": string }`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 进程健康 |
| GET | `/runtime` | `{ state, reason, quote_age_max_sec?, updated_at }` |
| GET | `/quotes` | 指数列表：`symbol, name, last, pct_chg, age_sec, line_state, color` |
| GET | `/account` | `cash, market_value, fees_total, equity` |
| GET | `/positions` | `symbol, qty, qty_sellable, cost, mkt_value` |
| GET | `/orders` | 订单列表（含拒单原因） |
| POST | `/orders` | body: `{ symbol, side, qty, type: "limit"|"market", limit?: number }` |
| POST | `/orders/{id}/cancel` | 撤单（P1） |
| POST | `/account/reset` | 重置模拟账户 |

### 7.1 错误码（建议）

| code | 含义 |
|---|---|
| `OUT_OF_SESSION` | 非交易时段 |
| `MARKET_DEGRADED` | 降级暂停成交 |
| `MARKET_HALTED` | 熔断 |
| `LOT_SIZE` | 非 100 整数倍 |
| `INSUFFICIENT_CASH` | 资金不足 |
| `INSUFFICIENT_SELLABLE` | 可卖不足 |
| `NO_QUOTE` | 无有效报价 |
| `SHORT_NOT_ALLOWED` | 禁止做空 |
| `ORDER_NOT_FOUND` | 订单不存在 |

## 8. 数据模型（SQLite）

- `quotes(symbol PK, name, last, pct_chg, fetched_at, source)`
- `orders(id, symbol, side, qty, type, limit_price, status, reason, created_at, updated_at)`
- `fills(id, order_id, price, qty, commission, stamp_tax, transfer_fee, traded_at)`
- `positions(symbol PK, qty, qty_sellable, cost_basis)`
- `account(id, cash, fees_total, updated_at)` — MVP 单账户
- `runtime_events(id, state, reason, at)`
- `meta(key, value)` — 如日历缓存版本

**对账键：** `order_id` / `fill_id` + `symbol` + `trade_date`。

**对账验收（实现时钉死一种权益公式并写测试）：**  
订单流水与 `cash`、`positions`、`fees_total` 同事务一致；拒单后账本不变。

## 9. 行情接入

| 项 | 说明 |
|---|---|
| 源 | AKShare 指数 spot（东财/新浪，实现时锁定一个并记入 config） |
| 周期 | 10s；同步调用放线程池，设超时 |
| 时间戳 | 上游无事件时间时，用**本地拉取成功时刻**作 `fetched_at`，UI 标注「拉取时刻」 |
| 失败 | 计入连续失败；达阈 → `halted` |
| 恢复 | 建议：连续成功 M=2 次退出熔断（待确认） |

## 10. 本地启动（目标）

```bash
# 后端
cd backend && uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm run dev
```

浏览器打开 Vite 地址（通常 `http://127.0.0.1:5173`）。

## 11. 实施切片

| 阶段 | 交付 | 验收种子 |
|---|---|---|
| **P0** | Vue 壳接 API；SQLite 账本；mock 或真行情二选一；市价/限价即时成交；拒单码 | 幸福路径买入；LOT_SIZE 拒单 |
| **P1** | AKShare 10s 轮询；degraded/halted；顶栏状态 | 降级无新成交 |
| **P2** | 限价挂单、收盘撤单、撤单 API（T+1 次日 ≥09:30 自动解锁已落地） | 挂单收盘撤可测 |
| **P3** | 账户重置打磨、订单列表、可选 SSE | 跨会话持久化 |
| **P4** | AKQuant 回测页（与虚拟盘指标分栏） | 研究指标 ≠ 虚拟盘承诺 |

## 12. 测试策略

| 类型 | 内容 |
|---|---|
| 单元 | 费用计算、lot 校验、T+1 可卖、限价条件 |
| 集成 | POST order 事务后 DB 断言 |
| 契约 | 前端 fixtures 对 API schema |
| 手工 | 交易时段外拒单；断行情进 degraded/halted |

## 13. 安全与合规（工程）

- 仅监听 `127.0.0.1`（建议默认）
- UI 常驻：「仅本地模拟 · 非投资建议 · 指数为虚拟标的」
- 不把回测/虚拟盘收益写成实盘可期
- 不接券商密钥；无实盘通道代码进 MVP

## 14. 待确认清单

| # | 项 | 建议默认 |
|---|---|---|
| 1 | ~~T+1 解锁时点~~ | **已确认：次日 ≥09:30 自动** |
| 2 | 限价未成交 | 收盘自动撤 |
| 3 | 指数涨跌停 | MVP N/A |
| 4 | 熔断恢复 | 连续成功 2 次自动恢复 |
| 5 | 包管理 | 前端 pnpm；后端 uv |
| 6 | 多账户 | MVP 单账户 |
| 7 | `web/` 静态稿 | 保留作视觉参考，不双轨运行 |

---

修订时同步：`PRODUCT.md` / `QUANT.md` 中与本文件冲突的「待确认」项，以产品确认结果为准回写两端。
