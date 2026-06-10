"""
B站内容发现工具 — CLI 入口

用法：
  python -m bili_tool.cli daily           # 执行每日完整流程
  python -m bili_tool.cli discover        # 仅发现+打分
  python -m bili_tool.cli feedback        # 仅扫描昨日反馈
  python -m bili_tool.cli init-taste      # 初始化口味画像
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from bili_tool.config import get_config
from bili_tool.curator import curate
from bili_tool.discovery import discover
from bili_tool.feedback import parse_feedback_sentiment, scan_feedback_notes
from bili_tool.scoring import score_l1, score_l2, score_l3, score_l2_auto
from bili_tool.storage import Database
from bili_tool.taste import TasteProfile

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def cmd_init_taste() -> None:
    """初始化口味画像（从已有数据或默认值创建）。"""
    db = Database()
    existing = db.load_taste()
    if existing:
        profile = TasteProfile.from_dict(existing)
        logger.info(f"已加载现有画像: {len(profile.topics)} 个话题, {len(profile.up_weights)} 个UP主")
    else:
        profile = TasteProfile()
        # 基于用户已知兴趣设置初始值
        profile.topics = {
            "历史": 0.9, "哲学": 0.8, "社会": 0.7, "影视": 0.7,
            "技术": 0.5, "武术": 0.4,
        }
        profile.min_duration = 600
        profile.prefer_longform = 0.85
        profile.depth_threshold = 0.7
        logger.info("已创建默认画像")

    # [IO] 从 B站 爬取关注列表，排除已关注 UP主
    if not profile.followed_mids:
        from bili_tool.bili_api import get_followings
        logger.info("正在爬取你的 B站关注列表...")
        all_followed: list[dict[str, Any]] = []
        for page in range(1, 6):  # 最多 5 页
            try:
                batch = get_followings(2086841254, page=page)
                if not batch:
                    break
                all_followed.extend(batch)
            except Exception:
                break
        for f in all_followed:
            profile.followed_mids.add(f["mid"])
            if f["name"] not in profile.up_names.values():
                profile.up_names[f["mid"]] = f["name"]
        logger.info(f"已同步 {len(profile.followed_mids)} 位关注的 UP主")

    db.save_taste(profile.to_dict())
    logger.info("口味画像已保存")


def cmd_feedback(date_str: str | None = None) -> dict[str, Any]:
    """扫描反馈：auto 直接优化画像，ask 保存待确认。"""
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    cfg = get_config()
    result = scan_feedback_notes(cfg.note_dir, date_str)
    auto_actions = result.get("auto_actions", [])
    pending = result.get("pending_questions", [])

    if not auto_actions and not pending:
        logger.info("无新反馈")
        return result

    db = Database()
    profile_data = db.load_taste()
    profile = TasteProfile.from_dict(profile_data) if profile_data else TasteProfile()

    # auto: 直接执行
    for action in auto_actions:
        if action.get("action") == "blacklist_up":
            # 需要通过 bvid 找到 mid
            bvid = action["bvid"]
            # 尝试从 candidates 表查 mid
            rows = db._conn.execute(
                "SELECT up_mid FROM candidates WHERE bvid=?", (bvid,)
            ).fetchall()
            if rows:
                mid = rows[0]["up_mid"]
                profile.blacklist.add(mid)
                profile.up_weights.pop(mid, None)
                logger.info(f"auto: 拉黑 UP主 mid={mid} ({action['reason'][:30]})")
        elif action.get("action") == "boost_direction":
            # 话题方向加分
            from bili_tool.feedback import parse_feedback_sentiment
            sentiment = parse_feedback_sentiment(action.get("reason", ""))
            if "喜欢" in str(sentiment.get("reasons", [])):
                for topic in list(profile.topics.keys())[:3]:
                    profile.boost_topic(topic, 0.05)
                logger.info("auto: 强化当前话题方向")

    db.save_taste(profile.to_dict())
    db.close()

    # ask: 提示我有待确认问题
    if pending:
        logger.info(f"⚠️ {len(pending)} 条待确认问题，见 .pending_questions.json")
        for i, q in enumerate(pending[:3]):
            logger.info(f"  {i+1}. {q.get('question', '')}")

    return result


def cmd_discover(limit: int = 10) -> list[dict[str, Any]]:
    """运行发现+打分+策展完整流水线。"""
    db = Database()

    # 加载画像
    profile_data = db.load_taste()
    if not profile_data:
        logger.warning("未找到口味画像，请先运行 init-taste")
        return []
    taste = TasteProfile.from_dict(profile_data)

    # 种子数据
    seed_mids = list(taste.up_weights.keys())[:10]
    seed_bvids = [r["bvid"] for r in db.get_pending(limit=20)]
    recent = db.get_recent_bvids()

    # 发现
    candidates = discover(taste, recent, seed_mids, seed_bvids)
    if not candidates:
        logger.warning("未发现任何候选")
        return []

    # 入池
    db.add_candidates(candidates)

    # L1
    candidates = score_l1(candidates, taste)
    for c in candidates:
        db.update_score(c["bvid"], l1=c["score_l1"])

    # L2 (auto GPU/CPU)
    candidates = score_l2_auto(candidates, taste)
    for c in candidates:
        db.update_score(c["bvid"], l2=c["score_l2"])
        db.mark_status(c["bvid"], "l2_passed")

    # L3
    candidates = score_l3(candidates, taste)
    for c in candidates:
        db.update_score(c["bvid"], l3=c["score_l3"])
        db.mark_status(c["bvid"], "scored")

    # 策展
    result = curate(candidates, db, limit=limit)

    logger.info(f"最终推荐: {len(result)} 条")
    return result


def _build_note_content(
    results: list[dict[str, Any]], taste: TasteProfile, date_str: str
) -> str:
    """根据结果生成 Obsidian 笔记内容。"""
    topics = list(taste.topics.keys())[:5]
    topic_str = "、".join(topics) if topics else "综合"

    lines = [
        "---",
        f"date: {date_str}",
        "tags: [b站推荐]",
        "cssclasses: [bili-recommend]",
        "---",
        "",
        f"# 🎬 B站每日推荐 - {date_str}",
        "",
        f"> 今日推荐 {len(results)} 条视频 | 主题覆盖：{topic_str}",
        "> 推荐依据：基于你的收藏夹画像 + 字幕内容分析",
        "",
    ]

    for i, r in enumerate(results, 1):
        title = r.get("title", "无标题")
        bvid = r.get("bvid", "")
        url = f"https://www.bilibili.com/video/{bvid}"
        up = r.get("up_name", "未知")
        dur = r.get("duration_sec", 0)
        # [C6] 合集时长修正：如果标题含[随机抽样]但时长仍为超大值，强制修正
        if "[随机抽样" in r.get("title", "") and dur > 7200:
            dur = 1800  # 默认30分钟单集
        play = r.get("play_count", 0)
        dur_str = f"{dur // 60}:{dur % 60:02d}"
        score = r.get("score_l3", 0)
        subtitle = r.get("subtitle_text", "")

        # [IO] 完整字幕截取（上限1小时 ≈ 15000字）
        full_sub = ""
        if subtitle:
            max_chars = 15000
            full_sub = subtitle[:max_chars] if len(subtitle) > max_chars else subtitle

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
            _generate_analysis(subtitle, taste),
            "",
            "### 📜 完整字幕（上限1小时）",
            f"```text",
            full_sub if full_sub else "（该视频无CC字幕，无法提取）",
            "```",
            "",
            "### 🤖 Hermes 逐段分析",
            "<!-- 待 Hermes 分析后填充 -->",
            "> ⏳ 待分析...",
            "",
            "### 🎯 推荐理由",
            _generate_reason(r, taste),
            "",
            "### 📝 我的评论",
            "<!-- 喜欢就写为什么喜欢，不喜欢写明原因 -->",
            "",
            "### ✅ 已阅",
            "- [ ] 我看完了，评论已写好 / 没什么想说的",
            "",
        ])

    return "\n".join(lines)


def _generate_analysis(subtitle: str, taste: TasteProfile) -> str:
    """基于字幕生成内容分析文本。"""
    if not subtitle:
        return "（该视频无 CC 字幕，无法自动分析，请观看后自行判断）\n\n- **亮点**：（请观看后自行补充）\n- **不足**：（请观看后自行补充）"

    text_len = len(subtitle)
    causal = len(re.findall(r"(因为|所以|因此|导致|从而|本质|关键)", subtitle))
    structure = len(re.findall(r"(第一|第二|首先|其次|最后|总结)", subtitle))

    parts = []

    # 核心论点
    if text_len > 300:
        first_few = subtitle[:200].strip()
        parts.append(f"- **核心论点**：视频开头提到「{first_few[:100]}...」")
    else:
        parts.append("- **核心论点**：（字幕较短，建议直接观看）")

    # 论证结构
    if structure >= 3:
        parts.append(f"- **论证结构**：有清晰分段标记（{structure} 处），结构完整")
    elif structure >= 1:
        parts.append(f"- **论证结构**：有基本分段（{structure} 处）")

    # 信息密度
    if text_len > 5000:
        parts.append(f"- **信息密度**：字幕较长（{text_len} 字），预期内容充实，信息密度高")
    elif text_len > 2000:
        parts.append(f"- **信息密度**：字幕适中（{text_len} 字）")
    else:
        parts.append(f"- **信息密度**：字幕较短（{text_len} 字），可能为短视频或分P内容")

    parts.append("- **亮点**：（请观看后自行补充）")
    parts.append("- **不足**：（请观看后自行补充）")

    return "\n".join(parts)


def _generate_reason(r: dict[str, Any], taste: TasteProfile) -> str:
    """生成推荐理由。"""
    parts = []
    mid = r.get("up_mid", 0)
    up_w = taste.up_weights.get(mid, 0)
    if up_w > 0.3:
        parts.append(f"你之前收藏过该UP主的内容，信任度较高")
    if r.get("duration_sec", 0) > 1800:
        parts.append(f"长视频（{r['duration_sec'] // 60}分钟），符合你对深度内容的需求")
    parts.append(f"综合评分 {r.get('score_l3', 0):.2f}，L2/L3 分析通过")
    return "；".join(parts) if parts else "基于口味画像综合匹配"


def cmd_daily() -> None:
    """定时检查：最新笔记全部已阅 → 生成新推荐；未阅完 → 跳过。"""
    cfg = get_config()
    today = datetime.now().strftime("%Y-%m-%d-%H")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"=== 定时检查 {today} ===")

    # ① 扫描昨日反馈
    logger.info("① 扫描昨日反馈...")
    cmd_feedback(yesterday)

    # ② 检查最新笔记是否全部已阅
    import glob as _glob
    from pathlib import Path as _Path
    notes = sorted(_glob.glob(str(cfg.note_dir / "推荐-*.md")))
    if notes:
        latest = open(notes[-1], encoding="utf-8").read()
        total = latest.count("✅ 已阅")
        checked = latest.count("- [x]") + latest.count("- [X]")
        if total > 0 and checked < total:
            logger.info(f"② 最新笔记 {checked}/{total} 已阅 → 跳过")
            return
        logger.info(f"② 最新笔记全部已阅 ({checked}/{total}) → 生成新推荐")
    else:
        logger.info("② 无历史笔记 → 生成新推荐")

    # ② 发现+打分
    logger.info("② 运行发现流水线...")
    results = cmd_discover(limit=cfg.daily_count)

    if not results:
        logger.warning("未找到足够的推荐视频")
        return

    # ③ 写入笔记
    logger.info("③ 写入 Obsidian...")
    db = Database()
    profile_data = db.load_taste()
    taste = TasteProfile.from_dict(profile_data) if profile_data else TasteProfile()

    content = _build_note_content(results, taste, today)
    note_path = cfg.note_dir / f"推荐-{today}.md"
    note_path.write_text(content, encoding="utf-8")

    # 记录推荐历史
    for r in results:
        db.mark_recommended(r["bvid"], str(note_path))

    db.close()
    logger.info(f"✅ 管道完成！笔记: {note_path}")
    logger.info("📝 待 Hermes 精校分析...")

    # [IO] 自动精校分析
    logger.info("④ LLM 精校分析...")
    import os
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if api_key:
        from bili_tool.analyzer import post_analyze_note
        updated = post_analyze_note(str(note_path), api_key)
        logger.info(f"精校完成: {updated} 条")
    else:
        logger.warning("未设置 DEEPSEEK_API_KEY，跳过精校分析")


def main() -> None:
    parser = argparse.ArgumentParser(description="B站内容发现工具")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("daily", help="执行每日完整流程")
    sub.add_parser("discover", help="运行发现+打分流水线")
    sub.add_parser("feedback", help="扫描昨日反馈")
    sub.add_parser("init-taste", help="初始化口味画像")

    args = parser.parse_args()

    if args.command == "daily":
        cmd_daily()
    elif args.command == "discover":
        results = cmd_discover()
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r.get('score_l3', 0):.2f}] {r.get('title', '')[:50]}  {r.get('bvid', '')}")
    elif args.command == "feedback":
        cmd_feedback()
    elif args.command == "init-taste":
        cmd_init_taste()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
