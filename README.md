# 大A 指数虚拟盘

本地「指数盘中准实时虚拟盘」：Vue 3 运营台 + FastAPI 模拟柜台 + SQLite 账本。

配套：`PRODUCT.md` · `QUANT.md` · `TECH.md` · `.impeccable/surfaces/web-index-html.md`

## 启动

```bash
# 后端（127.0.0.1:8000）
cd backend
python3 -m pip install -e ".[dev]"
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端（127.0.0.1:5173）
cd frontend
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173 。

默认 `config.yaml`：`market_source: mock`，`force_session: true`。启动时演示 **行情降级（约 14s）**；下单区可点「恢复行情刷新」后再成交。

真行情（可选）：`pip install -e ".[market]"`，并把 `market_source` 改为 `akshare`。

### 2026 周报（方舟 DeepSeek）

```bash
cp .env.example .env
# 编辑 .env，设置 ARK_API_KEY=...（勿提交；对话中暴露过的 Key 请先在控制台轮换）
```

左侧菜单「2026 周报」→ 选周 →「生成分析」。报告缓存在 SQLite；无 Key 时接口返回明确错误。

## 验收种子

1. 恢复行情 → 买入 100 份上证 → 现金/费用变化；当日可卖=0  
2. 数量 50 → `LOT_SIZE` 拒单，账本不变  
3. 降级状态下下单 → `MARKET_DEGRADED`，无新成交  

`web/index.html` 为方向契约静态参考，不作为运行入口。
