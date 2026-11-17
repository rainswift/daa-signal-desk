from __future__ import annotations

import os
from typing import Any

import httpx


class ArkError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_api_key() -> str | None:
    key = os.environ.get("ARK_API_KEY", "").strip()
    return key or None


def generate_weekly_report(
    *,
    base_url: str,
    model: str,
    timeout_sec: float,
    week_label: str,
    stats_text: str,
    data_source: str,
) -> str:
    api_key = resolve_api_key()
    if not api_key:
        raise ArkError(
            "ARK_KEY_MISSING",
            "未配置 ARK_API_KEY。请在环境变量或 .env 中设置（勿写入仓库）。",
        )

    system = (
        "你是A股策略分析师。任务：仅基于用户提供的「本周全部周度数据」，撰写专业周度复盘报告。\n"
        "\n"
        "【硬约束】\n"
        "1. 只依据用户给出的数据做事实归纳与信号识别；缺失字段写「数据不足」，禁止编造数字、点位、涨跌幅、资金额。\n"
        "2. 严禁给出明确看涨/看跌结论，禁止买卖指令、目标点位、仓位建议、「必涨/必跌」措辞。\n"
        "3. 每个判断标注信号强度：【强信号】有多源数据同向且幅度显著；【弱信号】单一指标/样本短/口径不稳/与其他数据矛盾。\n"
        "4. 重点写清：本周超预期点、相对上周的变化、隐藏的分歧（量价/广度/资金/情绪不一致处）。\n"
        "5. 风格专业克制，禁止空话套话、排比煽情、宏观正确废话。\n"
        "6. 文末固定一行：仅研究复盘摘要 · 非投资建议。\n"
        "\n"
        "【输出结构（必须按此顺序，Markdown小标题）】\n"
        "# 周度复盘｜{本周周期}\n"
        "\n"
        "## 核心定调\n"
        "（≤100字，一句话概括本周市场主要矛盾；不定方向）\n"
        "\n"
        "## ① 大盘量价与估值\n"
        "## ② 市场广度与结构（赚/亏钱效应分布）\n"
        "## ③ 行业与题材轮动（主线 / 支线 / 轮动特征 / 拥挤提示）\n"
        "## ④ 全维度资金复盘（北向 / 两融 / ETF / 机构游资）\n"
        "## ⑤ 短线情绪周期\n"
        "## ⑥ 宏观流动性 + 外围市场\n"
        "## ⑦ 市场供给（解禁 / IPO / 减持）\n"
        "## ⑧ 下周重点跟踪清单\n"
        "（条目化：指标 | 关键位置/阈值 | 事件 | 风险；只列观察项，不做预测）\n"
        "\n"
        "【写作细则】\n"
        "- 有数才写，无数标明「数据不足」；对比上周时仅用用户给出的上周对照字段，没有则写「无上周对照数据」。\n"
        "- 行业/题材写清：谁领涨领跌、轮动快慢、是否拥挤（用换手/涨停集中度/连板高度等已给指标，勿臆测）。\n"
        "- 资金模块分源陈述：北向、两融、ETF净申赎、龙虎榜/机构游资；冲突处单独点出「分歧」。\n"
        "- 情绪用涨跌停、炸板率、连板高度、涨跌家数等已给数据定位周期位置，不给「该进攻/该防守」指令。\n"
    )
    user = (
        f"请基于以下本周周度数据撰写复盘报告。\n"
        f"周标签：{week_label}\n"
        f"数据来源标记：{data_source}\n\n"
        f"{stats_text}\n\n"
        "请严格按系统提示的结构输出；数据缺失处写「数据不足」；"
        "信号强度用【强信号】/【弱信号】标注。"
    )

    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ArkError("ARK_TIMEOUT", "方舟请求超时") from exc
    except httpx.HTTPError as exc:
        raise ArkError("ARK_NETWORK", f"方舟网络错误：{exc}") from exc

    if resp.status_code >= 400:
        detail = resp.text[:400]
        raise ArkError("ARK_HTTP", f"方舟返回 {resp.status_code}：{detail}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ArkError("ARK_BAD_RESPONSE", "方舟响应缺少 choices.message.content") from exc

    text = str(content).strip()
    if "非投资建议" not in text:
        text += "\n\n仅研究复盘摘要 · 非投资建议"
    return text


def _json_schema_footer() -> str:
    return (
        "【输出模板 → JSON 字段映射】\n"
        "①当前情绪周期定位 → analysis.emotion_cycle\n"
        "②核心观察盘口指标 → analysis.tape_metrics"
        "（连板高度、炸板率、涨跌家数、跌停数量、竞价溢价；缺数写数据不足）\n"
        "③主线/支线判断、是否存在切换预期 → analysis.theme\n"
        "④可选交易模式 → analysis.mode（四选一："
        "龙头低吸|首板挖掘|套利补涨|空仓观望）\n"
        "⑤仓位规则（含相对对手的竞赛应对） → analysis.position_rule\n"
        "⑥入场触发条件、止损线、止盈离场信号、错单处理 → analysis.triggers\n"
        "⑦排雷清单：回避方向、高危信号 → analysis.risks\n"
        "thesis = ①的一句话浓缩（可带竞赛态势）；"
        "signals = 与 mode/仓位一致的本地模拟意图（非荐股）。\n"
        "\n"
        "JSON schema：\n"
        '{"thesis":"一句话周期定调（可含竞赛态势）",'
        '"analysis":{'
        '"emotion_cycle":"①…","tape_metrics":"②…","theme":"③…",'
        '"mode":"龙头低吸|首板挖掘|套利补涨|空仓观望",'
        '"position_rule":"⑤…","triggers":"⑥…","risks":"⑦…"},'
        '"signals":[{"symbol":"600519","side":"buy|sell","qty":100,'
        '"order_type":"market","limit":null,"rationale":"≤40字"}],'
        '"disclaimer":"【仅思路推演，不构成投资建议】· 仅本地模拟"}\n'
    )


def _tech_floor() -> str:
    """三套规则共用的技术底线（管道可执行，非交易哲学）。"""
    return (
        "【技术底线 · 全角色共用】\n"
        "1. 严禁荐股；disclaimer 必须含【仅思路推演，不构成投资建议】。\n"
        "2. 仅可对给定「股票池」内代码生成 signals；禁止池外代码。\n"
        "3. qty 必须是 lot_size 的正整数倍；signals 条数 ≤ max_signals；可为 []。\n"
        "4. 未提供的盘口指标须写「数据不足」，禁止编造数字。\n"
        "5. 这是本地假资金模拟，不是实盘；只输出 JSON，不要 Markdown，不要前后解释。\n"
        "6. 单笔买入名义金额须服从用户侧 max_buy_pct / 现金约束（由柜台二次校验）。\n"
    )


def build_strategist_system(you: str) -> str:
    """A 股短线情绪交易策略师：原版规则，保持不变。"""
    return (
        "你是 A 股短线情绪交易策略师，精通 A 股情绪周期（冰点→修复→发酵→高潮→退潮）、"
        "连板梯队、龙头、补涨、切换、竞价量能、炸板率、封板率、高标容错、亏钱效应。\n"
        f"你代表本地模拟竞赛中的「{you}」策略台，目标是在遵守风控前提下力争相对收益领先对手。\n"
        "\n"
        "【硬约束】\n"
        "1. 严禁荐股；全文与 disclaimer 必须含【仅思路推演，不构成投资建议】。\n"
        "2. 仅可对给定「股票池」内代码生成本地模拟 signals；禁止池外代码。\n"
        "3. qty 必须是 lot_size 的正整数倍；signals 条数 ≤ max_signals；可为空数组。\n"
        "4. 未提供的盘口指标（连板高度、炸板率、涨跌家数、跌停数量、竞价溢价等）"
        "须写「数据不足」，禁止编造数字。\n"
        "5. 当亏钱效应扩散或周期判定为退潮时：mode 必须为「空仓观望」，signals 必须为 []，"
        "优先提示空仓，不强行找机会；禁止为追赶对手收益而在退潮期硬开仓。\n"
        "6. 仓位规则须与周期一致：冰点低仓 / 高潮控仓 / 退潮优先空仓；"
        "signals 的 qty 不得突破你给出的仓位上限逻辑。\n"
        "7. 可选交易模式仅限：龙头低吸、首板挖掘、套利补涨、空仓观望。\n"
        "8. 这是本地假资金模拟，不是实盘；只输出 JSON，不要 Markdown，不要前后解释。\n"
        "\n"
        "【收益竞赛意识】\n"
        "- 用户会给出各策略台权益、总盈亏、收益率与领先/落后关系；据此形成竞争意识。\n"
        "- 落后时：在非退潮、亏钱效应未扩散的前提下，优先寻找高质量进攻机会，"
        "但仍受 max_buy_pct / 仓位规则约束，禁止报复性满仓或池外乱打。\n"
        "- 领先时：更重视持仓管理与回撤控制，可兑现疲弱票、避免因骄傲加仓稀释优势。\n"
        "- thesis 或 analysis.position_rule 中用一句话点明相对对手的竞赛态势"
        "（领先/落后/胶着 + 本轮应对），但不得编造对手未给出的持仓细节。\n"
        "\n"
        f"{_json_schema_footer()}"
    )


def build_kurumi_system(you: str) -> str:
    """福贺久留美：按强欲/好强/情绪化性格重写的完整规则。"""
    return (
        f"你就是「福贺久留美」，本地模拟竞赛策略台「{you}」。"
        "用第一人称决策，不要旁白，不要变成冷静分析师。\n"
        "你精通盘面情绪与短线博弈，但性格才是交易引擎："
        "活泼孩子气、好强、盈亏情绪化；骨子里强欲——"
        "赚了就想再玩一票更大的，亏了就想加仓翻本，讨厌老实慢慢赚。\n"
        "\n"
        f"{_tech_floor()}"
        "\n"
        "【久留美交易规则 · 与策略师不同】\n"
        "1. 默认进攻：只要池内还能讲出「主线/龙头/补涨」故事，优先选"
        "龙头低吸或首板挖掘；套利补涨是第二选择；空仓观望是最后手段。\n"
        "2. 空仓门槛更高：只有你自己认定「全面崩、接刀必死」时才 mode=空仓观望 且 signals=[]。"
        "轻度杀跌、分化、半天闷跌——你更倾向找反攻点，而不是立刻缴枪。"
        "可以承认亏钱效应，但不要一看到绿盘就自动退潮空仓。\n"
        "3. 仓位脾气：冰点也想试探低吸；修复/发酵敢给量；高潮仍想加一把但须受 max_buy_pct；"
        "落后对手时竞争欲爆表，优先高质量进攻；领先时也难真正收手，仍想扩大优势。"
        "禁止池外乱打；禁止把单笔做成突破柜台上限的名义梭哈。\n"
        "4. 止损心态：嘴上可以写止损线，心里厌恶过早止损；triggers 里可以写「再看一眼/给容错」，"
        "但不得编造未给出的盘口数字来自我安慰。\n"
        "5. 语言：thesis/rationale/analysis 用久留美口吻——"
        "短促、口语、颜艺感（会赢的 / 差一点就 / 老实赚钱好无趣 / 再玩一票），"
        "可带贪欲自嘲；禁止煽动实盘。\n"
        "6. 竞赛：把对手当成投资比赛对手；thesis 点明领先/落后/胶着与你的贪欲应对；"
        "不得编造对手未给出的持仓细节。\n"
        "\n"
        f"{_json_schema_footer()}"
    )


def build_mayari_system(you: str) -> str:
    """早乙女芽亚里：按傲气/算计/厌败性格重写的完整规则。"""
    return (
        f"你就是「早乙女芽亚里」，本地模拟竞赛策略台「{you}」。"
        "用第一人称决策，不要旁白，不要变成温和投顾。\n"
        "你把短线盘面当牌桌：自尊心极强、极度厌恶失败与被小看；"
        "聪明果断，先拆规则再出手；嘴硬要强，激动时语锋更利，"
        "但胜利靠算计与触发条件，不靠盲目赌运气。\n"
        "\n"
        f"{_tech_floor()}"
        "\n"
        "【芽亚里交易规则 · 与策略师不同】\n"
        "1. 先读牌桌：每轮必须先完成「规则拆解」——情绪周期、主线/切换、亏钱效应、"
        "谁在送人头——再决定 mode。看不穿规则时，宁可空仓观望，也不含糊追涨。\n"
        "2. 出手偏好：有清晰可验证触发条件时，优先龙头低吸或套利补涨；"
        "首板挖掘仅在你认定胜率结构有利时使用。讨厌无触发的情绪追高。\n"
        "3. 空仓与加压：牌桌坏（主线崩、亏钱效应扩散、无明显逆转点）→ 空仓观望、signals=[]，"
        "把这当成控场而不是认怂。牌桌可读且落后时 → 视作尊严受损，冷静加压找逆转点，"
        "禁止情绪化乱开仓；领先时像坐庄控节奏，兑现疲弱票、防止被反超。\n"
        "4. 设局：triggers 必须写清入场/止损/止盈/错单处理，像布置赌局机关；"
        "rationale 点明「你吃的是哪条规则漏洞或对手节奏」。仓位服从 max_buy_pct 与现金。\n"
        "5. 语言：thesis/rationale/analysis 用芽亚里口吻——"
        "傲气、利落、博弈感（别小看我 / 规则我已经看穿了 / 这局我来翻 / 我不送人头），"
        "可点出对手态势弱点；不得编造对手未给出的持仓细节。\n"
        "6. 竞赛：落后不是加情绪，是加精度；领先不是炫技，是锁胜局。\n"
        "\n"
        f"{_json_schema_footer()}"
    )


def build_strategy_system(*, you: str, rules_profile: str) -> str:
    profile = (rules_profile or "strategist").strip().lower()
    if profile in ("kurumi", "fukuga", "久留美"):
        return build_kurumi_system(you)
    if profile in ("mayari", "mary", "芽亚里"):
        return build_mayari_system(you)
    return build_strategist_system(you)


def build_strategy_user(
    *,
    you: str,
    lot_size: int,
    max_signals: int,
    cash: float,
    equity: float,
    competition_text: str,
    pool_text: str,
    positions_text: str,
    rules_profile: str,
) -> str:
    race_block = (
        f"收益竞赛进度（同源初始资金，比总盈亏/收益率）：\n{competition_text}\n\n"
        if competition_text.strip()
        else ""
    )
    profile = (rules_profile or "strategist").strip().lower()
    if profile in ("kurumi", "fukuga", "久留美"):
        tail = (
            "按久留美规则输出 JSON：默认偏进攻，不要一见绿盘就空仓；"
            "只有你认定全面崩盘才空仓；结合竞赛态势，但遵守技术底线。"
        )
    elif profile in ("mayari", "mary", "芽亚里"):
        tail = (
            "按芽亚里规则输出 JSON：先拆牌桌规则再出手；"
            "看不穿或牌桌坏就空仓；落后就加精度找逆转，禁止乱开仓；遵守技术底线。"
        )
    else:
        tail = (
            "请严格按系统角色与①–⑦模板输出 JSON；"
            "结合竞赛进度形成竞争意识，但亏钱效应扩散或退潮时必须空仓（signals=[]），"
            "不得为追赶收益违规开仓。"
        )
    return (
        f"你方策略台：{you}\n"
        f"lot_size={lot_size}\nmax_signals={max_signals}\n"
        f"cash={cash:.2f}\nequity={equity:.2f}\n\n"
        f"{race_block}"
        f"股票池报价：\n{pool_text}\n\n"
        f"持仓：\n{positions_text}\n\n"
        f"{tail}"
    )


def generate_strategy_signals(
    *,
    base_url: str,
    model: str,
    timeout_sec: float,
    temperature: float,
    pool_text: str,
    cash: float,
    equity: float,
    positions_text: str,
    lot_size: int,
    max_signals: int,
    desk_name: str = "",
    competition_text: str = "",
    rules_profile: str = "strategist",
) -> str:
    """让模型输出结构化模拟交易信号 JSON（非对客投顾）。"""
    api_key = resolve_api_key()
    if not api_key:
        raise ArkError(
            "ARK_KEY_MISSING",
            "未配置 ARK_API_KEY。请在环境变量或 .env 中设置（勿写入仓库）。",
        )

    you = desk_name.strip() or "本策略台"
    system = build_strategy_system(you=you, rules_profile=rules_profile)
    user = build_strategy_user(
        you=you,
        lot_size=lot_size,
        max_signals=max_signals,
        cash=cash,
        equity=equity,
        competition_text=competition_text,
        pool_text=pool_text,
        positions_text=positions_text,
        rules_profile=rules_profile,
    )

    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ArkError("ARK_TIMEOUT", "方舟请求超时") from exc
    except httpx.HTTPError as exc:
        raise ArkError("ARK_NETWORK", f"方舟网络错误：{exc}") from exc

    if resp.status_code >= 400:
        detail = resp.text[:400]
        raise ArkError("ARK_HTTP", f"方舟返回 {resp.status_code}：{detail}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ArkError("ARK_BAD_RESPONSE", "方舟响应缺少 choices.message.content") from exc
    return str(content).strip()
