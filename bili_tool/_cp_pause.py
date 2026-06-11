"""检查点暂停逻辑。打印完整数据，AI审查后决定继续或中止。"""

import json
import logging

logger = logging.getLogger(__name__)


def checkpoint_pause(stage: int, data: dict) -> None:
    """管道暂停点。ok=True自动继续，ok=False打印数据等待AI处理。"""
    sep = "=" * 50
    lines = [
        "",
        sep,
        f"🛑 检查点 {stage} — 管道暂停",
        sep,
    ]

    if data.get("warning"):
        lines.append(f"⚠️  警告: {data['warning']}")
    else:
        lines.append("✅ 状态正常")

    lines.append("")
    lines.append(f"📋 摘要: {data['summary']}")
    lines.append("")
    lines.append("📊 详细数据:")

    for k, v in data.get("details", {}).items():
        lines.append(f"   {k}: {v}")

    if data.get("ok"):
        lines.append("")
        lines.append("→ 自动继续...")
        for line in lines:
            logger.info(line)
        return

    # 有警告 → 让 AI 决定
    lines.append("")
    lines.append("⚠️  检测到问题，AI 正在审查...")
    lines.append("（管道暂停。AI 审查后决定继续/修复/中止）")

    for line in lines:
        logger.warning(line)
