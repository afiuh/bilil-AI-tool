"""GPU转录模块。ProcessPoolExecutor 调用，独立进程干净CUDA上下文。"""
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# ════════════════════════════════════
# Worker 函数（给子进程调用）
# ════════════════════════════════════

def _transcribe_in_subprocess(audio_path: str, bvid: str, cache_path: str) -> bool:
    """
    子进程：加载FunASR → 转录 → 写缓存文件。
    主进程通过 ProcessPoolExecutor.submit 调用。
    返回 True/False。
    """
    try:
        from funasr import AutoModel
        model = AutoModel(
            model="paraformer-zh", device="cuda:0",
            disable_update=True, trust_remote_code=False,
        )
        result = model.generate(input=audio_path, batch_size=1)
        text = result[0].get("text", "") if result else ""

        if len(text) < 50:
            return False

        data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        data["subtitle"] = text
        data["transcribed_at"] = datetime.now().isoformat()
        Path(cache_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


# ════════════════════════════════════
# 批量调度（主进程调用）
# ════════════════════════════════════

def transcribe_batch(run_id: str, bvids: list[str]) -> dict:
    """
    批量转录。ProcessPoolExecutor(1 worker)。
    返回 {bvid: bool, ...}。
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from bili_tool.cache import video_path, read_video

    tasks = []
    for bvid in bvids:
        v = read_video(run_id, bvid)
        if not v:
            continue
        audio = v.get("audio_path", "")
        if not audio or not Path(audio).exists():
            logger.warning("无音频: %s", bvid)
            continue
        cp = str(video_path(run_id, bvid))
        tasks.append((audio, bvid, cp))

    if not tasks:
        return {}

    results = {}
    logger.info("开始转录 %d 条 (1 worker)", len(tasks))
    with ProcessPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(_transcribe_in_subprocess, a, b, c): b for a, b, c in tasks}
        for future in as_completed(futures):
            bvid = futures[future]
            try:
                ok = future.result()
                results[bvid] = ok
                v = read_video(run_id, bvid)
                sub = v.get("subtitle", "") if v else ""
                if ok:
                    logger.info("✅ 转录成功 %s: %d字", bvid, len(sub))
                else:
                    logger.warning("⚠️ 转录失败 %s", bvid)
            except Exception as e:
                logger.error("❌ %s 异常: %s", bvid, e)
                results[bvid] = False

    return results
