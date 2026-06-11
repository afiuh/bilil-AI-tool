"""定期回顾：扫描笔记提取反馈，返回结构化数据供AI分析。"""

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def run_review(
    note_dir: Path,
    taste,       # TasteProfile
    db,          # Database
    days: int = 3,
) -> dict[str, Any]:
    from bili_tool.notes import get_latest_note, count_reviewed
    from bili_tool.feedback import _is_reviewed, _is_communicated

    cutoff = date.today() - timedelta(days=days)
    notes = sorted(note_dir.glob("推荐-*.md"))
    recent = [n for n in notes if _note_date(n) and _note_date(n) >= cutoff]

    if not recent:
        return {"videos": [], "summary": f"最近{days}天无笔记"}

    all_videos = []
    total_reviewed = 0
    total_communicated = 0

    for note_path in recent:
        content = note_path.read_text(encoding="utf-8")
        date_str = note_path.stem.replace("推荐-", "")
        sections = re.split(r'\n## \d+\.', content)

        for i, sec in enumerate(sections[1:], 1):
            video = _extract_video_info(sec, i, date_str)
            if video:
                total_reviewed += 1 if _is_reviewed(sec) else 0
                total_communicated += 1 if _is_communicated(sec) else 0
                all_videos.append(video)

    topics = _calc_topic_dist(all_videos)
    pending = _load_pending(note_dir)
    avg_score = sum(v.get("score", 0) for v in all_videos) / max(len(all_videos), 1)
    has_reviews = sum(1 for v in all_videos if v.get("review"))

    return {
        "videos": all_videos,
        "total": len(all_videos),
        "reviewed": total_reviewed,
        "communicated": total_communicated,
        "topic_dist": topics,
        "avg_score": round(avg_score, 2),
        "videos_with_reviews": has_reviews,
        "pending_questions": pending,
        "note_dates": [n.stem for n in recent],
        "summary": (
            f"共{len(all_videos)}条视频（{len(recent)}篇笔记）。"
            f"已阅{total_reviewed}条，已交流{total_communicated}条。"
            f"均分{avg_score:.2f}。{has_reviews}条有用户评论。"
            f"话题: {topics}。"
        ),
    }


def _note_date(note_path: Path) -> date | None:
    m = re.search(r'(\d{4}-\d{2}-\d{2})', note_path.stem)
    return date.fromisoformat(m.group(1)) if m else None


def _extract_video_info(section: str, idx: int, date_str: str) -> dict[str, Any] | None:
    title_m = re.search(r'^(.+?)\n', section)
    if not title_m:
        return None
    title = title_m.group(1).strip()

    up_m = re.search(r'\*\*UP主\*\* \| (.+?) \|', section)
    score_m = re.search(r'\*\*综合评分\*\* \| (.+?) \|', section)
    dur_m = re.search(r'\*\*时长\*\* \| (.+?) \|', section)

    review_m = re.search(
        r'### 📝 我的评论\s*\n(?:<!--.*?-->\s*\n?)?(.+?)(?=\n###|\n---|\Z)',
        section, re.DOTALL
    )
    review = ""
    if review_m:
        r = review_m.group(1).strip()
        r = re.sub(r'### ✅.*', '', r, flags=re.DOTALL).strip()
        if r and '我看完了' not in r[:20]:
            review = r[:500]

    annotations = []
    for m in re.finditer(
        r'> 💬 你的看法：\s*\n>\s*(.+?)(?=\n>|\n###|\n---)',
        section, re.DOTALL
    ):
        text = m.group(1).strip()
        if len(text) > 5:
            annotations.append(text[:200])

    return {
        "idx": idx,
        "date": date_str,
        "title": title[:80],
        "up": up_m.group(1).strip() if up_m else "?",
        "duration": dur_m.group(1).strip() if dur_m else "?",
        "score": float(score_m.group(1)) if score_m else 0,
        "review": review,
        "annotations": annotations,
        "annotation_count": len(annotations),
    }


def _calc_topic_dist(videos: list[dict]) -> dict[str, int]:
    topics = {"历史": 0, "哲学": 0, "影视": 0, "社会": 0, "其他": 0}
    topic_kw = {
        "历史": ["历史", "朝代", "战争", "帝国", "三国", "明朝", "唐朝", "古代"],
        "哲学": ["哲学", "思辨", "辩证", "唯物", "认知", "方法论", "福柯"],
        "影视": ["解读", "影评", "剧评", "吐槽", "电影", "电视剧"],
        "社会": ["社会", "政治", "权力", "博弈", "阶层", "规则"],
    }
    for v in videos:
        for t, kws in topic_kw.items():
            if any(kw in v["title"] for kw in kws):
                topics[t] += 1
                break
        else:
            topics["其他"] += 1
    return topics


def _load_pending(note_dir: Path) -> list[dict]:
    pq_path = note_dir / ".pending_questions.json"
    if pq_path.exists():
        try:
            return json.loads(pq_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []
