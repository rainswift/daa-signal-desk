"""
A股周度复盘数据采集（akshare + pandas）。

供后台 `weekly.py` 与 `scripts/weekly_review_collect.py` 共用。

口径备注：
- 万得全A无稳定公开接口：用「国证A指(399317)」近似，并在 note 标明
- 北向资金东财历史自约 2024-08 后常为空：失败时 status=missing
- 东财 push2 易限流：指数优先腾讯日线；行业/ETF 等失败会降级并提示
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger("daa.weekly_collect")
CN = ZoneInfo("Asia/Shanghai")
SLEEP = 0.35  # 降低连续请求触发限流的概率
_VERBOSE = False  # 库调用默认安静；CLI 经 collect_week_bundle(verbose=True) 打开


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(CN)


def _to_date(v: Any) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def safe_call(label: str, fn: Callable[[], Any], default: Any = None) -> Any:
    """接口异常友好捕获，不中断整流程。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        msg = f"{label} 失败：{type(exc).__name__}: {exc}"
        log.warning(msg)
        if _VERBOSE:
            print(f"[WARN] {msg}")
        return default


def sleep_bit() -> None:
    time.sleep(SLEEP)


def _say(msg: str) -> None:
    log.info(msg)
    if _VERBOSE:
        print(msg)


class RowBag:
    """汇总行收集器 → DataFrame / CSV。"""

    COLS = [
        "week_start",
        "week_end",
        "module",
        "item",
        "code",
        "name",
        "metric",
        "value",
        "unit",
        "note",
        "status",
    ]

    def __init__(self, week_start: date, week_end: date) -> None:
        self.week_start = week_start
        self.week_end = week_end
        self.rows: list[dict[str, Any]] = []

    def add(
        self,
        module: str,
        item: str,
        metric: str,
        value: Any,
        *,
        code: str = "",
        name: str = "",
        unit: str = "",
        note: str = "",
        status: str = "ok",
    ) -> None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            value = ""
            if status == "ok":
                status = "missing"
        self.rows.append(
            {
                "week_start": self.week_start.isoformat(),
                "week_end": self.week_end.isoformat(),
                "module": module,
                "item": item,
                "code": code,
                "name": name,
                "metric": metric,
                "value": value,
                "unit": unit,
                "note": note,
                "status": status,
            }
        )
        flag = "OK" if status == "ok" else status.upper()
        shown = value if value != "" else "数据不足"
        _say(f"  [{flag}] {module}/{item}/{metric}: {shown} {unit} {note}".rstrip())

    def missing(self, module: str, item: str, metric: str, note: str, **kwargs: Any) -> None:
        self.add(module, item, metric, "", note=note, status="missing", **kwargs)

    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=self.COLS)


# ---------------------------------------------------------------------------
# 交易周识别（模块：meta）
# ---------------------------------------------------------------------------

def load_trade_dates() -> list[date]:
    import akshare as ak

    raw = ak.calendar_trade_date_hist_sina()
    col = "trade_date" if "trade_date" in raw.columns else raw.columns[0]
    dates = sorted({d for d in (_to_date(x) for x in raw[col]) if d is not None})
    return dates


def resolve_last_complete_week(
    trade_dates: list[date],
    today: Optional[date] = None,
    *,
    friday_close_hour: int = 15,
    friday_close_minute: int = 5,
) -> tuple[date, date, list[date]]:
    """
    最近一个完整交易周：自然周周一~周五内、落在交易日历上的全部交易日。
    若本周尚未收完（周中，或周五未过收盘），则回退到上一自然周。
    """
    today = today or _now().date()
    now = _now()
    traded = [d for d in trade_dates if d <= today]
    if not traded:
        raise RuntimeError("交易日历为空，无法识别交易周")

    def week_window(any_day: date) -> tuple[date, date, list[date]]:
        monday = any_day - timedelta(days=any_day.weekday())
        friday = monday + timedelta(days=4)
        days = [d for d in trade_dates if monday <= d <= friday]
        return monday, friday, days

    last = traded[-1]
    monday, friday, days = week_window(last)

    incomplete = False
    if friday > today:
        incomplete = True
    elif friday == today:
        if now.hour < friday_close_hour or (
            now.hour == friday_close_hour and now.minute < friday_close_minute
        ):
            incomplete = True
    elif last < friday and friday <= today:
        # 周五休市但周已过完 → 完整
        incomplete = False
    elif last.weekday() < 4 and monday <= today <= friday:
        incomplete = True

    if incomplete or not days:
        prev_anchor = monday - timedelta(days=1)
        monday, friday, days = week_window(prev_anchor)
        # 若仍空（长假），继续回退最多 8 周
        for _ in range(8):
            if days:
                break
            monday, friday, days = week_window(monday - timedelta(days=1))

    if not days:
        raise RuntimeError("未能定位到含交易日的完整周")
    return monday, friday, days


# ---------------------------------------------------------------------------
# 1) 主要指数 → 复盘模块「指数数据 / ①大盘量价」
# ---------------------------------------------------------------------------

INDEX_LIST = [
    # code_tx: 腾讯/新浪符号；万得全A用国证A指近似
    ("sh000001", "000001", "上证综指", False),
    ("sz399001", "399001", "深证成指", False),
    ("sz399006", "399006", "创业板指", False),
    ("sh000688", "000688", "科创50", False),
    ("sh000300", "000300", "沪深300", False),
    ("sh000905", "000905", "中证500", False),
    ("sz399317", "399317", "国证A指(近似万得全A)", True),
]


def _filter_week(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    date_col = "date" if "date" in out.columns else ("日期" if "日期" in out.columns else None)
    if date_col is None:
        return pd.DataFrame()
    out["_d"] = out[date_col].map(_to_date)
    return out.loc[(out["_d"] >= start) & (out["_d"] <= end)].sort_values("_d")


def fetch_index_daily(symbol: str) -> Optional[pd.DataFrame]:
    """优先腾讯（含成交额/换手），失败回落新浪。"""
    import akshare as ak

    df = safe_call(
        f"index_zh_daily_tx({symbol})",
        lambda: ak.index_zh_daily_tx(symbol=symbol),
    )
    if df is not None and not df.empty:
        return df
    sleep_bit()
    df = safe_call(
        f"index_zh_daily_sina({symbol})",
        lambda: ak.index_zh_daily_sina(symbol=symbol),
    )
    return df


def collect_indices(bag: RowBag, week_days: list[date]) -> None:
    start, end = week_days[0], week_days[-1]
    _say("\n=== 1) 主要指数（周涨跌/成交额/振幅/换手）===")
    for i, (sym, code, name, is_proxy) in enumerate(INDEX_LIST):
        if i:
            sleep_bit()
        df = fetch_index_daily(sym)
        sub = _filter_week(df, start, end) if df is not None else pd.DataFrame()
        note = "万得全A无公开稳定源，以国证A指近似" if is_proxy else "日线周聚合"
        if sub.empty:
            for m in ("周涨跌幅", "周成交额", "周振幅", "周换手率"):
                bag.missing("index", name, m, note=f"{note}；无K线", code=code, name=name)
            continue

        o = float(sub.iloc[0]["open"])
        c = float(sub.iloc[-1]["close"])
        h = float(sub["high"].max())
        l = float(sub["low"].min())
        pct = round((c / o - 1) * 100, 4) if o else None
        amp = round((h - l) / o * 100, 4) if o else None

        if "amount" in sub.columns:
            amount = float(sub["amount"].sum())
            amount_yi = round(amount / 1e8, 4)
            bag.add("index", name, "周成交额", amount_yi, code=code, name=name, unit="亿元", note=note)
        else:
            bag.missing("index", name, "周成交额", "源无成交额字段", code=code, name=name)

        if "turnover" in sub.columns:
            # 腾讯换手多为小数（0.01=1%），周换手用交易日简单平均
            turns = pd.to_numeric(sub["turnover"], errors="coerce").dropna()
            if not turns.empty:
                avg = float(turns.mean())
                # 若均值 < 0.25 视为小数口径 → 转百分数
                turn_pct = round(avg * 100, 4) if avg < 0.25 else round(avg, 4)
                bag.add(
                    "index",
                    name,
                    "周换手率",
                    turn_pct,
                    code=code,
                    name=name,
                    unit="%",
                    note=note + "；交易日换手简单平均",
                )
            else:
                bag.missing("index", name, "周换手率", "换手为空", code=code, name=name)
        else:
            bag.missing("index", name, "周换手率", "源无换手字段", code=code, name=name)

        bag.add("index", name, "周涨跌幅", pct, code=code, name=name, unit="%", note=note)
        bag.add("index", name, "周振幅", amp, code=code, name=name, unit="%", note=note)
        bag.add("index", name, "周开盘", round(o, 4), code=code, name=name, unit="点", note=note)
        bag.add("index", name, "周收盘", round(c, 4), code=code, name=name, unit="点", note=note)
        bag.add(
            "index",
            name,
            "交易日数",
            int(len(sub)),
            code=code,
            name=name,
            unit="日",
            note=note,
        )


# ---------------------------------------------------------------------------
# 2) 市场宽度 → 「市场宽度 / ②广度与结构」
# ---------------------------------------------------------------------------

def collect_breadth(bag: RowBag, week_days: list[date]) -> None:
    """
    公开源对「历史每日涨跌家数/中位数/新高新低」支持弱：
    - 若周五=今天：用乐咕乐股当日快照作参考（弱信号）
    - 创新高/新低：同花顺阶段榜快照（弱信号）
    - 否则标记 missing，避免编造
    """
    import akshare as ak

    _say("\n=== 2) 市场宽度（涨跌家数/中位数/新高新低）===")
    today = _now().date()
    end = week_days[-1]

    if end == today:
        act = safe_call("stock_market_activity_legu", ak.stock_market_activity_legu)
        if isinstance(act, pd.DataFrame) and not act.empty:
            mp = {str(r["item"]): r["value"] for _, r in act.iterrows()}
            bag.add(
                "breadth",
                "全市场",
                "上涨家数",
                mp.get("上涨", ""),
                unit="家",
                note="乐咕当日快照；非严格周累计【弱】",
            )
            bag.add(
                "breadth",
                "全市场",
                "下跌家数",
                mp.get("下跌", ""),
                unit="家",
                note="乐咕当日快照；非严格周累计【弱】",
            )
        else:
            bag.missing("breadth", "全市场", "上涨家数", "乐咕接口失败")
            bag.missing("breadth", "全市场", "下跌家数", "乐咕接口失败")
    else:
        bag.missing(
            "breadth",
            "全市场",
            "上涨家数",
            "akshare无稳定历史日度涨跌家数；请手工补或换数据源",
        )
        bag.missing(
            "breadth",
            "全市场",
            "下跌家数",
            "akshare无稳定历史日度涨跌家数；请手工补或换数据源",
        )

    bag.missing(
        "breadth",
        "全市场",
        "涨跌幅中位数",
        "需全市场个股日收益截面，免费接口成本过高；请手工补",
        unit="%",
    )

    # 同花顺创新高/新低（快照）
    sleep_bit()
    cxg = safe_call("stock_rank_cxg_ths", lambda: ak.stock_rank_cxg_ths(symbol="创月新高"))
    sleep_bit()
    cxd = safe_call("stock_rank_cxd_ths", lambda: ak.stock_rank_cxd_ths(symbol="创月新低"))
    if isinstance(cxg, pd.DataFrame):
        bag.add(
            "breadth",
            "全市场",
            "阶段新高数量",
            int(len(cxg)),
            unit="家",
            note="同花顺「创月新高」快照，非本周严格统计【弱】",
        )
    else:
        bag.missing("breadth", "全市场", "阶段新高数量", "同花顺创新高接口失败", unit="家")
    if isinstance(cxd, pd.DataFrame):
        bag.add(
            "breadth",
            "全市场",
            "阶段新低数量",
            int(len(cxd)),
            unit="家",
            note="同花顺「创月新低」快照，非本周严格统计【弱】",
        )
    else:
        bag.missing("breadth", "全市场", "阶段新低数量", "同花顺创新低接口失败", unit="家")


# ---------------------------------------------------------------------------
# 3) 行业板块 → 「行业板块 / ③行业与题材」
# ---------------------------------------------------------------------------

def _industry_fallback_ths(bag: RowBag) -> None:
    import akshare as ak

    ths = safe_call("stock_board_industry_summary_ths", ak.stock_board_industry_summary_ths)
    if not isinstance(ths, pd.DataFrame) or ths.empty:
        bag.missing("industry", "申万一级", "周涨跌幅", "东财/同花顺行业接口均失败")
        bag.missing("industry", "申万一级", "板块成交额", "东财/同花顺行业接口均失败")
        return
    pct_col = next((c for c in ths.columns if "涨跌" in str(c)), None)
    name_col = next((c for c in ths.columns if "名称" in str(c) or "板块" in str(c)), ths.columns[0])
    if not pct_col:
        bag.missing("industry", "行业", "周涨跌幅", "同花顺行业无涨跌列")
        return
    tmp = ths[[name_col, pct_col]].copy()
    tmp[pct_col] = pd.to_numeric(tmp[pct_col], errors="coerce")
    tmp = tmp.dropna().sort_values(pct_col, ascending=False)
    for _, r in tmp.iterrows():
        bag.add(
            "industry",
            str(r[name_col]),
            "周涨跌幅",
            round(float(r[pct_col]), 4),
            name=str(r[name_col]),
            unit="%",
            note="同花顺行业快照降级，非周聚合【弱】",
            status="degraded",
        )
    bag.missing("industry", "全行业", "板块成交额", "降级源无周成交额")


def collect_industry(bag: RowBag, week_days: list[date], *, full_industry: bool = False) -> None:
    """
    默认：同花顺行业快照降级（避免东财全市场板块日K连环限流）。
    --full-industry：逐个东财行业日K做真周聚合（慢，易限流）。
    """
    import akshare as ak

    _say("\n=== 3) 申万一级/行业周涨跌与成交额 ===")
    if not full_industry:
        _say("  （默认快速模式：同花顺快照；真周聚合请加 --full-industry）")
        _industry_fallback_ths(bag)
        return

    start, end = week_days[0], week_days[-1]
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    names = safe_call("stock_board_industry_name_em", ak.stock_board_industry_name_em)
    if names is None or getattr(names, "empty", True):
        _industry_fallback_ths(bag)
        return

    rows_pct: list[tuple[str, float, float]] = []
    fail_streak = 0
    for i, (_, row) in enumerate(names.iterrows()):
        bname = str(row.get("板块名称") or row.get("name") or "")
        if not bname:
            continue
        if i:
            sleep_bit()
        hist = safe_call(
            f"industry_hist({bname})",
            lambda n=bname: ak.stock_board_industry_hist_em(
                symbol=n,
                start_date=start_s,
                end_date=end_s,
                period="日k",
                adjust="",
            ),
        )
        if hist is None or getattr(hist, "empty", True):
            fail_streak += 1
            if fail_streak >= 5 and not rows_pct:
                _say("  [WARN] 东财行业连续失败，降级同花顺快照")
                _industry_fallback_ths(bag)
                return
            continue
        fail_streak = 0
        sub = hist.copy()
        dcol = "日期" if "日期" in sub.columns else "date"
        sub["_d"] = sub[dcol].map(_to_date)
        sub = sub.loc[(sub["_d"] >= start) & (sub["_d"] <= end)].sort_values("_d")
        if sub.empty:
            continue
        ocol = "开盘" if "开盘" in sub.columns else "open"
        ccol = "收盘" if "收盘" in sub.columns else "close"
        acol = "成交额" if "成交额" in sub.columns else ("amount" if "amount" in sub.columns else None)
        o, c = float(sub.iloc[0][ocol]), float(sub.iloc[-1][ccol])
        pct = (c / o - 1) * 100 if o else None
        amt = float(pd.to_numeric(sub[acol], errors="coerce").fillna(0).sum()) if acol else None
        if pct is not None:
            rows_pct.append((bname, float(pct), float(amt) if amt is not None else float("nan")))

    if not rows_pct:
        _industry_fallback_ths(bag)
        return

    rows_pct.sort(key=lambda x: x[1], reverse=True)
    for bname, pct, amt in rows_pct:
        bag.add(
            "industry",
            bname,
            "周涨跌幅",
            round(pct, 4),
            name=bname,
            unit="%",
            note="东财行业板块日K周聚合（近似申万一级，以源名称为准）",
        )
        if pd.notna(amt):
            bag.add(
                "industry",
                bname,
                "板块成交额",
                round(amt / 1e8, 4),
                name=bname,
                unit="亿元",
                note="周内成交额求和",
            )


# ---------------------------------------------------------------------------
# 4) 资金 → 「资金数据 / ④全维度资金」
# ---------------------------------------------------------------------------

def collect_capital(bag: RowBag, week_days: list[date]) -> None:
    import akshare as ak

    _say("\n=== 4) 资金（北向 / 两融 / 股票ETF）===")
    start, end = week_days[0], week_days[-1]

    # 北向：沪股通+深股通（东财近年常空）
    north_sum = 0.0
    north_ok = False
    for sym in ("沪股通", "深股通"):
        sleep_bit()
        hist = safe_call(f"stock_hsgt_hist_em({sym})", lambda s=sym: ak.stock_hsgt_hist_em(symbol=s))
        if hist is None or getattr(hist, "empty", True):
            continue
        sub = hist.copy()
        sub["_d"] = sub["日期"].map(_to_date)
        sub = sub.loc[(sub["_d"] >= start) & (sub["_d"] <= end)]
        col = "当日成交净买额"
        vals = pd.to_numeric(sub[col], errors="coerce") if col in sub.columns else pd.Series(dtype=float)
        if vals.notna().any():
            north_sum += float(vals.fillna(0).sum())
            north_ok = True

    if north_ok:
        bag.add(
            "capital",
            "北向资金",
            "周累计净买入",
            round(north_sum, 4),
            unit="亿元",
            note="沪股通+深股通「当日成交净买额」周求和",
        )
    else:
        bag.missing(
            "capital",
            "北向资金",
            "周累计净买入",
            "东财北向字段近年常为空（约2024-08后）；请换数据源手工补",
            unit="亿元",
        )

    # 两融：沪市区间 + 深市按日
    sleep_bit()
    sse = safe_call(
        "stock_margin_sse",
        lambda: ak.stock_margin_sse(
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        ),
    )
    sse_map: dict[date, float] = {}
    if isinstance(sse, pd.DataFrame) and not sse.empty:
        dcol = "信用交易日期" if "信用交易日期" in sse.columns else sse.columns[0]
        bcol = "融资融券余额"
        for _, r in sse.iterrows():
            ds = str(r[dcol]).replace("-", "")[:8]
            try:
                d = datetime.strptime(ds, "%Y%m%d").date()
            except ValueError:
                continue
            sse_map[d] = float(r[bcol]) / 1e8  # 元 → 亿元

    sz_map: dict[date, float] = {}
    for d in week_days:
        sleep_bit()
        one = safe_call(
            f"stock_margin_szse({d})",
            lambda day=d: ak.stock_margin_szse(date=day.strftime("%Y%m%d")),
        )
        if isinstance(one, pd.DataFrame) and not one.empty and "融资融券余额" in one.columns:
            # 深交所接口单位多为亿元
            sz_map[d] = float(pd.to_numeric(one.iloc[0]["融资融券余额"], errors="coerce"))

    # 取周内首末有数的交易日余额差
    all_days = sorted(set(sse_map) | set(sz_map))
    all_days = [d for d in all_days if start <= d <= end]
    if len(all_days) >= 1:
        def bal(day: date) -> Optional[float]:
            s, z = sse_map.get(day), sz_map.get(day)
            if s is None and z is None:
                return None
            return (s or 0.0) + (z or 0.0)

        first = next((bal(d) for d in all_days if bal(d) is not None), None)
        last = next((bal(d) for d in reversed(all_days) if bal(d) is not None), None)
        if first is not None and last is not None:
            bag.add(
                "capital",
                "两融",
                "周初余额",
                round(first, 4),
                unit="亿元",
                note="沪+深融资融券余额；深市单位按亿元口径",
            )
            bag.add(
                "capital",
                "两融",
                "周末余额",
                round(last, 4),
                unit="亿元",
                note="沪+深融资融券余额",
            )
            bag.add(
                "capital",
                "两融",
                "周变动",
                round(last - first, 4),
                unit="亿元",
                note="周末余额-周初余额",
            )
        else:
            bag.missing("capital", "两融", "周变动", "两融余额解析失败", unit="亿元")
    else:
        bag.missing("capital", "两融", "周变动", "两融接口无周内数据", unit="亿元")

    # 股票ETF：东财现货若含近1周份额变动则汇总；否则 missing
    sleep_bit()
    etf = safe_call("fund_etf_spot_em", ak.fund_etf_spot_em)
    if isinstance(etf, pd.DataFrame) and not etf.empty:
        # 常见列名兼容
        cand = [c for c in etf.columns if "申购" in str(c) or "赎回" in str(c) or "净申购" in str(c)]
        share_cols = [c for c in etf.columns if "份额" in str(c)]
        if cand:
            total = 0.0
            for c in cand:
                total += float(pd.to_numeric(etf[c], errors="coerce").fillna(0).sum())
            bag.add(
                "capital",
                "股票ETF",
                "周净申赎汇总",
                round(total, 4),
                unit="视源字段",
                note=f"东财ETF现货列汇总: {cand}【弱，口径视源】",
                status="degraded",
            )
        elif share_cols:
            bag.missing(
                "capital",
                "股票ETF",
                "周净申赎汇总",
                f"仅有份额列{share_cols[:3]}，无周净申赎字段；请换专门申赎数据源",
            )
        else:
            bag.missing("capital", "股票ETF", "周净申赎汇总", "ETF现货无申赎相关列")
    else:
        bag.missing("capital", "股票ETF", "周净申赎汇总", "fund_etf_spot_em 失败或限流")


# ---------------------------------------------------------------------------
# 5) 情绪 → 「情绪数据 / ⑤短线情绪」
# ---------------------------------------------------------------------------

def collect_emotion(bag: RowBag, week_days: list[date]) -> None:
    import akshare as ak

    _say("\n=== 5) 情绪（涨停/跌停/炸板率/连板高度）===")
    zt_daily: list[int] = []
    dt_daily: list[int] = []
    zb_daily: list[int] = []
    max_lb = 0

    for d in week_days:
        ds = d.strftime("%Y%m%d")
        sleep_bit()
        zt = safe_call(f"stock_zt_pool_em({ds})", lambda x=ds: ak.stock_zt_pool_em(date=x))
        sleep_bit()
        dt = safe_call(f"stock_zt_pool_dtgc_em({ds})", lambda x=ds: ak.stock_zt_pool_dtgc_em(date=x))
        sleep_bit()
        zb = safe_call(f"stock_zt_pool_zbgc_em({ds})", lambda x=ds: ak.stock_zt_pool_zbgc_em(date=x))

        ztn = int(len(zt)) if isinstance(zt, pd.DataFrame) else 0
        dtn = int(len(dt)) if isinstance(dt, pd.DataFrame) else 0
        zbn = int(len(zb)) if isinstance(zb, pd.DataFrame) else 0
        if isinstance(zt, pd.DataFrame) and not zt.empty:
            zt_daily.append(ztn)
            lb_col = next((c for c in zt.columns if "连板" in str(c)), None)
            if lb_col is not None:
                mx = pd.to_numeric(zt[lb_col], errors="coerce").max()
                if pd.notna(mx):
                    max_lb = max(max_lb, int(mx))
        if isinstance(dt, pd.DataFrame) and not dt.empty:
            dt_daily.append(dtn)
        if isinstance(zb, pd.DataFrame) and not zb.empty:
            zb_daily.append(zbn)

        # 日度也落库，便于核对
        bag.add("emotion", f"日_{ds}", "涨停家数", ztn, unit="家", note="东财涨停池")
        bag.add("emotion", f"日_{ds}", "跌停家数", dtn, unit="家", note="东财跌停池")
        bag.add("emotion", f"日_{ds}", "炸板家数", zbn, unit="家", note="东财炸板池")
        if ztn + zbn > 0:
            bag.add(
                "emotion",
                f"日_{ds}",
                "炸板率",
                round(zbn / (ztn + zbn) * 100, 2),
                unit="%",
                note="炸板/(涨停+炸板)",
            )

    if zt_daily:
        bag.add("emotion", "全周", "涨停家数合计", int(sum(zt_daily)), unit="家", note="日涨停家数求和")
        bag.add(
            "emotion",
            "全周",
            "涨停家数日均",
            round(sum(zt_daily) / len(zt_daily), 2),
            unit="家",
            note="",
        )
    else:
        bag.missing("emotion", "全周", "涨停家数合计", "涨停池全周无数据", unit="家")

    if dt_daily:
        bag.add("emotion", "全周", "跌停家数合计", int(sum(dt_daily)), unit="家", note="日跌停家数求和")
        bag.add(
            "emotion",
            "全周",
            "跌停家数日均",
            round(sum(dt_daily) / len(dt_daily), 2),
            unit="家",
            note="",
        )
    else:
        bag.missing("emotion", "全周", "跌停家数合计", "跌停池全周无数据", unit="家")

    if zt_daily or zb_daily:
        z_sum, b_sum = sum(zt_daily), sum(zb_daily)
        if z_sum + b_sum > 0:
            bag.add(
                "emotion",
                "全周",
                "炸板率",
                round(b_sum / (z_sum + b_sum) * 100, 2),
                unit="%",
                note="周内合计：炸板/(涨停+炸板)",
            )
        else:
            bag.missing("emotion", "全周", "炸板率", "涨停+炸板均为0", unit="%")
    else:
        bag.missing("emotion", "全周", "炸板率", "无涨停/炸板数据", unit="%")

    if max_lb > 0:
        bag.add("emotion", "全周", "连板高度", max_lb, unit="板", note="周内涨停池连板数最大值")
    else:
        bag.missing("emotion", "全周", "连板高度", "无连板数字段或全周无涨停", unit="板")


# ---------------------------------------------------------------------------
# 6) 宏观外围 → 「宏观&外围 / ⑥宏观流动性+外围」
# ---------------------------------------------------------------------------

def collect_macro(bag: RowBag, week_days: list[date]) -> None:
    import akshare as ak

    _say("\n=== 6) 宏观外围（美元指数 / 美债10Y / 在岸人民币）===")
    start, end = week_days[0], week_days[-1]

    # 美元指数：全球指数表找名称再拉历史；失败则 endpoint 直接试
    dxy = None
    table = safe_call("index_global_name_table", ak.index_global_name_table)
    dxy_name = None
    if isinstance(table, pd.DataFrame) and not table.empty:
        hit = table[table.astype(str).apply(lambda r: r.str.contains("美元指数", na=False)).any(axis=1)]
        if not hit.empty:
            for col in ("指数名称", "name", "名称"):
                if col in hit.columns:
                    dxy_name = str(hit.iloc[0][col])
                    break
            if dxy_name is None:
                dxy_name = str(hit.iloc[0, 0])

    if dxy_name:
        sleep_bit()
        dxy = safe_call(
            f"index_global_hist_em({dxy_name})",
            lambda n=dxy_name: ak.index_global_hist_em(symbol=n),
        )
    if dxy is None:
        sleep_bit()
        dxy = safe_call("index_global_hist_sina(DINIW)", lambda: ak.index_global_hist_sina(symbol="DINIW"))

    if isinstance(dxy, pd.DataFrame) and not dxy.empty:
        sub = _filter_week(dxy, start, end)
        if sub.empty:
            sub = dxy.tail(5)
            note = "周内无点，退回最近可得【弱】"
        else:
            note = "周内日线"
        ccol = "close" if "close" in sub.columns else ("收盘" if "收盘" in sub.columns else sub.columns[-1])
        o = float(pd.to_numeric(sub.iloc[0][ccol], errors="coerce"))
        c = float(pd.to_numeric(sub.iloc[-1][ccol], errors="coerce"))
        bag.add("macro", "美元指数", "周收", round(c, 4), unit="点", note=note)
        if o:
            bag.add("macro", "美元指数", "周涨跌幅", round((c / o - 1) * 100, 4), unit="%", note=note)
    else:
        bag.missing("macro", "美元指数", "周收", "全球指数接口失败")

    # 10Y 美债
    sleep_bit()
    yld = safe_call("bond_zh_us_yield_em", ak.bond_zh_us_yield_em)
    if isinstance(yld, pd.DataFrame) and not yld.empty:
        sub = yld.copy()
        sub["_d"] = sub["日期"].map(_to_date)
        sub = sub.loc[(sub["_d"] >= start) & (sub["_d"] <= end)].sort_values("_d")
        col = "美国国债收益率10年"
        if sub.empty or col not in sub.columns:
            bag.missing("macro", "美债10Y", "周收", "周内无美债10Y")
        else:
            o = float(sub.iloc[0][col])
            c = float(sub.iloc[-1][col])
            bag.add("macro", "美债10Y", "周初", round(o, 4), unit="%", note="美国国债收益率10年")
            bag.add("macro", "美债10Y", "周收", round(c, 4), unit="%", note="美国国债收益率10年")
            bag.add("macro", "美债10Y", "周变动bp", round((c - o) * 100, 2), unit="bp", note="(周末-周初)*100")
    else:
        bag.missing("macro", "美债10Y", "周收", "bond_zh_us_yield_em 失败")

    # 在岸人民币：fx_spot_quote 为实时；hist 若有则周聚合
    sleep_bit()
    fx_hist = safe_call("fx_hist_em", lambda: ak.fx_hist_em(symbol="USDCNH"))
    # 在岸优先 USDCNY
    if fx_hist is None or getattr(fx_hist, "empty", True):
        sleep_bit()
        fx_hist = safe_call("fx_hist_em_USDCNY", lambda: ak.fx_hist_em(symbol="USDCNY"))

    used_spot = False
    if isinstance(fx_hist, pd.DataFrame) and not fx_hist.empty:
        sub = _filter_week(fx_hist, start, end)
        ccol = next((c for c in ("收盘价", "最新价", "close", "收盘") if c in (sub.columns if not sub.empty else fx_hist.columns)), None)
        if not sub.empty and ccol:
            o = float(pd.to_numeric(sub.iloc[0][ccol], errors="coerce"))
            c = float(pd.to_numeric(sub.iloc[-1][ccol], errors="coerce"))
            bag.add("macro", "在岸人民币", "周收", round(c, 4), unit="USD/CNY", note="外汇历史周聚合")
            if o:
                bag.add(
                    "macro",
                    "在岸人民币",
                    "周变动",
                    round(c - o, 4),
                    unit="",
                    note="周末-周初",
                )
        else:
            used_spot = True
    else:
        used_spot = True

    if used_spot:
        sleep_bit()
        spot = safe_call("fx_spot_quote", ak.fx_spot_quote)
        if isinstance(spot, pd.DataFrame) and not spot.empty:
            hit = spot[spot["货币对"].astype(str).str.replace(" ", "") == "USD/CNY"]
            if hit.empty:
                hit = spot[spot["货币对"].astype(str).str.contains("USD/CNY", na=False)]
            if not hit.empty:
                bid = float(hit.iloc[0]["买报价"])
                ask = float(hit.iloc[0]["卖报价"])
                mid = round((bid + ask) / 2, 4)
                bag.add(
                    "macro",
                    "在岸人民币",
                    "最新中间价近似",
                    mid,
                    unit="USD/CNY",
                    note="实时买卖价中值，非周序列【弱】",
                    status="degraded",
                )
            else:
                bag.missing("macro", "在岸人民币", "周收", "未找到 USD/CNY")
        else:
            bag.missing("macro", "在岸人民币", "周收", "外汇接口失败")


# ---------------------------------------------------------------------------
# 7) 供给 → 「供给&政策 / ⑦市场供给」
# ---------------------------------------------------------------------------

def collect_supply(bag: RowBag, week_days: list[date]) -> None:
    import akshare as ak

    _say("\n=== 7) 供给（IPO / 解禁）===")
    start, end = week_days[0], week_days[-1]

    sleep_bit()
    ipo = safe_call("stock_xgsr_ths", ak.stock_xgsr_ths)
    if isinstance(ipo, pd.DataFrame) and not ipo.empty:
        df = ipo.copy()
        df["_d"] = df["上市日期"].map(_to_date)
        sub = df.loc[(df["_d"] >= start) & (df["_d"] <= end)]
        bag.add("supply", "IPO", "本周上市家数", int(len(sub)), unit="家", note="同花顺新股上市首日")
        if not sub.empty:
            names = ",".join(sub["股票简称"].astype(str).tolist()[:20])
            bag.add("supply", "IPO", "本周上市名单", names, note="最多列20只")
    else:
        bag.missing("supply", "IPO", "本周上市家数", "stock_xgsr_ths 失败", unit="家")

    sleep_bit()
    rest = safe_call("stock_restricted_release_summary_em", ak.stock_restricted_release_summary_em)
    if isinstance(rest, pd.DataFrame) and not rest.empty:
        df = rest.copy()
        df["_d"] = df["解禁时间"].map(_to_date)
        sub = df.loc[(df["_d"] >= start) & (df["_d"] <= end)]
        if sub.empty:
            bag.missing("supply", "解禁", "本周解禁市值", "周内无解禁汇总行", unit="亿元")
        else:
            # 实际解禁市值多为元
            mv = pd.to_numeric(sub["实际解禁市值"], errors="coerce").fillna(0).sum()
            qty = pd.to_numeric(sub["实际解禁数量"], errors="coerce").fillna(0).sum()
            houses = int(pd.to_numeric(sub["当日解禁股票家数"], errors="coerce").fillna(0).sum())
            bag.add("supply", "解禁", "本周解禁家数合计", houses, unit="家", note="东财解禁汇总")
            bag.add(
                "supply",
                "解禁",
                "本周实际解禁数量",
                round(qty / 1e8, 4),
                unit="亿股",
                note="周内求和",
            )
            bag.add(
                "supply",
                "解禁",
                "本周实际解禁市值",
                round(mv / 1e8, 4),
                unit="亿元",
                note="周内求和",
            )
    else:
        bag.missing("supply", "解禁", "本周解禁市值", "解禁汇总接口失败", unit="亿元")


# ---------------------------------------------------------------------------
# 提示词文本块
# ---------------------------------------------------------------------------

def build_prompt_text(bag: RowBag) -> str:
    df = bag.to_df()
    ws, we = bag.week_start, bag.week_end

    def lines(module: str) -> list[str]:
        sub = df[df["module"] == module]
        if sub.empty:
            return ["- 数据不足"]
        out: list[str] = []
        for _, r in sub.iterrows():
            val = r["value"] if str(r["status"]) == "ok" or str(r["value"]) != "" else "数据不足"
            if val == "" or (str(r["status"]) == "missing" and val == "数据不足"):
                val = "数据不足"
            bit = f"- {r['item']}"
            if r["code"]:
                bit += f"({r['code']})"
            bit += f" | {r['metric']}: {val}"
            if r["unit"]:
                bit += f" {r['unit']}"
            if r["note"]:
                bit += f" （{r['note']}）"
            if r["status"] not in ("ok",):
                bit += f" [{r['status']}]"
            out.append(bit)
        return out

    parts = [
        f"本周周期：{ws.strftime('%Y.%m.%d')}-{we.strftime('%Y.%m.%d')}",
        "",
        "指数数据：",
        *lines("index"),
        "",
        "市场宽度：",
        *lines("breadth"),
        "",
        "行业板块：",
        *lines("industry"),
        "",
        "资金数据：",
        *lines("capital"),
        "",
        "情绪数据：",
        *lines("emotion"),
        "",
        "宏观&外围：",
        *lines("macro"),
        "",
        "供给&政策：",
        *lines("supply"),
        "- 政策要闻：数据不足",
        "",
        "我的额外关注点：",
        "- 无",
        "",
        "（粘贴说明：将本文件全文作为周复盘 User 提示词中的数据区；缺数勿编造。）",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 库入口：按 ISO week_key / 指定交易周采集
# ---------------------------------------------------------------------------

def resolve_trade_week_for_iso_key(
    week_key: str,
    *,
    trade_dates: Optional[list[date]] = None,
    today: Optional[date] = None,
) -> tuple[date, date, list[date]]:
    """
    week_key 如 2026-W46 → 该 ISO 周周一~周五内的实际交易日。
    若交易日历不可用，退化为该周工作日（周一至周五，截断到 today）。
    """
    year_s, week_s = week_key.split("-W")
    year, week = int(year_s), int(week_s)
    jan4 = date(year, 1, 4)
    monday = jan4 - timedelta(days=jan4.weekday()) + timedelta(weeks=week - 1)
    friday = monday + timedelta(days=4)
    today = today or _now().date()
    end_cap = min(friday, today)

    dates = trade_dates
    if dates is None:
        dates = safe_call("calendar_trade_date_hist_sina", load_trade_dates, default=[]) or []

    if dates:
        week_days = [d for d in dates if monday <= d <= end_cap]
        if week_days:
            return monday, friday, week_days

    # 无日历：用自然工作日兜底
    week_days = [monday + timedelta(days=i) for i in range(5) if monday + timedelta(days=i) <= today]
    if not week_days:
        week_days = [monday]
    return monday, friday, week_days


def collect_week_bundle(
    monday: date,
    friday: date,
    week_days: list[date],
    *,
    full_industry: bool = False,
    verbose: bool = False,
    week_key: str = "",
) -> dict[str, Any]:
    """按模块采集一周数据，返回后台可入库的 stats 结构。"""
    global _VERBOSE
    prev = _VERBOSE
    _VERBOSE = verbose
    try:
        bag = RowBag(monday, friday)
        bag.add("meta", "交易周", "week_start", monday.isoformat(), note="自然周周一")
        bag.add("meta", "交易周", "week_end", friday.isoformat(), note="自然周周五")
        bag.add(
            "meta",
            "交易周",
            "trade_days",
            ",".join(d.isoformat() for d in week_days),
            note="实际交易日列表",
        )
        try:
            collect_indices(bag, week_days)
            collect_breadth(bag, week_days)
            collect_industry(bag, week_days, full_industry=full_industry)
            collect_capital(bag, week_days)
            collect_emotion(bag, week_days)
            collect_macro(bag, week_days)
            collect_supply(bag, week_days)
        except Exception as exc:  # noqa: BLE001
            log.exception("周度采集过程异常: %s", exc)
            if verbose:
                print(f"[ERROR] 采集过程异常: {exc}")
                traceback.print_exc()

        prompt = build_prompt_text(bag)
        ok_n = sum(1 for r in bag.rows if r.get("status") == "ok")
        miss_n = sum(1 for r in bag.rows if r.get("status") == "missing")
        deg_n = sum(1 for r in bag.rows if r.get("status") == "degraded")
        index_ok = any(
            r.get("module") == "index" and r.get("status") == "ok" and r.get("metric") == "周涨跌幅"
            for r in bag.rows
        )
        data_source = "akshare" if index_ok or ok_n > 0 else "akshare_partial"
        note = (
            f"全模块周度采集（腾讯/新浪指数优先；行业默认同花顺快照）；"
            f"ok={ok_n} degraded={deg_n} missing={miss_n}"
        )
        # 兼容旧前端/报告：从 index 行折叠出 indices 摘要
        indices: dict[str, Any] = {}
        for r in bag.rows:
            if r.get("module") != "index" or not r.get("code"):
                continue
            code = str(r["code"])
            slot = indices.setdefault(
                code,
                {"name": r.get("name") or r.get("item") or code, "bars": None},
            )
            metric, val = str(r.get("metric") or ""), r.get("value")
            if metric == "周开盘" and val != "":
                slot["open"] = float(val)
            elif metric == "周收盘" and val != "":
                slot["close"] = float(val)
            elif metric == "周涨跌幅" and val != "":
                slot["pct_chg"] = float(val)
            elif metric == "周振幅" and val != "":
                slot["amplitude"] = float(val)
            elif metric == "周成交额" and val != "":
                slot["amount_yi"] = float(val)
            elif metric == "周换手率" and val != "":
                slot["turnover"] = float(val)
            elif metric == "交易日数" and val != "":
                slot["bars"] = int(float(val))
            if r.get("status") and r["status"] != "ok":
                slot.setdefault("status", r["status"])

        return {
            "week_key": week_key,
            "week_start": monday.isoformat(),
            "week_end": friday.isoformat(),
            "trade_days": [d.isoformat() for d in week_days],
            "indices": indices,
            "rows": bag.rows,
            "prompt_text": prompt,
            "data_source": data_source,
            "note": note,
            "counts": {"ok": ok_n, "degraded": deg_n, "missing": miss_n},
        }
    finally:
        _VERBOSE = prev


def collect_for_week_key(
    week_key: str,
    *,
    full_industry: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """后台入口：按 ISO week_key 采集整周复盘数据。"""
    try:
        import akshare as ak  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("akshare 未安装：pip install '.[market]' pandas") from exc

    monday, friday, week_days = resolve_trade_week_for_iso_key(week_key)
    log.info("采集交易周 %s: %s ~ %s days=%s", week_key, monday, friday, week_days)
    return collect_week_bundle(
        monday,
        friday,
        week_days,
        full_industry=full_industry,
        verbose=verbose,
        week_key=week_key,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股周度复盘数据采集（akshare）")
    parser.add_argument(
        "--out-dir",
        type=str,
        default="",
        help="CSV/提示词输出目录",
    )
    parser.add_argument(
        "--full-industry",
        action="store_true",
        help="对东财全部行业做日K周聚合（慢，易限流）；默认用同花顺快照降级",
    )
    parser.add_argument(
        "--week-key",
        type=str,
        default="",
        help="指定 ISO 周，如 2026-W46；默认取最近一个完整交易周",
    )
    args = parser.parse_args(argv)

    print("=" * 60)
    print("A股周度复盘数据采集")
    print("=" * 60)

    try:
        import akshare as ak  # noqa: F401
    except ImportError:
        print("[ERROR] 未安装 akshare。请执行: pip install akshare pandas")
        return 1

    trade_dates = safe_call("calendar_trade_date_hist_sina", load_trade_dates, default=[])
    if not trade_dates:
        print("[ERROR] 无法获取交易日历")
        return 2

    try:
        if args.week_key:
            monday, friday, week_days = resolve_trade_week_for_iso_key(
                args.week_key, trade_dates=trade_dates
            )
        else:
            monday, friday, week_days = resolve_last_complete_week(trade_dates)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 识别交易周失败: {exc}")
        return 3

    print(f"完整交易周: {monday} ~ {friday}")
    print(f"周内交易日: {', '.join(d.isoformat() for d in week_days)}")

    bundle = collect_week_bundle(
        monday,
        friday,
        week_days,
        full_industry=bool(args.full_industry),
        verbose=True,
        week_key=args.week_key or "",
    )

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parents[2] / "scripts" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{monday.strftime('%Y%m%d')}_{friday.strftime('%Y%m%d')}"
    csv_path = out_dir / f"weekly_review_{tag}.csv"
    txt_path = out_dir / f"weekly_review_{tag}_prompt.txt"

    pd.DataFrame(bundle["rows"], columns=RowBag.COLS).to_csv(
        csv_path, index=False, encoding="utf-8-sig"
    )
    txt_path.write_text(str(bundle["prompt_text"]), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"已写出 CSV : {csv_path}")
    print(f"已写出提示词数据块: {txt_path}")
    print(
        "配套用法: 打开 *_prompt.txt，整段粘贴进周复盘提示词的数据区"
        "（本周周期/指数/宽度/行业/资金/情绪/宏观/供给），即可生成报告。"
    )
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
