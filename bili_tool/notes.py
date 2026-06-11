"""Obsidian笔记读写。格式集中锁定，AI传什么candidate进来都按固定模板输出。"""

from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def write_recommendations(
    candidates: list[dict[str, Any]],
    taste,  # TasteProfile
    date_str: str,
    note_dir: Path,
) -> str:
    """生成推荐笔记并写入Obsidian。返回笔记路径。"""
    content = _build_note_content(candidates, taste, date_str)
    note_path = note_dir / f"推荐-{date_str}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    logger.info(f"笔记已写入: {note_path}")
    return str(note_path)


def mark_reviewed(note_path: str, video_index: int) -> bool:
    """勾选第N条视频的已阅复选框。"""
    return _toggle_checkbox(note_path, video_index, "已阅")


def mark_communicated(note_path: str, video_index: int) -> bool:
    """勾选第N条视频的已交流复选框。"""
    return _toggle_checkbox(note_path, video_index, "已交流")


def get_latest_note(note_dir: Path) -> Path | None:
    """获取最新笔记路径。"""
    notes = sorted(note_dir.glob("推荐-*.md"))
    return notes[-1] if notes else None


def count_reviewed(note_path: str) -> tuple[int, int]:
    """统计已阅状态。(总数, 已阅数)。"""
    content = Path(note_path).read_text(encoding="utf-8")
    total = content.count("✅ 已阅")
    checked = len(re.findall(r'✅ 已阅\s*\n- \[[xX]\]', content))
    return total, checked


def _toggle_checkbox(note_path: str, video_index: int, marker: str) -> bool:
    """勾选指定标记的复选框。"""
    try:
        content = Path(note_path).read_text(encoding="utf-8")
        sections = re.split(r"\n## \d+\.", content)
        if video_index >= len(sections):
            return False
        sec = sections[video_index]
        sec = re.sub(
            rf"(✅ {marker}.*\n- )\[ \]",
            rf"\1[x]",
            sec
        )
        sections[video_index] = sec
        new_content = "\n## ".join(sections) if content.startswith("## ") else content
        Path(note_path).write_text(new_content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"勾选复选框失败: {e}")
        return False


def _build_note_content(
    results: list[dict[str, Any]],
    taste,  # TasteProfile
    today: str,
) -> str:
    """构建笔记内容（内部函数，格式锁定）。"""
    lines = [
        f"# 📺 AI 推荐视频 — {today}",
        "",
        f"> 基于你的口味画像自动生成。共 {len(results)} 条推荐。",
        "",
    ]

    for i, r in enumerate(results, 1):
        title = r.get("title", "无标题")
        bvid = r.get("bvid", "")
        url = f"https://www.bilibili.com/video/{bvid}"
        up = r.get("up_name", "未知")
        dur = r.get("duration_sec", 0)
        dur_str = f"{dur // 60}:{dur % 60:02d}"
        play = r.get("play_count", 0)
        score = r.get("score_l3", 0)
        subtitle = r.get("subtitle_text", "")
        analysis_text = r.get("analysis", "")
        reason = r.get("reason", "")

        full_sub = subtitle[:15000] if subtitle and len(subtitle) > 15000 else subtitle

        lines.extend([
            "---",
            "",
            f"## {i}. {title}",
            "",
            "### 📋 基本信息",
            "| 项目 | 内容 |",
            "|------|------|",
            f"| **UP主** | {up} |",
            f"| **链接** | [{url}]({url}) |",
            f"| **时长** | {dur_str} |",
            f"| **播放量** | {play} |",
            f"| **综合评分** | {score:.2f} |",
            "",
            "### 📖 内容分析",
            analysis_text or "（待分析）",
            "",
            "### 📜 完整字幕（上限1小时）",
            "```text",
            full_sub if full_sub else "（该视频无CC字幕，无法提取）",
            "```",
            "",
            "### 🤖 Hermes 逐段分析",
            "<!-- 待 Hermes 分析后填充 -->",
            "> ⏳ 待分析...",
            "",
            "### 🎯 推荐理由",
            reason or "基于口味画像综合匹配",
            "",
            "### 📝 我的评论",
            "<!-- 喜欢就写为什么喜欢，不喜欢写明原因 -->",
            "",
            "### ✅ 已阅",
            "- [ ] 我看完了，评论已写好 / 没什么想说的",
            "",
            "### ✅ 已交流",
            "- [ ] 已与AI讨论 / 没什么想交流的",
            "",
        ])

    return "\n".join(lines)
