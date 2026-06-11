"""管道检查点。关键位置插入，AI可介入查看数据。"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def check_discovery(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """检查点①：发现后 — 话题分布。"""
    total = len(candidates)
    if total == 0:
        return {"ok": False, "stage": "发现后", "warning": "无候选视频",
                "summary": "发现阶段返回0条", "details": {}}

    from collections import Counter
    partitions = Counter(c.get("partition", "未知") for c in candidates)
    titles = [c.get("title", "") for c in candidates]

    # 话题关键词检测
    topic_hits = {"历史": 0, "哲学": 0, "影视": 0, "社会": 0, "其他": 0}
    topic_kw = {
        "历史": ["历史", "朝代", "战争", "帝国", "古代", "三国", "明朝", "唐朝"],
        "哲学": ["哲学", "思辨", "辩证", "认知", "唯物", "方法论", "毛选"],
        "影视": ["解读", "影评", "剧评", "电影", "电视剧", "吐槽"],
        "社会": ["社会", "政治", "权力", "博弈", "阶层", "规则"],
    }
    for t in titles:
        matched = False
        for topic, kws in topic_kw.items():
            if any(kw in t for kw in kws):
                topic_hits[topic] += 1
                matched = True
                break
        if not matched:
            topic_hits["其他"] += 1

    # 判断是否偏斜
    max_topic = max(topic_hits, key=topic_hits.get)
    max_pct = topic_hits[max_topic] / total if total > 0 else 0
    ok = max_pct < 0.7

    # 候选标题采样（前10条）
    title_sample = [c.get("title", "")[:40] for c in candidates[:10]]

    return {
        "ok": ok,
        "stage": "发现后",
        "warning": f"话题偏斜：{max_topic}类占{max_pct:.0%}" if not ok else "",
        "summary": f"候选{total}条。{max_topic}类{max_pct:.0%}。分区分布：{dict(partitions.most_common(5))}",
        "details": {
            "total": total,
            "topic_dist": topic_hits,
            "partition_dist": dict(partitions.most_common(5)),
            "title_sample": title_sample,
            "max_topic": max_topic,
            "max_pct": f"{max_pct:.0%}",
        },
    }


def check_scoring(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """检查点②：打分后 — 分数分布 + 鸡汤指数。"""
    total = len(candidates)
    if total == 0:
        return {"ok": False, "stage": "打分后", "warning": "无幸存视频",
                "summary": "打分后全部淘汰", "details": {}}

    scores = [c.get("score_l3", 0) for c in candidates]
    soups = [c.get("soup_score", -1) for c in candidates]
    avg_score = sum(scores) / total
    soup_count = sum(1 for s in soups if s > 0.6)
    low_count = sum(1 for s in scores if s < 0.2)

    warnings = []
    if avg_score < 0.25:
        warnings.append(f"平均分偏低({avg_score:.2f})")
    if soup_count > total * 0.3:
        warnings.append(f"鸡汤率偏高({soup_count}/{total})")
    if low_count > total * 0.3:
        warnings.append(f"低分率偏高({low_count}/{total})")

    # 高分/低分/鸡汤视频标题采样
    top3 = sorted(candidates, key=lambda x: x.get("score_l3", 0), reverse=True)[:3]
    bottom3 = sorted(candidates, key=lambda x: x.get("score_l3", 0))[:3]
    soup_list = [f"{c.get('title','')[:30]}({c.get('soup_score',0):.1f})" for c in candidates if c.get('soup_score', 0) > 0.6]

    return {
        "ok": len(warnings) == 0,
        "stage": "打分后",
        "warning": "; ".join(warnings) if warnings else "",
        "summary": (
            f"幸存{total}条。均分{avg_score:.2f}。"
            f"鸡汤{soup_count}条，低分{low_count}条。"
        ),
        "details": {
            "total": total,
            "avg_score": round(avg_score, 3),
            "max_score": round(max(scores), 3),
            "min_score": round(min(scores), 3),
            "soup_count": soup_count,
            "low_count": low_count,
            "top3": [f"{c.get('title','')[:35]}({c.get('score_l3',0):.2f})" for c in top3],
            "bottom3": [f"{c.get('title','')[:35]}({c.get('score_l3',0):.2f})" for c in bottom3],
            "soup_list": soup_list[:5],
        },
    }


def check_output(note_path: str) -> dict[str, Any]:
    """检查点③：笔记输出后 — 最终质量。"""
    from pathlib import Path
    p = Path(note_path)
    if not p.exists():
        return {"ok": False, "stage": "笔记后", "warning": "笔记文件不存在",
                "summary": f"路径：{note_path}", "details": {}}

    content = p.read_text(encoding="utf-8")
    import re

    # 统计
    video_count = content.count("### 📋 基本信息")
    truncated = len(re.findall(r"截断|truncat", content, re.IGNORECASE))
    placeholder = content.count("⏳ 待分析")
    total_size = len(content)

    warnings = []
    if placeholder > 0:
        warnings.append(f"{placeholder}条视频未精校")
    if truncated > 0:
        warnings.append(f"检测到{truncated}处截断")

    return {
        "ok": len(warnings) == 0,
        "stage": "笔记后",
        "warning": "; ".join(warnings) if warnings else "",
        "summary": (
            f"笔记 {p.name}：{total_size}字，{video_count}条视频。"
            f"精校完成{video_count - placeholder}/{video_count}。"
        ),
        "details": {
            "path": str(p), "size": total_size, "video_count": video_count,
            "placeholder_count": placeholder, "truncated": truncated,
        },
    }


def check_pool_merge(results: dict, taste=None) -> dict:
    """检查点②(5池模式)：各池合并后 — 总量+分布。"""
    total = sum(len(v) for v in results.values())
    if total == 0:
        return {"ok": False, "stage": "池合并后", "warning": "5池全部空产",
                "summary": "0条候选", "details": {}}

    # 分区分布
    from collections import Counter
    partitions = Counter()
    for pool_results in results.values():
        for c in pool_results:
            partitions[c.get("partition", "未知")] += 1

    # 话题偏斜检查
    top_topic = partitions.most_common(1)[0] if partitions else ("未知", 0)
    max_pct = top_topic[1] / total if total > 0 else 0

    from bili_tool.config import get_config
    cfg = get_config()
    ok = max_pct < cfg.topic_diversity_warn

    return {
        "ok": ok,
        "stage": "池合并后",
        "warning": f"话题偏斜：{top_topic[0]}占{max_pct:.0%}" if not ok else "",
        "summary": f"5池合并{total}条。{dict(partitions.most_common(5))}",
        "details": {
            "total": total,
            "pool_counts": {k: len(v) for k, v in results.items()},
            "partition_dist": dict(partitions.most_common(5)),
        },
    }
