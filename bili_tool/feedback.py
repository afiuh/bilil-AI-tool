"""
B站内容发现工具 — 反馈解析模块 v2.0

扫描 Obsidian 笔记中的所有反馈区域：
  - 💬 你的看法（逐段批注反馈）
  - 📝 我的评论（单条视频评价）
  - 💬 总体反馈（整批推荐的评价）

分级处理：
  - auto（明确信号）→ 自动更新 taste
  - ask（模糊信号）→ 保存待确认问题，下次对话时提问
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def scan_feedback_notes(note_dir: Path, date_str: str) -> dict[str, Any]:
    """扫描指定日期的推荐笔记，提取所有反馈。

    返回: {
        "auto_actions": [...],   # 可直接执行的优化
        "pending_questions": [...] # 需要确认的问题
    }
    """
    note_path = note_dir / f"推荐-{date_str}.md"
    if not note_path.exists():
        logger.info(f"笔记不存在: {note_path}")
        return {"auto_actions": [], "pending_questions": []}

    content = note_path.read_text(encoding="utf-8")
    sections = re.split(r"\n## \d+\.", content)

    auto_actions: list[dict[str, Any]] = []
    pending_questions: list[dict[str, Any]] = []

    for sec in sections[1:]:
        bvid = _extract_bvid(sec)
        if not bvid:
            continue

        # 检查已阅 + 已交流（两者都勾了才处理反馈）
        if not _is_reviewed(sec):
            continue
        if not _is_communicated(sec):
            continue  # 未交流的不调整权重

        # ① 解析 💬 你的看法（逐段批注反馈）
        annotation_feedbacks = _parse_annotations(sec)
        for af in annotation_feedbacks:
            classified = _classify_feedback(af["text"], bvid, af["context"])
            if classified["type"] == "auto":
                auto_actions.append(classified)
            else:
                pending_questions.append(classified)

        # ② 解析 📝 我的评论
        review = _parse_review_section(sec)
        if review:
            classified = _classify_feedback(review, bvid, "视频总体评价")
            if classified["type"] == "auto":
                auto_actions.append(classified)
            else:
                pending_questions.append(classified)

        # ③ 解析 💬 总体反馈
        overall = _parse_overall_feedback(sec)
        if overall:
            classified = _classify_feedback(overall, bvid, "整批推荐方向")
            if classified["type"] == "auto":
                auto_actions.append(classified)
            else:
                pending_questions.append(classified)

    # 保存待确认问题
    if pending_questions:
        _save_pending_questions(note_dir, date_str, pending_questions)

    logger.info(
        f"扫描 {date_str}: auto={len(auto_actions)}, ask={len(pending_questions)}"
    )
    return {"auto_actions": auto_actions, "pending_questions": pending_questions}


# ── 解析函数 ────────────────────────────────


def _extract_bvid(section: str) -> str:
    """从段首或链接中提取 bvid。"""
    # 段首标题
    m = re.search(r"BV[\w]+", section)
    if m:
        return m.group(0)
    # 链接内：bilibili.com/video/BVxxx
    m = re.search(r"video/(BV[\w]+)", section)
    return m.group(1) if m else ""


def _is_reviewed(section: str) -> bool:
    m = re.search(r"✅ 已阅.*\n- \[([ xX])\s*\]", section)
    return bool(m and m.group(1).strip().lower() == "x")


def _is_communicated(section: str) -> bool:
    """检查是否已交流（用户手动勾选或AI交流后勾选）。"""
    m = re.search(r"✅ 已交流.*- \[([ xX])\s*\]", section, re.DOTALL)
    return bool(m and m.group(1).strip().lower() == "x")


def _parse_annotations(section: str) -> list[dict[str, Any]]:
    """提取所有 💬 你的看法 区域。"""
    results = []
    # 匹配 💬 你的看法：后面直到下一个 ## 或 下一个批注的内容
    pattern = r"💬 你的看法：\s*(.*?)(?=\n> \*\*\[|\n> 💡|\n> ⚠️|\n###|\n##|\Z)"
    for m in re.finditer(pattern, section, re.DOTALL):
        text = m.group(1).strip()
        if text and len(text) > 3:
            # 提取上下文（前一个 💡/⚠️ 的内容）
            context = _get_annotation_context(section, m.start())
            results.append({"text": text, "context": context})
    return results


def _get_annotation_context(section: str, pos: int) -> str:
    """找到当前位置之前最近的批注内容作为上下文。"""
    before = section[:pos]
    m = re.search(r"[💡⚠️](?: \*)?(.+?)(?:\*)?(?:\n|$)", before[::-1])
    return m.group(1)[::-1].strip() if m else ""


def _parse_review_section(section: str) -> str:
    """提取 📝 我的评论。"""
    # 从 我的评论 到下一个 ### 之间的内容
    m = re.search(r"📝 我的评论(.*?)(?=\n###)", section, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    return raw.strip()


def _parse_overall_feedback(section: str) -> str:
    """提取 💬 对这次推荐的总体反馈。"""
    m = re.search(r"💬 对这次推荐的总体反馈(.*?)(?:### ✅|$)", section, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    return raw.strip()


# ── 分级分类 ────────────────────────────────


def _classify_feedback(
    text: str, bvid: str, context: str
) -> dict[str, Any]:
    """将反馈分类为 auto 或 ask。"""

    # auto: 明确的黑名单信号
    blacklist_signals = [
        "完全不喜欢", "别再推", "拉黑", "取关这个", "不要这个UP主",
        "跟我关注的UP主差太多", "完全不感兴趣",
    ]
    for sig in blacklist_signals:
        if sig in text:
            return {
                "type": "auto",
                "action": "blacklist_up",
                "bvid": bvid,
                "reason": text[:100],
                "context": context,
            }

    # auto: 明确的加分信号
    boost_signals = [
        "多推这个方向", "这个UP主很好", "以后多推这类", "就是这个风格",
        "很对我的胃口", "分析很好", "喜欢",
    ]
    for sig in boost_signals:
        if sig in text:
            return {
                "type": "auto",
                "action": "boost_direction",
                "bvid": bvid,
                "reason": text[:100],
                "context": context,
            }

    # ask: 模糊信号——需要确认
    if text and len(text) > 2:
        return {
            "type": "ask",
            "bvid": bvid,
            "feedback": text[:200],
            "context": context,
            "question": _generate_question(text, context),
        }

    return {"type": "auto", "action": "skip"}


def _generate_question(feedback: str, context: str) -> str:
    """根据反馈生成确认问题。"""
    if any(w in feedback for w in ["不够严谨", "太浅", "深度不足"]):
        return f"你说「{context[:30]}...」不够严谨——是指论证跳跃、证据不足、还是讲得太浅？"
    if any(w in feedback for w in ["不喜欢", "不是我的菜"]):
        return f"你说不喜欢「{context[:30]}...」——是选题方向不对，还是UP主水平不行？"
    if any(w in feedback for w in ["风格", "像", "不如"]):
        return f"你提到风格问题——是要排除这个UP主，还是让他改进后可以再推？"
    return f"关于「{context[:30]}...」，你的意思是？"


# ── 持久化 ──────────────────────────────────


def _save_pending_questions(
    note_dir: Path, date_str: str, questions: list[dict[str, Any]]
) -> None:
    """保存待确认问题到文件。"""
    qfile = note_dir / ".pending_questions.json"
    existing: list[dict[str, Any]] = []
    if qfile.exists():
        try:
            existing = json.loads(qfile.read_text(encoding="utf-8"))
        except Exception:
            pass

    for q in questions:
        q["date"] = date_str
        existing.append(q)

    qfile.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"待确认问题: {len(questions)} 条 → {qfile}")


def load_pending_questions(note_dir: Path) -> list[dict[str, Any]]:
    """加载待确认问题。"""
    qfile = note_dir / ".pending_questions.json"
    if not qfile.exists():
        return []
    try:
        return json.loads(qfile.read_text(encoding="utf-8"))
    except Exception:
        return []


def clear_pending_questions(note_dir: Path) -> None:
    """清除已确认的问题。"""
    qfile = note_dir / ".pending_questions.json"
    if qfile.exists():
        qfile.unlink()


# ── 兼容旧接口 ──────────────────────────────


def parse_feedback_sentiment(comment: str) -> dict[str, Any]:
    """兼容旧接口：简单情感分析。"""
    sentiment = "neutral"
    reasons: list[str] = []

    negative_signals = [
        ("太浅", "深度不足"), ("没讲清楚", "论证不清"),
        ("灌水", "信息密度低"), ("标题党", "标题党"),
        ("不喜欢", "不感兴趣"), ("无聊", "内容乏味"),
        ("重复", "内容重复"), ("废话", "信息密度低"),
    ]
    positive_signals = [
        ("很好", "喜欢"), ("不错", "喜欢"), ("精彩", "喜欢"),
        ("推荐", "喜欢"), ("深度", "深度满意"), ("厉害", "UP主优质"),
    ]

    for pattern, reason in negative_signals:
        if pattern in comment:
            reasons.append(reason)
            sentiment = "negative"
    for pattern, reason in positive_signals:
        if pattern in comment:
            reasons.append(reason)
            if sentiment != "negative":
                sentiment = "positive"

    return {"sentiment": sentiment, "reasons": list(set(reasons))}
