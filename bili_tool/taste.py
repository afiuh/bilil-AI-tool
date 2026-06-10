"""
B站内容发现工具 — 口味画像模块

从收藏夹+历史行为中提取用户口味向量。
支持：
  - 从收藏夹初始化画像
  - 根据反馈更新权重
  - 导出/导入 JSON
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class TasteProfile:
    """用户口味画像。"""

    def __init__(self) -> None:
        # 话题权重：话题名 → 权重 (0-1)
        self.topics: dict[str, float] = {}
        # UP主权重：mid → 权重
        self.up_weights: dict[int, float] = {}
        # UP主名称：mid → name
        self.up_names: dict[int, str] = {}
        # 风格偏好
        self.min_duration: int = 600      # 最短接受时长（秒）
        self.prefer_longform: float = 0.8 # 长视频偏好度
        self.depth_threshold: float = 0.7 # 深度要求阈值
        # 黑名单：mid → 永远不会推荐
        self.blacklist: set[int] = set()
        # 已关注 UP主列表（用于排除）
        self.followed_mids: set[int] = set()

    # ── 序列化 ────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "topics": self.topics,
            "up_weights": {str(k): v for k, v in self.up_weights.items()},
            "up_names": {str(k): v for k, v in self.up_names.items()},
            "min_duration": self.min_duration,
            "prefer_longform": self.prefer_longform,
            "depth_threshold": self.depth_threshold,
            "blacklist": list(self.blacklist),
            "followed_mids": list(self.followed_mids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TasteProfile":
        p = cls()
        p.topics = data.get("topics", {})
        p.up_weights = {int(k): v for k, v in data.get("up_weights", {}).items()}
        p.up_names = {int(k): v for k, v in data.get("up_names", {}).items()}
        p.min_duration = data.get("min_duration", 600)
        p.prefer_longform = data.get("prefer_longform", 0.8)
        p.depth_threshold = data.get("depth_threshold", 0.7)
        p.blacklist = set(data.get("blacklist", []))
        p.followed_mids = set(data.get("followed_mids", []))
        return p

    # ── 话题提取 ────────────────────────────

    @staticmethod
    def extract_topics_from_titles(titles: list[str]) -> dict[str, float]:
        """从一批视频标题中提取话题关键词和权重。"""
        keywords: Counter[str] = Counter()
        topic_map = {
            "历史": ["历史", "唐朝", "宋朝", "明朝", "三国", "清朝", "春秋", "战国", "古代", "朝代",
                     "安史之乱", "大闹天宫", "西游", "大唐", "大秦", "匈奴", "战争史"],
            "哲学": ["哲学", "思辨", "思维", "辩证", "认知", "底层逻辑", "本质", "规律", "原理",
                     "马克思主义", "唯物", "唯心", "方法论", "框架"],
            "社会": ["社会", "规则", "权力", "博弈", "人性", "阶层", "体制", "系统",
                     "毛选", "游击战", "兵法", "政治"],
            "影视": ["色戒", "潜伏", "三体", "新三国", "士兵突击", "纸牌屋", "火线",
                     "影评", "剧评", "解读", "电影", "电视剧"],
            "技术": ["编程", "开发", "代码", "CAD", "Python", "AI", "全栈", "前端", "后端"],
            "武术": ["咏春", "功夫", "格斗", "武术", "拳法", "套路"],
        }
        for title in titles:
            for topic, words in topic_map.items():
                for w in words:
                    if w in title:
                        keywords[topic] += 1
        if not keywords:
            return {}
        total = sum(keywords.values())
        return {k: min(v / total, 1.0) for k, v in keywords.items()}

    # ── 更新方法 ────────────────────────────

    def boost_up(self, mid: int, name: str = "", amount: float = 0.1) -> None:
        """奖励 UP主：加分。"""
        self.up_weights[mid] = min(1.0, self.up_weights.get(mid, 0.5) + amount)
        if name:
            self.up_names[mid] = name

    def penalize_up(self, mid: int, amount: float = 0.2) -> None:
        """惩罚 UP主：降分，降到阈值以下加入黑名单。"""
        current = self.up_weights.get(mid, 0.5)
        new = max(0.0, current - amount)
        if new < 0.2:
            self.blacklist.add(mid)
            self.up_weights.pop(mid, None)
        else:
            self.up_weights[mid] = new

    def boost_topic(self, topic: str, amount: float = 0.05) -> None:
        """奖励话题。"""
        self.topics[topic] = min(1.0, self.topics.get(topic, 0.5) + amount)

    def penalize_topic(self, topic: str, amount: float = 0.1) -> None:
        """惩罚话题。"""
        self.topics[topic] = max(0.0, self.topics.get(topic, 0.5) - amount)

    def increase_depth_threshold(self, amount: float = 0.05) -> None:
        """提高深度要求。"""
        self.depth_threshold = min(1.0, self.depth_threshold + amount)

    def is_blacklisted(self, mid: int) -> bool:
        return mid in self.blacklist
