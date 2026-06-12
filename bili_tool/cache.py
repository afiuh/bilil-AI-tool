"""缓存层：搜索批量文件 + 视频递进文件。所有功能模块通过缓存层交换数据。"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_ROOT = Path.home() / ".bili_tool"
RUN_DIR = CACHE_ROOT / "run"
AUDIO_DIR = CACHE_ROOT / "audio"


# ════════════════════════════════════
# 运行管理
# ════════════════════════════════════

def create_run(run_id: str | None = None) -> str:
    """创建本次运行的文件夹。返回 run_id。"""
    if run_id is None:
        run_id = datetime.now().strftime("%Y-%m-%d-%H")
    d = RUN_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "candidates").mkdir(exist_ok=True)
    (d / "_search").mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return run_id


def list_runs() -> list[str]:
    """列出所有运行文件夹（按时间倒序）。"""
    if not RUN_DIR.exists():
        return []
    return sorted((d.name for d in RUN_DIR.iterdir() if d.is_dir()), reverse=True)


def get_latest_run() -> str | None:
    runs = list_runs()
    return runs[0] if runs else None


# ════════════════════════════════════
# 搜索层：批量文件
# ════════════════════════════════════

def write_search_batch(run_id: str, batch_data: dict) -> str:
    """写入搜索批量文件。返回文件路径。"""
    d = RUN_DIR / run_id / "_search"
    d.mkdir(parents=True, exist_ok=True)
    pid = batch_data.get("pool_id", "pool")
    path = d / f"{pid}_zone{batch_data.get('zone_id','?')}.json"
    batch_data["written_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(batch_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def read_search_batches(run_id: str) -> list[dict]:
    """读取某次运行的所有搜索批量文件。"""
    d = RUN_DIR / run_id / "_search"
    if not d.exists():
        return []
    batches = []
    for f in sorted(d.glob("*.json")):
        try:
            batches.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return batches


# ════════════════════════════════════
# 视频层：递进文件
# ════════════════════════════════════

def video_path(run_id: str, bvid: str) -> Path:
    return RUN_DIR / run_id / "candidates" / f"{bvid}.json"


def video_exists(run_id: str, bvid: str) -> bool:
    return video_path(run_id, bvid).exists()


def read_video(run_id: str, bvid: str) -> dict | None:
    p = video_path(run_id, bvid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_video(run_id: str, bvid: str, data: dict) -> str:
    """写入/更新视频缓存文件。返回路径。"""
    p = video_path(run_id, bvid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def update_video(run_id: str, bvid: str, updates: dict) -> str | None:
    """增量更新视频缓存文件。返回路径或None。"""
    existing = read_video(run_id, bvid)
    if existing is None:
        return None
    existing.update(updates)
    return write_video(run_id, bvid, existing)


def list_videos(run_id: str) -> list[str]:
    """列出某次运行的所有视频缓存 BV 号。"""
    d = RUN_DIR / run_id / "candidates"
    if not d.exists():
        return []
    return sorted(f.stem for f in d.glob("*.json"))


def list_video_data(run_id: str) -> list[dict]:
    """列出某次运行的所有视频缓存数据。"""
    return [d for bvid in list_videos(run_id) if (d := read_video(run_id, bvid))]


# ════════════════════════════════════
# 批量操作
# ════════════════════════════════════

def split_batch_to_videos(run_id: str, batch: dict) -> int:
    """将搜索批量文件拆分为独立的视频缓存文件。返回拆分数。"""
    count = 0
    for c in batch.get("candidates", []):
        bvid = c.get("bvid")
        if not bvid:
            continue
        c["discovered_at"] = datetime.now().isoformat()
        write_video(run_id, bvid, c)
        count += 1
    return count


def split_all_batches(run_id: str) -> int:
    """将该次运行的所有搜索批量文件拆分为视频文件。"""
    total = 0
    for batch in read_search_batches(run_id):
        total += split_batch_to_videos(run_id, batch)
    logger.info("拆分完成: %d 条候选 → candidates/", total)
    return total


def delete_videos(run_id: str, bvids: list[str]) -> int:
    """删除指定视频的缓存文件（策展落选）。返回删除数。"""
    count = 0
    for bvid in bvids:
        p = video_path(run_id, bvid)
        if p.exists():
            p.unlink()
            count += 1
    return count


# ════════════════════════════════════
# 查询辅助
# ════════════════════════════════════

def count_ready(run_id: str) -> dict:
    """检查有多少视频已完成打分+转录。"""
    videos = list_video_data(run_id)
    total = len(videos)
    done_scoring = sum(1 for v in videos if v.get("scoring", {}).get("l3") is not None)
    done_subtitle = sum(1 for v in videos if v.get("subtitle"))
    return {
        "total": total,
        "done_scoring": done_scoring,
        "done_subtitle": done_subtitle,
        "ready": done_scoring == total and done_subtitle == total,
        "missing_scoring": [v["bvid"] for v in videos if v.get("scoring", {}).get("l3") is None],
        "missing_subtitle": [v["bvid"] for v in videos if not v.get("subtitle")],
    }
