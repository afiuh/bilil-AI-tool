"""音频下载模块。下载到 ~/.bili_tool/audio/，写 audio_path 到视频缓存。"""
import logging
import requests
from pathlib import Path
from bili_tool.cache import AUDIO_DIR, update_video, read_video

logger = logging.getLogger(__name__)


def download_audio(run_id: str, bvid: str, max_sec: int = 3600) -> str | None:
    """下载视频音频到缓存目录。max_sec=None=不限时。返回路径或None。"""
    from bili_tool.config import get_config
    from bili_tool.bili_api import _get_cid

    cfg = get_config()
    try:
        cid = _get_cid(bvid)
        url = (
            f"https://api.bilibili.com/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&fnval=16&fourk=1"
        )
        resp = requests.get(url, headers=cfg.headers, cookies=cfg.cookie_dict, timeout=10)
        data = resp.json().get("data", {})
        audio = data.get("dash", {}).get("audio", [{}])
        audio_url = audio[0].get("baseUrl") if audio else None
        if not audio_url:
            logger.warning("无音频URL: %s", bvid)
            return None
    except Exception as e:
        logger.error("获取音频URL失败 %s: %s", bvid, e)
        return None

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / f"{bvid}.m4a"

    try:
        resp = requests.get(audio_url, headers=cfg.headers, cookies=cfg.cookie_dict, timeout=300, stream=True)
        resp.raise_for_status()
        max_bytes = max_sec * 16000 * 2
        downloaded = 0
        with open(path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if max_bytes and downloaded >= max_bytes:
                        break
        # 转 wav (whisper.cpp 需要)
        wav_path = path.with_suffix('.wav')
        import subprocess
        subprocess.run(
            ['ffmpeg', '-i', str(path), '-ar', '16000', '-ac', '1', '-y', str(wav_path)],
            capture_output=True, timeout=60,
        )
        if wav_path.exists():
            path.unlink()  # 删 m4a，留 wav
            update_video(run_id, bvid, {"audio_path": str(wav_path)})
        else:
            update_video(run_id, bvid, {"audio_path": str(path)})

        logger.info("音频下载完成: %s (%d KB)", bvid, downloaded // 1024)
        return str(wav_path if wav_path.exists() else path)
    except Exception as e:
        logger.error("下载失败 %s: %s", bvid, e)
        if path.exists():
            path.unlink()
        return None
