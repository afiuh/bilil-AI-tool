"""
B站内容发现工具 — SQLite 存储层

三张表：
  candidates      → 候选视频池
  taste_profile   → 口味画像
  recommend_history → 推荐历史
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from bili_tool.config import get_config


class Database:
    """本地 SQLite 数据库封装。"""

    def __init__(self) -> None:
        cfg = get_config()
        self._conn = sqlite3.connect(str(cfg.db_path))  # [IO][DB]
        self._conn.row_factory = sqlite3.Row
        self._create_tables()  # [DB]

    # ── 建表 ──────────────────────────────

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                bvid           TEXT PRIMARY KEY,
                title          TEXT NOT NULL,
                up_name        TEXT NOT NULL,
                up_mid         INTEGER NOT NULL,
                duration_sec   INTEGER NOT NULL,
                play_count     INTEGER DEFAULT 0,
                pub_date       TEXT,
                cover_url      TEXT,
                partition      TEXT,
                subtitle_text  TEXT,
                score_l1       REAL,
                score_l2       REAL,
                score_l3       REAL,
                status         TEXT DEFAULT 'pending',
                created_at     TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS taste_profile (
                id             INTEGER PRIMARY KEY CHECK(id=1),
                profile_json   TEXT NOT NULL,
                updated_at     TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS recommend_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                bvid           TEXT NOT NULL,
                note_path      TEXT,
                recommended_at TEXT DEFAULT (datetime('now','localtime')),
                feedback_at    TEXT,
                feedback_text  TEXT
            );
            """
        )
        self._conn.commit()

    # ── 候选池 ────────────────────────────

    def add_candidate(self, **kwargs: Any) -> None:
        """添加单条候选。"""
        keys = list(kwargs.keys())
        placeholders = ", ".join([f":{k}" for k in keys])
        columns = ", ".join(keys)
        # [IO][DB]
        self._conn.execute(
            f"INSERT OR IGNORE INTO candidates ({columns}) VALUES ({placeholders})",
            kwargs,
        )

    def add_candidates(self, items: list[dict[str, Any]]) -> int:
        """批量添加候选，返回实际插入数。"""
        if not items:
            return 0
        keys = list(items[0].keys())
        placeholders = ", ".join([f":{k}" for k in keys])
        columns = ", ".join(keys)
        before = self._conn.total_changes
        # [IO][DB]
        self._conn.executemany(
            f"INSERT OR IGNORE INTO candidates ({columns}) VALUES ({placeholders})",
            items,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def get_pending(self, limit: int = 200) -> list[dict[str, Any]]:
        """获取待打分的候选。"""
        rows = self._conn.execute(
            "SELECT * FROM candidates WHERE status='pending' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_score(
        self, bvid: str, *, l1: float | None = None, l2: float | None = None, l3: float | None = None
    ) -> None:
        """更新候选打分。"""
        sets = []
        vals: list[Any] = []
        if l1 is not None:
            sets.append("score_l1=?")
            vals.append(l1)
        if l2 is not None:
            sets.append("score_l2=?")
            vals.append(l2)
        if l3 is not None:
            sets.append("score_l3=?")
            vals.append(l3)
        if not sets:
            return
        vals.append(bvid)
        self._conn.execute(
            f"UPDATE candidates SET {', '.join(sets)} WHERE bvid=?", vals
        )
        self._conn.commit()

    def mark_status(self, bvid: str, status: str) -> None:
        """更新候选状态：pending / scored / discarded / recommended。"""
        self._conn.execute(
            "UPDATE candidates SET status=? WHERE bvid=?", (status, bvid)
        )
        self._conn.commit()

    def get_top_scored(
        self, limit: int = 10, min_score: float = 0.5
    ) -> list[dict[str, Any]]:
        """获取打分最高的候选。"""
        rows = self._conn.execute(
            "SELECT * FROM candidates WHERE score_l3>=? "
            "ORDER BY score_l3 DESC LIMIT ?",
            (min_score, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 口味画像 ────────────────────────────

    def save_taste(self, profile: dict[str, Any]) -> None:
        """保存口味画像。"""
        self._conn.execute(
            "INSERT OR REPLACE INTO taste_profile (id, profile_json) VALUES (1, ?)",
            (json.dumps(profile, ensure_ascii=False),),
        )
        self._conn.commit()

    def load_taste(self) -> dict[str, Any] | None:
        """加载口味画像。"""
        row = self._conn.execute(
            "SELECT profile_json FROM taste_profile WHERE id=1"
        ).fetchone()
        return json.loads(row["profile_json"]) if row else None

    # ── 推荐历史 ────────────────────────────

    def mark_recommended(self, bvid: str, note_path: str = "") -> None:
        """记录已推荐。"""
        self._conn.execute(
            "INSERT INTO recommend_history (bvid, note_path) VALUES (?, ?)",
            (bvid, note_path),
        )
        self._conn.commit()

    def get_recent_bvids(self, days: int = 30) -> set[str]:
        """获取近期已推荐的 bvid（去重用）。"""
        rows = self._conn.execute(
            "SELECT bvid FROM recommend_history "
            "WHERE recommended_at >= datetime('now','localtime',?)",
            (f"-{days} days",),
        ).fetchall()
        return {r["bvid"] for r in rows}

    def get_feedback_records(self, after_date: str = "") -> list[dict[str, Any]]:
        """获取有反馈的记录。"""
        query = "SELECT * FROM recommend_history WHERE feedback_text IS NOT NULL AND feedback_text != ''"
        params: tuple = ()
        if after_date:
            query += " AND feedback_at >= ?"
            params = (after_date,)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def save_feedback(self, bvid: str, text: str) -> None:
        """保存用户反馈。"""
        self._conn.execute(
            "UPDATE recommend_history SET feedback_text=?, feedback_at=datetime('now','localtime') "
            "WHERE bvid=? AND feedback_text IS NULL",
            (text, bvid),
        )
        self._conn.commit()

    # ── 清理 ────────────────────────────────

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
