"""状态查询。纯读操作，不改数据。"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_candidate_count(db) -> int:
    """数据库中候选视频总数。"""
    try:
        cur = db._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM candidates")
        return cur.fetchone()[0]
    except Exception:
        return 0


def get_recommend_history(db, limit: int = 20) -> list[dict[str, Any]]:
    """最近推荐历史。"""
    try:
        cur = db._conn.cursor()
        cur.execute("""
            SELECT rh.bvid, rh.note_path, rh.recommended_at, c.title, c.up_name
            FROM recommend_history rh
            LEFT JOIN candidates c ON rh.bvid = c.bvid
            ORDER BY rh.id DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def get_unreviewed_notes(note_dir: Path) -> list[str]:
    """获取未全部已阅的笔记列表。"""
    from bili_tool.notes import count_reviewed
    unreviewed = []
    for note in sorted(note_dir.glob("推荐-*.md"), reverse=True):
        total, checked = count_reviewed(str(note))
        if total > 0 and checked < total:
            unreviewed.append(str(note))
    return unreviewed


def get_stats(db, note_dir: Path) -> dict[str, Any]:
    """综合统计信息。"""
    return {
        "candidates": get_candidate_count(db),
        "history": len(get_recommend_history(db, limit=1000)),
        "unreviewed": len(get_unreviewed_notes(note_dir)),
    }
