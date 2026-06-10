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

    result = unique[:limit]
    logger.info(f"策展: {len(candidates)} → {len(result)}")
    return result
