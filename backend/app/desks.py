from __future__ import annotations

from typing import Any

from .ledger import DEFAULT_DESK_ID

VALID_RULES_PROFILES = frozenset({"strategist", "kurumi", "mayari"})


def _normalize_rules_profile(raw: Any) -> str:
    profile = str(raw or "strategist").strip().lower()
    if profile in ("fukuga", "久留美"):
        return "kurumi"
    if profile in ("mary", "芽亚里"):
        return "mayari"
    if profile in VALID_RULES_PROFILES:
        return profile
    return "strategist"


def list_desk_configs(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """从 config 解析策略台列表；无 desks 时回退为单一 DeepSeek 台。"""
    strat = cfg.get("strategy") or {}
    ark = cfg.get("ark") or {}
    raw = strat.get("desks")
    if isinstance(raw, list) and raw:
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            desk_id = str(item.get("id") or "").strip()
            if not desk_id:
                continue
            out.append(
                {
                    "id": desk_id,
                    "name": str(item.get("name") or desk_id),
                    "model": str(item.get("model") or ark.get("model") or ""),
                    "base_url": str(item.get("base_url") or ark.get("base_url") or ""),
                    "timeout_sec": float(
                        item.get("timeout_sec", ark.get("timeout_sec", 90))
                    ),
                    "rules_profile": _normalize_rules_profile(item.get("rules_profile")),
                }
            )
        if out:
            return out
    return [
        {
            "id": DEFAULT_DESK_ID,
            "name": "DeepSeek Flash",
            "model": str(ark.get("model") or ""),
            "base_url": str(ark.get("base_url") or ""),
            "timeout_sec": float(ark.get("timeout_sec", 90)),
            "rules_profile": "strategist",
        }
    ]


def desk_ids(cfg: dict[str, Any]) -> list[str]:
    return [d["id"] for d in list_desk_configs(cfg)]


def get_desk(cfg: dict[str, Any], desk_id: str) -> dict[str, Any]:
    for d in list_desk_configs(cfg):
        if d["id"] == desk_id:
            return d
    raise KeyError(desk_id)


def resolve_desk_id(cfg: dict[str, Any], desk_id: str | None) -> str:
    ids = desk_ids(cfg)
    if not ids:
        return DEFAULT_DESK_ID
    if desk_id and desk_id in ids:
        return desk_id
    if desk_id is None or desk_id == "":
        return ids[0]
    raise KeyError(desk_id)
