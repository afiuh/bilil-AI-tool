"""
B站内容发现工具 — 策展模块

去重、排序、截断 Top N。
"""

from __future__ import annotations

import logging
from typing import Any

from bili_tool.storage import Database

logger = logging.getLogger(__name__)


def curate(
    candidates: list[dict[str, Any]],
    db: Database,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """策展：去重 → 排序 → 截断。"""

    # 去重 + 排除已推荐
    recent = db.get_recent_bvids(days=60)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in candidates:
        bvid = c.get("bvid", "")
        if bvid in seen or bvid in recent:
            continue
        seen.add(bvid)
        unique.append(c)

    # 按 L3 分排序
    unique.sort(key=lambda x: x.get("score_l3", 0), reverse=True)

    # 多样性约束：确保每个核心方向至少有 floor 条
    DIVERSITY_FLOOR = 1   # 每个方向最少条数
    topic_categories = {
        "历史": ["人文历史", "历史"],
        "哲学/社科": ["社科·法律·心理", "哲学"],
        "影视": ["影视杂谈", "电影", "电视剧"],
    }

    # 第一轮：从每个方向取 floor 条最高分的
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for topic, partitions in topic_categories.items():
        for c in unique:
            if c["bvid"] in used:
                continue
            partition = c.get("partition", "")
            title = c.get("title", "")
            # 匹配分区或标题关键词
            if any(p in partition for p in partitions) or any(kw in title for kw in partitions):
                result.append(c)
                used.add(c["bvid"])
                if len([r for r in result if any(
                    p in r.get("partition", "") for p in partitions
                )]) >= DIVERSITY_FLOOR:
                    break

    # 第二轮：剩余名额按 L3 分补满
    for c in unique:
        if len(result) >= limit:
            break
        if c["bvid"] not in used:
            result.append(c)
            used.add(c["bvid"])

    logger.info(f"策展: {len(candidates)} → {len(result)} (含多样性约束)")
    return result[:limit]


def deduplicate(
    candidates: list[dict[str, Any]],
    db,  # Database
    days: int = 60,
) -> list[dict[str, Any]]:
    """去重：排除已推荐和候选内重复。"""
    from bili_tool.storage import Database as DB
    recent = set()
    try:
        recent = set(db.get_recent_bvids(days=days))
    except Exception:
        pass
    seen: set[str] = set()
    result = []
    for c in candidates:
        bvid = c.get("bvid", "")
        if bvid in seen or bvid in recent:
            continue
        seen.add(bvid)
        result.append(c)
    return result


def rank(
    candidates: list[dict[str, Any]],
    sort_by: str = "score_l3",
) -> list[dict[str, Any]]:
    """按指定字段排序。"""
    return sorted(candidates, key=lambda x: x.get(sort_by, 0), reverse=True)


def enforce_diversity(
    candidates: list[dict[str, Any]],
    limit: int = 10,
    floor: int = 1,
) -> list[dict[str, Any]]:
    """多样性约束：每个核心方向至少floor条。"""
    topic_categories = {
        "历史": ["人文历史", "历史"],
        "哲学/社科": ["社科·法律·心理", "哲学"],
        "影视": ["影视杂谈", "电影", "电视剧"],
    }
    result = []
    used: set[str] = set()
    for topic, partitions in topic_categories.items():
        count = 0
        for c in candidates:
            if c["bvid"] in used:
                continue
            partition = c.get("partition", "")
            title = c.get("title", "")
            if any(p in partition for p in partitions) or any(
                kw in title for kw in partitions
            ):
                result.append(c)
                used.add(c["bvid"])
                count += 1
                if count >= floor:
                    break
    for c in candidates:
        if len(result) >= limit:
            break
        if c["bvid"] not in used:
            result.append(c)
            used.add(c["bvid"])
    return result[:limit]
