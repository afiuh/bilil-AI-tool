"""定期回顾 CLI 命令。"""

import logging
from bili_tool.config import get_config
from bili_tool.storage import Database
from bili_tool.taste import TasteProfile
from bili_tool._review import run_review

logger = logging.getLogger(__name__)


def cmd_review(days: int = 3) -> None:
    """定期回顾：扫描最近N天笔记，输出结构化数据。"""
    cfg = get_config()
    db = Database()
    taste = TasteProfile.from_dict(db.load_taste() or {})

    result = run_review(cfg.note_dir, taste, db, days=days)

    sep = "=" * 50
    print(f"\n📊 定期回顾（最近{days}天）")
    print(sep)
    print(result["summary"])
    print(f"\n--- 逐条视频 ---")
    for v in result["videos"]:
        line = f"  [{v['score']:.2f}] {v['title'][:50]} | {v['up']} | {v['duration']}"
        print(line)
        if v.get("review"):
            review_preview = v["review"][:100].replace("\n", " ")
            print(f"    📝 {review_preview}...")
        if v.get("annotations"):
            print(f"    💬 {v['annotation_count']}条批注")

    if result.get("pending_questions"):
        print(f"\n⚠️ 待确认问题: {len(result['pending_questions'])}条")

    print(f"\n话题分布: {result['topic_dist']}")
    print(f"均分: {result['avg_score']}, 已阅: {result['reviewed']}/{result['total']}")

    db.close()
