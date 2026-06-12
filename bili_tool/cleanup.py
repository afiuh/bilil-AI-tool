"""缓存清理模块。按文件修改时间自动清理。零依赖，智能体按需调用。"""
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_ROOT = Path.home() / ".bili_tool"
AUDIO_DIR = CACHE_ROOT / "audio"
RUN_DIR = CACHE_ROOT / "run"


def clean_audio(days: int = 2) -> dict:
    """清理音频缓存。删除 >days 天的 wav 文件。"""
    if not AUDIO_DIR.exists():
        return {"files": 0, "size_mb": 0}

    now = time.time()
    cutoff = now - days * 86400
    deleted = 0
    freed = 0

    for f in AUDIO_DIR.glob("*.wav"):
        try:
            mtime = f.stat().st_mtime
            if mtime < cutoff:
                size = f.stat().st_size
                f.unlink()
                deleted += 1
                freed += size
        except Exception as e:
            logger.warning("清理音频失败 %s: %s", f.name, e)

    mb = freed // (1024 * 1024)
    logger.info("音频清理: 删 %d 个, 释放 %d MB", deleted, mb)
    return {"files": deleted, "size_mb": mb}


def clean_runs(days: int = 7) -> dict:
    """清理旧管道数据。删除 >days 天的 run 目录。"""
    if not RUN_DIR.exists():
        return {"dirs": 0, "size_mb": 0}

    now = time.time()
    cutoff = now - days * 86400
    deleted = 0
    freed = 0

    for d in RUN_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            mtime = d.stat().st_mtime
            if mtime < cutoff:
                size = _dir_size(d)
                _rmtree(d)
                deleted += 1
                freed += size
        except Exception as e:
            logger.warning("清理管道失败 %s: %s", d.name, e)

    mb = freed // (1024 * 1024)
    logger.info("管道清理: 删 %d 个目录, 释放 %d MB", deleted, mb)
    return {"dirs": deleted, "size_mb": mb}


def clean_all(audio_days: int = 2, runs_days: int = 7) -> dict:
    """清理全部缓存。返回统计。"""
    a = clean_audio(audio_days)
    r = clean_runs(runs_days)
    return {
        "audio_files": a["files"],
        "audio_mb": a["size_mb"],
        "run_dirs": r["dirs"],
        "run_mb": r["size_mb"],
        "total_mb": a["size_mb"] + r["size_mb"],
    }


# ── 辅助 ──

def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except Exception:
        pass
    return total


def _rmtree(path: Path) -> None:
    for f in path.rglob("*"):
        if f.is_file():
            f.unlink()
    for d in sorted(path.rglob("*"), reverse=True):
        if d.is_dir():
            d.rmdir()
    path.rmdir()
