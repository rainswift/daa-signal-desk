---
version: 1
slug: "web-index-html"
primary_target: "web/index.html"
related_targets: []
---

## Scope & mode

- Surface: 本地「大A 指数虚拟盘」主工作台（报价 + 下单 + 账本）
- Visitor mode: **Operate**
- Build path: code-led（决策页锁定）

## Audience & job

- Audience: 个人本地投研者，交易时段本机使用
- Job: 看指数准实时报价并完成模拟下单；账本（现金/持仓/可卖）一眼可对账
- Proof: 降级/熔断状态可见；涨跌幅与可卖为等宽高对比数字，不为装饰让路
- Constraints: 仅指数虚拟标的；仅本地模拟文案常驻；忌游戏感与过炫视觉

## Direction contract

THESIS: 五个指数是五条「线路」——服务灯管状态，报价与下单是主站台，账本是换乘枢纽；拒绝霓虹交易终端与炫技数据艺术。

OWN-WORLD: 站台冷灰底 `#E8ECF0` + 深海军壳 `#0B1F3A`；线路色只落在 8px 色条与状态灯；琥珀 `#F5A623`=降级、朱红 `#C62828`=熔断/涨、叶绿 `#1B7F5A`=跌；IBM Plex Sans Condensed 标签 + IBM Plex Mono 表列数字；发丝分缝、无重阴影。

STORY: 用户先读运营状态，再选线路报价，在中间下单，右侧核对可卖与现金；明白这是模拟且指数不可实盘买卖。

FIRST VIEWPORT: 顶栏品牌+运营状态灯+免责；三栏——左线路报价表（含状态灯）、中下单（买入主按钮、卖出隔离）、右账本枢纽（现金/市值/持仓/可卖/费用）；降级样例报价年龄 14s。

FORM: 城市轨道交通运营状态图（接地列表第 4；骰子指定）。seed:7237bbbd7e86109f。抬升：等宽表列数字；单一强调色只标当前下单标的；发丝对齐槽；卖出键物理隔离。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Memorable moment

指数行左侧色条 + 行尾服务灯；顶栏琥珀灯与「行情降级」文案同亮。

## Unresolved

- 技术栈与路由文件名（暂定 `web/index.html`）
- 是否持久化账户跨会话
