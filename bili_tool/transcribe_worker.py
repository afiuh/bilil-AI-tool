"""GPU转录模块 — whisper.cpp CUDA后端，零PyTorch。"""
import json, logging, subprocess, tempfile, os, re, shutil
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

logger = logging.getLogger(__name__)

MODEL = str(Path.home() / "whisper_models" / "whisper-large-v3-f16.gguf")
EXE = str(Path.home() / "whisper_cuda" / "Release" / "whisper-cli.exe")


def _transcribe_in_subprocess(audio_path: str, bvid: str, cache_path: str) -> bool:
    """子进程: whisper.cpp GPU转录 → 写缓存。返回 True/False。"""
    if not audio_path or not Path(audio_path).exists():
        logger.error("音频文件不存在: %s", audio_path)
        return False

    out_dir = tempfile.mkdtemp()
    out_base = os.path.join(out_dir, "out")
    try:
        result = subprocess.run(
            [EXE, "-m", MODEL, "-f", audio_path,
             "-l", "zh", "--output-txt", "-of", out_base,
             "--no-timestamps"],  # 去掉时间戳，减少输出
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=900,
        )
        out_txt = out_base + ".txt"
        if not Path(out_txt).exists():
            tail = result.stderr.strip()[-300:] if result.stderr else ""
            logger.error("whisper失败 %s: %s", bvid, tail[:200])
            return False

        text = Path(out_txt).read_text(encoding="utf-8").strip()
        text = re.sub(r'\[\d{2}:\d{2}:\d{2}\.\d{3} --> .*?\]', '', text)
        text = " ".join(text.split())
        if len(text) < 50:
            logger.warning("转录太短 %s: %d字", bvid, len(text))
            return False

        data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        data["subtitle"] = text
        data["transcribed_at"] = datetime.now().isoformat()
        Path(cache_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.error("转录异常 %s: %s", bvid, e)
        return False
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def transcribe_batch(run_id: str, bvids: list[str]) -> dict:
    """批量转录。ProcessPoolExecutor(1 worker)。返回 {bvid: bool, ...}。"""
    from bili_tool.cache import video_path, read_video

    if not Path(EXE).exists() or not Path(MODEL).exists():
        logger.error("whisper 模型或二进制缺失")
        return {b: False for b in bvids}

    tasks = []
    for bvid in bvids:
        v = read_video(run_id, bvid)
        audio = v.get("audio_path", "") if v else ""
        if not audio or not Path(audio).exists():
            logger.warning("无音频: %s", bvid)
            continue
        tasks.append((audio, bvid, str(video_path(run_id, bvid))))

    if not tasks:
        return {}

    results = {}
    logger.info("whisper.cpp GPU 转录 %d 条 (1 worker)", len(tasks))
    with ProcessPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(_transcribe_in_subprocess, a, b, c): b for a, b, c in tasks}
        for future in as_completed(futures):
            bvid = futures[future]
            try:
                ok = future.result()
                results[bvid] = ok
                v = read_video(run_id, bvid)
                sub_len = len(v.get("subtitle", "")) if v else 0
                logger.info("%s %s: %d字", "✅" if ok else "⚠️", bvid, sub_len)
            except Exception as e:
                logger.error("❌ %s: %s", bvid, e)
                results[bvid] = False
    return results
