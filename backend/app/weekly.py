from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .db import Database
from .llm_ark import ArkError, generate_weekly_report

log = logging.getLogger("daa.weekly")
CN = ZoneInfo("Asia/Shanghai")


def _iso_week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_bounds(week_key: str) -> tuple[date, date]:
    """week_key like 2026-W03 → Mon..Sun."""
    year_s, week_s = week_key.split("-W")
    year, week = int(year_s), int(week_s)
    # ISO: week 1 Monday
    jan4 = date(year, 1, 4)
    start = jan4 - timedelta(days=jan4.weekday()) + timedelta(weeks=week - 1)
    end = start + timedelta(days=6)
    return start, end


def list_weeks(year: int, today: Optional[date] = None) -> list[dict[str, Any]]:
    today = today or datetime.now(CN).date()
    if today.year < year:
        return []
    end_cap = today if today.year == year else date(year, 12, 31)
    # first Monday of ISO week that touches Jan 1 of year, or first week of year
    cursor = date(year, 1, 1)
    # move to Monday of that ISO week
    cursor = cursor - timedelta(days=cursor.weekday())
    weeks: list[dict[str, Any]] = []
    seen: set[str] = set()
    while cursor <= end_cap:
        key = _iso_week_key(cursor)
        if key.startswith(f"{year}-") and key not in seen:
            start, end = week_bounds(key)
            if start.year == year or end.year == year or start <= end_cap:
                if start <= end_cap:
                    weeks.append(
                        {
                            "week_key": key,
                            "week_start": start.isoformat(),
                            "week_end": min(end, end_cap).isoformat() if end > end_cap else end.isoformat(),
                        }
                    )
                    seen.add(key)
        cursor += timedelta(days=7)
    weeks.sort(key=lambda w: w["week_key"], reverse=True)
    return weeks


def _mock_week_stats(indices: list[dict[str, str]], start: date, end: date) -> dict[str, Any]:
    rng = random.Random(f"{start.toordinal()}")
    bases = {
        "000001": 3600.0,
        "399001": 11000.0,
        "000300": 3900.0,
        "399006": 2100.0,
        "000688": 980.0,
        "000905": 6500.0,
        "399317": 6000.0,
    }
    out: dict[str, Any] = {}
    for idx in indices:
        sym = idx["symbol"]
        base = bases.get(sym, 1000.0) * (1 + rng.uniform(-0.08, 0.08))
        pct = round(rng.uniform(-3.5, 3.5), 2)
        close = round(base * (1 + pct / 100), 2)
        high = round(max(base, close) * (1 + rng.uniform(0, 0.015)), 2)
        low = round(min(base, close) * (1 - rng.uniform(0, 0.015)), 2)
        out[sym] = {
            "name": idx["name"],
            "open": round(base, 2),
            "high": high,
            "low": low,
            "close": close,
            "pct_chg": pct,
            "amplitude": round((high - low) / base * 100, 2) if base else 0.0,
            "bars": 5,
        }
    friday = start + timedelta(days=4)
    return {
        "week_start": start.isoformat(),
        "week_end": min(friday, end).isoformat(),
        "indices": out,
        "rows": [],
        "prompt_text": "",
        "data_source": "mock",
        "note": "synthetic：未使用 AKShare 或拉取失败时的演示序列",
    }


def build_week_stats(indices: list[dict[str, str]], week_key: str, *, full_industry: bool = False) -> dict[str, Any]:
    """
    优先走 scripts 同口径全模块采集（指数/宽度/行业/资金/情绪/宏观/供给）；
    akshare 不可用或采集抛错时回退 mock 指数。
    """
    start, end = week_bounds(week_key)
    today = datetime.now(CN).date()
    if end > today:
        end = today

    try:
        from .weekly_collect import collect_for_week_key

        stats = collect_for_week_key(week_key, full_industry=full_industry, verbose=False)
        if stats.get("indices") or (stats.get("counts") or {}).get("ok", 0) > 0:
            stats["week_key"] = week_key
            return stats
        log.warning("周度全模块采集无有效指标，回退 mock：%s", week_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("周度全模块采集失败，回退 mock：%s (%s)", week_key, exc)

    stats = _mock_week_stats(indices, start, end)
    stats["week_key"] = week_key
    return stats


def stats_to_prompt_text(stats: dict[str, Any]) -> str:
    """优先使用采集模块生成的 prompt；否则拼装最小指数模板。"""
    prompt = str(stats.get("prompt_text") or "").strip()
    if prompt:
        meta = (
            f"（元数据）week_key={stats.get('week_key')} "
            f"data_source={stats.get('data_source')} note={stats.get('note', '')}"
        )
        # 插在周期行后，便于排查数据源
        lines = prompt.splitlines()
        if lines and lines[0].startswith("本周周期："):
            return "\n".join([lines[0], meta, *lines[1:]])
        return meta + "\n" + prompt

    start = str(stats.get("week_start", "")).replace("-", ".")
    end = str(stats.get("week_end", "")).replace("-", ".")
    lines = [
        f"本周周期：{start}-{end}",
        f"（元数据）week_key={stats.get('week_key')} data_source={stats.get('data_source')} note={stats.get('note', '')}",
        "",
        "指数数据：",
    ]
    indices = stats.get("indices") or {}
    if indices:
        for sym, row in indices.items():
            lines.append(
                f"- {row.get('name', sym)}({sym}): "
                f"开={row.get('open', '数据不足')} 高={row.get('high', '数据不足')} "
                f"低={row.get('low', '数据不足')} 收={row.get('close', '数据不足')} "
                f"周涨跌={row.get('pct_chg', '数据不足')}% 振幅={row.get('amplitude', '数据不足')}% "
                f"交易日数={row.get('bars', '?')}"
            )
        lines.append("- 周成交额：数据不足")
        lines.append("- 换手率：数据不足")
        lines.append("- 估值（PE/PB分位）：数据不足")
    else:
        lines.append("- 数据不足")

    lines.extend(
        [
            "",
            "市场宽度：",
            "- 涨跌家数：数据不足",
            "- 涨跌幅中位数：数据不足",
            "- 新高/新低数量：数据不足",
            "- 上周对照：无上周对照数据",
            "",
            "行业板块：",
            "- 申万一级行业周表现：数据不足",
            "- 概念板块周表现：数据不足",
            "- 上周对照、拥挤相关指标：数据不足",
            "",
            "资金数据：",
            "- 北向资金周净买入：数据不足",
            "- 两融余额变动：数据不足",
            "- ETF周净申赎：数据不足",
            "- 龙虎榜（机构/游资）：数据不足",
            "",
            "情绪数据：",
            "- 涨停/跌停家数：数据不足",
            "- 炸板率：数据不足",
            "- 连板高度：数据不足",
            "",
            "宏观&外围：",
            "- 人民币汇率：数据不足",
            "- 美债收益率：数据不足",
            "- 流动性指标：数据不足",
            "- 外围主要指数周表现：数据不足",
            "",
            "供给&政策：",
            "- IPO：数据不足",
            "- 解禁：数据不足",
            "- 减持：数据不足",
            "- 政策要闻：数据不足",
            "",
            "我的额外关注点：",
            "- 无",
        ]
    )
    return "\n".join(lines)


def get_report(db: Database, week_key: str) -> Optional[dict[str, Any]]:
    row = db.fetchone("SELECT * FROM weekly_reports WHERE week_key = ?", (week_key,))
    if row is None:
        return None
    return {
        "week_key": row["week_key"],
        "week_start": row["week_start"],
        "week_end": row["week_end"],
        "stats": json.loads(row["stats_json"]),
        "content_md": row["content_md"],
        "model": row["model"],
        "data_source": row["data_source"],
        "created_at": row["created_at"],
    }


def save_report(
    db: Database,
    *,
    week_key: str,
    week_start: str,
    week_end: str,
    stats: dict[str, Any],
    content_md: str,
    model: str,
    data_source: str,
) -> dict[str, Any]:
    ts = datetime.now(CN).isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO weekly_reports
          (week_key, week_start, week_end, stats_json, content_md, model, data_source, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(week_key) DO UPDATE SET
          week_start=excluded.week_start,
          week_end=excluded.week_end,
          stats_json=excluded.stats_json,
          content_md=excluded.content_md,
          model=excluded.model,
          data_source=excluded.data_source,
          created_at=excluded.created_at
        """,
        (week_key, week_start, week_end, json.dumps(stats, ensure_ascii=False), content_md, model, data_source, ts),
    )
    db.commit()
    return get_report(db, week_key)  # type: ignore[return-value]


def existing_week_keys(db: Database) -> set[str]:
    return {r["week_key"] for r in db.fetchall("SELECT week_key FROM weekly_reports")}


def generate_or_get(
    db: Database,
    cfg: dict[str, Any],
    week_key: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    year = int(cfg.get("weekly", {}).get("year", 2026))
    valid = {w["week_key"] for w in list_weeks(year)}
    if week_key not in valid:
        raise ValueError(f"week_key 不在 {year} 可生成范围：{week_key}")

    if not force:
        cached = get_report(db, week_key)
        if cached is not None:
            return cached

    indices = list(cfg.get("weekly_indices") or cfg.get("indices") or [])
    full_industry = bool(cfg.get("weekly", {}).get("full_industry", False))
    stats = build_week_stats(indices, week_key, full_industry=full_industry)
    ark = cfg.get("ark", {})
    try:
        content = generate_weekly_report(
            base_url=str(ark.get("base_url", "https://ark.cn-beijing.volces.com/api/plan/v3")),
            model=str(ark.get("model", "deepseek-v4-1-flash-261017")),
            timeout_sec=float(ark.get("timeout_sec", 90)),
            week_label=f"{week_key}（{stats['week_start']}~{stats['week_end']}）",
            stats_text=stats_to_prompt_text(stats),
            data_source=str(stats.get("data_source", "mock")),
        )
    except ArkError:
        raise

    return save_report(
        db,
        week_key=week_key,
        week_start=stats["week_start"],
        week_end=stats["week_end"],
        stats=stats,
        content_md=content,
        model=str(ark.get("model", "deepseek-v4-1-flash-261017")),
        data_source=str(stats.get("data_source", "mock")),
    )
