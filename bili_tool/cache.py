"""管道缓存。每阶段自动存盘，崩了可断点恢复，正常结束自动清理。"""

from __future__ import annotations
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_ROOT = Path.home() / ".bili_tool" / "cache"


def _cache_dir(run_id: str) -> Path:
    d = CACHE_ROOT / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(stage: str, candidates: list[dict[str, Any]], run_id: str) -> str:
    """保存阶段数据。返回文件路径。"""
    d = _cache_dir(run_id)
    path = d / f"{stage}.json"
    # 只保存可序列化字段
    clean = [{k: v for k, v in c.items() if isinstance(v, (str, int, float, bool, type(None), list, dict))}
             for c in candidates]
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug(f"缓存: {path} ({len(clean)}条)")
    return str(path)


def load(stage: str, run_id: str) -> list[dict[str, Any]] | None:
    """加载阶段缓存。不存在返回None。"""
    d = _cache_dir(run_id)
    path = d / f"{stage}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info(f"从缓存恢复: {stage} ({len(data)}条)")
        return data
    except Exception as e:
        logger.warning(f"缓存读取失败: {e}")
        return None


def list_runs() -> list[str]:
    """列出所有缓存运行ID（按时间排序）。"""
    if not CACHE_ROOT.exists():
        return []
    return sorted(d.name for d in CACHE_ROOT.iterdir() if d.is_dir())


def get_latest_stage(run_id: str) -> str | None:
    """获取某次运行的最新缓存阶段。"""
    d = _cache_dir(run_id)
    stages = sorted(
        [f.stem for f in d.glob("*.json")],
        key=lambda s: int(s.split("_")[0]) if s.split("_")[0].isdigit() else 99
    )
    return stages[-1] if stages else None


def cleanup(run_id: str) -> None:
    """清理某次运行的缓存目录。"""
    d = _cache_dir(run_id)
    if d.exists():
        shutil.rmtree(d)
        logger.debug(f"缓存已清理: {d}")


def clear_all() -> None:
    """清理所有缓存。"""
    if CACHE_ROOT.exists():
        shutil.rmtree(CACHE_ROOT)
        logger.info("全部缓存已清理")


# ═══════════════════════════════════════════
# 视频级缓存（v0.4.0）
# ═══════════════════════════════════════════

VIDEO_CACHE_DIR = CACHE_ROOT.parent / "video_cache"


def save_video(bvid: str, data: dict) -> str:
    """保存单视频缓存。返回文件路径。"""
    d = VIDEO_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{bvid}.json"
    from datetime import datetime
    data["cached_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_video(bvid: str) -> dict | None:
    """加载单视频缓存。不存在返回None。"""
    path = VIDEO_CACHE_DIR / f"{bvid}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def has_video(bvid: str) -> bool:
    """检查视频是否已缓存。"""
    return (VIDEO_CACHE_DIR / f"{bvid}.json").exists()


def cache_scoring(bvid: str, candidate: dict) -> None:
    """缓存单个视频的打分数据。已存在则合并更新。"""
    existing = load_video(bvid) or {}
    existing["bvid"] = bvid
    existing["title"] = candidate.get("title", existing.get("title", ""))
    existing["up_mid"] = candidate.get("up_mid", existing.get("up_mid", 0))
    existing["up_name"] = candidate.get("up_name", existing.get("up_name", ""))
    existing["duration_sec"] = candidate.get("duration_sec", existing.get("duration_sec", 0))
    existing["partition"] = candidate.get("partition", existing.get("partition", ""))
    existing["scoring"] = {
        "l1": candidate.get("score_l1", existing.get("scoring", {}).get("l1", 0)),
        "l2": candidate.get("score_l2", existing.get("scoring", {}).get("l2", 0)),
        "l3": candidate.get("score_l3", existing.get("scoring", {}).get("l3", 0)),
        "soup": candidate.get("soup_score", existing.get("scoring", {}).get("soup", -1)),
    }
    save_video(bvid, existing)


def cache_subtitle(bvid: str, text: str) -> None:
    """缓存单个视频的字幕。已存在则合并更新。"""
    existing = load_video(bvid) or {}
    existing["bvid"] = bvid
    existing["subtitle"] = text
    existing["subtitle_len"] = len(text)
    save_video(bvid, existing)
