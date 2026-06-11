"""
B站内容发现工具 — 发现引擎

四策略并行发现候选视频：
  1. UP主蔓延：从收藏 UP主 → 关注链 → 新视频
  2. 关联推荐：从收藏视频 → B站"相关推荐"
  3. 关键词搜索：从口味画像 → 关键词 → 搜索
  4. 分区探索：热门口味分区 → 热门+新晋

自动排除：已关注UP主、黑名单UP主、近期已推。
"""

from __future__ import annotations

import logging
from typing import Any

from bili_tool.bili_api import (
    get_followings,
    get_related_videos,
    get_upper_videos,
    search_videos,
)
from bili_tool.config import get_config
from bili_tool.taste import TasteProfile
from bili_tool.config import get_config

logger = logging.getLogger(__name__)


def discover(
    taste: TasteProfile,
    recent_bvids: set[str],
    seed_mids: list[int],
    seed_bvids: list[str],
) -> list[dict[str, Any]]:
    """主入口：运行所有发现策略，返回去重后的候选列表。"""

    cfg = get_config()
    all_candidates: list[dict[str, Any]] = []
    seen: set[str] = set(recent_bvids)  # 排除近期已推

    def add(items: list[dict[str, Any]], limit: int) -> int:
        added = 0
        for item in items:
            bvid = item.get("bvid", "")
            if bvid in seen:
                continue
            mid = item.get("up_mid", 0)
            if cfg.exclude_followed and mid in taste.followed_mids:
                continue
            if taste.is_blacklisted(mid):
                continue
            seen.add(bvid)
            all_candidates.append(item)
            added += 1
            if added >= limit:
                break
        return added

    # 策略 1：UP主蔓延
    logger.info("策略1: UP主蔓延")
    spread_mids = _spread_up_chain(taste, seed_mids, depth=1)
    for mid in spread_mids:
        videos = get_upper_videos(mid, page=1, page_size=10)
        add(videos, cfg.max_per_strategy)

    # 策略 2：关联推荐
    logger.info("策略2: 关联推荐")
    for bvid in seed_bvids[:10]:
        related = get_related_videos(bvid, limit=15)
        add(related, cfg.max_per_strategy)

    # 策略 3：关键词搜索
    logger.info("策略3: 关键词搜索")
    keywords = _gen_search_keywords(taste)
    for kw in keywords[:5]:
        results = search_videos(kw, page=1, page_size=20)
        add(results, cfg.max_per_strategy)

    # 策略 3b：探索池（冷门方向轮换，避免历史垄断）
    cfg = get_config()
    if cfg.explore_ratio > 0:
        explore_kw = getattr(cfg, 'explore_keywords', [])
        if explore_kw:
            import random
            sampled = random.sample(explore_kw, min(3, len(explore_kw)))
            for kw in sampled:
                try:
                    results = search_videos(kw, page=1, page_size=15)
                    add(results, cfg.max_per_strategy)
                except Exception:
                    continue

    # 策略 4：分区探索
    logger.info("策略4: 分区探索")
    partition_kw = _gen_partition_keywords(taste)
    for kw in partition_kw[:3]:
        results = search_videos(kw, page=1, page_size=15)
        add(results, cfg.max_per_strategy)

    logger.info(f"发现完成: {len(all_candidates)} 条候选")
    return all_candidates


def _spread_up_chain(
    taste: TasteProfile, seed_mids: list[int], depth: int = 1
) -> list[int]:
    """从种子 UP主蔓延到关注链，找新人。"""
    visited = set(taste.followed_mids) | set(taste.blacklist)
    new_mids: list[int] = []
    current = [m for m in seed_mids if m not in visited]

    for _ in range(depth):
        next_wave: list[int] = []
        for mid in current[:5]:
            try:
                followings = get_followings(mid, page=1)
            except Exception:
                continue
            for f in followings[:10]:
                fm = f["mid"]
                if fm not in visited:
                    visited.add(fm)
                    next_wave.append(fm)
                    new_mids.append(fm)
        current = next_wave
        if not current:
            break

    return new_mids


def _gen_search_keywords(taste: TasteProfile) -> list[str]:
    """基于口味画像生成搜索关键词。"""
    kw_map = {
        "历史": ["深度历史解读", "历史底层逻辑", "中国历史分析", "历史权谋"],
        "哲学": ["哲学思辨", "思维方法论", "深度哲学解读"],
        "社会": ["社会运行规律", "权力博弈分析", "底层逻辑分析"],
        "影视": ["深度影评解读", "电影拉片分析", "经典剧集深度解读"],
        "技术": ["编程开发教程", "技术深度解析"],
        "武术": ["武术教学", "功夫解析"],
    }
    keywords: list[str] = []
    sorted_topics = sorted(taste.topics.items(), key=lambda x: x[1], reverse=True)
    for topic, _ in sorted_topics:
        keywords.extend(kw_map.get(topic, []))
    return keywords[:8]


def _gen_partition_keywords(taste: TasteProfile) -> list[str]:
    """生成分区探索关键词。"""
    top_topics = sorted(taste.topics.items(), key=lambda x: x[1], reverse=True)[:3]
    return [t[0] for t in top_topics]


def discover_all(taste: TasteProfile) -> list[dict[str, Any]]:
    """四策略并行发现，去重合并。别名，等同于discover()。"""
    return discover(taste)


def discover_by_following(
    mids: list[int],
    depth: int = 3,
    max_results: int = 200,
) -> list[dict[str, Any]]:
    """从指定UP主关注链蔓延发现。"""
    from bili_tool.bili_api import get_following
    result = []
    visited: set[int] = set(mids)
    queue = list(mids)
    for _ in range(depth):
        if len(result) >= max_results or not queue:
            break
        mid = queue.pop(0)
        try:
            following = get_following(mid)
            for f in following[:20]:
                fid = f.get("mid", 0)
                if fid not in visited:
                    visited.add(fid)
                    queue.append(fid)
                    result.append({
                        "bvid": "",
                        "title": "",
                        "up_mid": fid,
                        "up_name": f.get("name", ""),
                        "source": "following_chain",
                    })
        except Exception:
            continue
    return result[:max_results]


def discover_by_search(
    keywords: list[str],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """按关键词搜索候选视频。"""
    from bili_tool.bili_api import search_videos
    result = []
    for kw in keywords[:5]:
        try:
            result.extend(search_videos(kw, limit=limit // len(keywords) + 1))
        except Exception:
            continue
    return result[:limit]


def discover_by_partition(
    partition_ids: list[int] | None = None,
    sort: str = "hot",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """扫分区热门视频。默认知识/人文历史分区。"""
    from bili_tool.bili_api import get_partition_videos
    if partition_ids is None:
        partition_ids = [36, 207]  # 知识, 人文历史
    result = []
    for pid in partition_ids:
        try:
            result.extend(get_partition_videos(pid, sort=sort, limit=limit // len(partition_ids) + 1))
        except Exception:
            continue
    return result[:limit]
