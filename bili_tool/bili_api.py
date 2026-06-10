"""
B站内容发现工具 — B站 API 封装

基于 requests + 手动 Cookie 认证。
所有请求带 timeout + 异常处理 + 节流。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from bili_tool.config import get_config

logger = logging.getLogger(__name__)

# B站 API 基础 URL
_API_BASE = "https://api.bilibili.com"
_SEARCH_URL = f"{_API_BASE}/x/web-interface/wbi/search/type"
_VIDEO_INFO_URL = f"{_API_BASE}/x/web-interface/view"
_RELATED_URL = f"{_API_BASE}/x/web-interface/archive/related"
_FOLLOWINGS_URL = f"{_API_BASE}/x/relation/followings"
_UPPER_VIDEOS_URL = f"{_API_BASE}/x/space/wbi/arc/search"
_SUBTITLE_URL = f"{_API_BASE}/x/player/wbi/v2"

# ── 请求工具 ────────────────────────────────


def _get_headers() -> dict[str, str]:
    cfg = get_config()
    return dict(cfg.headers)  # [IO] 复制避免副作用


def _throttle() -> None:
    """请求节流。"""
    time.sleep(get_config().request_interval)


def _safe_get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """[IO] 安全 GET 请求，带超时 + 异常处理。"""
    cfg = get_config()
    headers = _get_headers()
    _throttle()
    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            cookies=cfg.cookie_dict,
            timeout=cfg.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"B站 API 返回错误: code={data.get('code')} msg={data.get('message')}")
        return data
    except requests.RequestException as e:  # [ERR]
        logger.error(f"请求失败 {url}: {e}")
        return {"code": -1, "message": str(e), "data": {}}


# ── 搜索 ─────────────────────────────────────


def search_videos(
    keyword: str, page: int = 1, page_size: int = 20
) -> list[dict[str, Any]]:
    """搜索视频，返回结构化候选列表。"""
    params = {
        "search_type": "video",
        "keyword": keyword,
        "page": page,
        "order": "totalrank",  # 综合排序
    }
    data = _safe_get(_SEARCH_URL, params)
    result = data.get("data", {}).get("result", [])
    if not result:
        return []
    return [_parse_search_item(item) for item in result]


def _parse_search_item(item: dict[str, Any]) -> dict[str, Any]:
    """将搜索结果项转为标准格式。"""
    return {
        "bvid": item.get("bvid", ""),
        "title": item.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", ""),
        "up_name": item.get("author", ""),
        "up_mid": item.get("mid", 0),
        "duration_sec": _parse_duration(item.get("duration", "0:00")),
        "play_count": item.get("play", 0),
        "pub_date": item.get("pubdate", ""),
        "cover_url": item.get("pic", ""),
        "partition": item.get("typename", ""),
    }


# ── 视频信息 ──────────────────────────────────


def get_video_info(bvid: str) -> dict[str, Any] | None:
    """获取单个视频的详细信息。"""
    data = _safe_get(_VIDEO_INFO_URL, {"bvid": bvid})
    v = data.get("data", {})
    if not v:
        return None
    return {
        "bvid": v.get("bvid", bvid),
        "title": v.get("title", ""),
        "up_name": v.get("owner", {}).get("name", ""),
        "up_mid": v.get("owner", {}).get("mid", 0),
        "duration_sec": v.get("duration", 0),
        "play_count": v.get("stat", {}).get("view", 0),
        "pub_date": v.get("pubdate", ""),
        "cover_url": v.get("pic", ""),
        "partition": v.get("tname", ""),
    }


# ── 字幕提取 ──────────────────────────────────


def get_subtitle_text(bvid: str) -> str:
    """获取视频字幕全文（CC 字幕）。"""
    cid = _get_cid(bvid)
    if not cid:
        return ""
    params = {"bvid": bvid, "cid": cid}
    data = _safe_get(f"{_API_BASE}/x/player/wbi/v2", params)
    subtitle_list = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
    if not subtitle_list:
        return ""
    # 取第一个中文字幕
    sub_url = ""
    for s in subtitle_list:
        if "zh" in s.get("lan", ""):
            sub_url = s.get("subtitle_url", "")
            break
    if not sub_url and subtitle_list:
        sub_url = subtitle_list[0].get("subtitle_url", "")
    if not sub_url:
        return ""
    try:
        resp = requests.get("https:" + sub_url, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("body", [])
        return " ".join([it.get("content", "") for it in items])
    except Exception:  # [ERR] 字幕拉取失败不阻断流程
        return ""


def _get_cid(bvid: str) -> int:
    """获取视频的 cid（分P ID）。"""
    data = _safe_get(_VIDEO_INFO_URL, {"bvid": bvid})
    pages = data.get("data", {}).get("pages", [])
    return pages[0].get("cid", 0) if pages else 0


# ── 关联推荐 ──────────────────────────────────


def get_related_videos(bvid: str, limit: int = 20) -> list[dict[str, Any]]:
    """获取视频的关联推荐列表。"""
    data = _safe_get(_RELATED_URL, {"bvid": bvid})
    items = data.get("data", []) or []
    results = []
    for item in items[:limit]:
        results.append({
            "bvid": item.get("bvid", ""),
            "title": item.get("title", ""),
            "up_name": item.get("owner", {}).get("name", ""),
            "up_mid": item.get("owner", {}).get("mid", 0),
            "duration_sec": item.get("duration", 0),
            "play_count": item.get("stat", {}).get("view", 0),
            "pub_date": item.get("pubdate", ""),
            "cover_url": item.get("pic", ""),
            "partition": item.get("tname", ""),
        })
    return results


# ── UP主相关 ──────────────────────────────────


def get_followings(mid: int, page: int = 1) -> list[dict[str, Any]]:
    """获取某 UP主 的关注列表。"""
    data = _safe_get(_FOLLOWINGS_URL, {"vmid": mid, "pn": page, "ps": 50})
    items = data.get("data", {}).get("list", [])
    return [{"mid": it.get("mid", 0), "name": it.get("uname", "")} for it in items]


def get_upper_videos(
    mid: int, page: int = 1, page_size: int = 30
) -> list[dict[str, Any]]:
    """获取某 UP主 的视频列表。"""
    data = _safe_get(_UPPER_VIDEOS_URL, {
        "mid": mid, "pn": page, "ps": page_size, "order": "pubdate",
    })
    vlist = data.get("data", {}).get("list", {}).get("vlist", [])
    results = []
    for v in vlist:
        results.append({
            "bvid": v.get("bvid", ""),
            "title": v.get("title", ""),
            "up_name": v.get("author", ""),
            "up_mid": v.get("mid", mid),
            "duration_sec": _parse_duration(v.get("length", "0:00")),
            "play_count": v.get("play", 0),
            "pub_date": v.get("created", ""),
            "cover_url": v.get("pic", ""),
            "partition": v.get("tname", ""),
        })
    return results


# ── 辅助 ──────────────────────────────────────


def _parse_duration(dur: str) -> int:
    """解析时长字符串 'mm:ss' 或 'hh:mm:ss' → 秒。"""
    parts = dur.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


# ── 合集处理 ──────────────────────────────────


def get_video_pages(bvid: str) -> list[dict[str, Any]]:
    """获取视频所有分P信息。"""
    data = _safe_get(_VIDEO_INFO_URL, {"bvid": bvid})
    return data.get("data", {}).get("pages", [])


def is_collection(bvid: str) -> bool:
    """判断是否是合集（>3 个分P）。"""
    pages = get_video_pages(bvid)
    return len(pages) > 3


def get_random_episode_info(bvid: str) -> dict[str, Any] | None:
    """从合集中随机抽一集，返回该集的信息。"""
    import random
    pages = get_video_pages(bvid)
    if not pages:
        return None
    page = random.choice(pages)
    return {
        "cid": page.get("cid", 0),
        "part": page.get("part", ""),
        "duration_sec": page.get("duration", 0),
    }


# ── 音频转文字 ──────────────────────────────────


def get_audio_url(bvid: str, cid: int | None = None) -> str:
    """获取视频音频流 URL。"""
    if cid is None:
        cid = _get_cid(bvid)
    data = _safe_get(f"{_API_BASE}/x/player/playurl", {
        "bvid": bvid, "cid": cid, "fnval": 16, "fourk": 1,
    })
    dash = data.get("data", {}).get("dash", {})
    audios = dash.get("audio", [])
    if audios:
        return audios[0].get("baseUrl", audios[0].get("base_url", ""))
    return ""


def transcribe_audio_segment(bvid: str, cid: int | None = None, max_sec: int = 600) -> str:
    """下载视频前 max_sec 秒音频并转文字（使用 FunASR paraformer-zh）。"""
    audio_url = get_audio_url(bvid, cid)
    if not audio_url:
        return ""

    import tempfile
    import os
    try:
        # [IO] 下载音频到临时文件
        cfg = get_config()
        resp = requests.get(
            audio_url,
            headers={**cfg.headers, "Referer": "https://www.bilibili.com"},
            cookies=cfg.cookie_dict,
            timeout=60,
            stream=True,
        )
        resp.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
        downloaded = 0
        max_bytes = max_sec * 16000
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                tmp.write(chunk)
                downloaded += len(chunk)
                if downloaded >= max_bytes:
                    break
        tmp.close()

        # [IO] FunASR 转文字（中文专精，模型缓存）
        from funasr import AutoModel
        if not hasattr(transcribe_audio_segment, "_model"):
            transcribe_audio_segment._model = AutoModel(
                model="paraformer-zh", device="cpu", disable_update=True
            )  # type: ignore[attr-defined]
        result = transcribe_audio_segment._model.generate(input=tmp.name)  # type: ignore[attr-defined]
        os.unlink(tmp.name)

        if result and len(result) > 0:
            return result[0].get("text", "")
        return ""

    except Exception as e:
        logger.warning(f"音频转文字失败 {bvid}: {e}")
        return ""

# ── GPU 异步转录接口 ────────────────────────

def transcribe_batch_gpu(bvid_audio_map: dict[str, tuple[str, int | None]]) -> dict[str, str]:
    """[IO] GPU 异步批量转录 {bvid: (audio_file_path, cid)} → {bvid: text}。

    强制 CUDA，禁止 CPU/核显。自动根据显存控制并行数。
    """
    from bili_tool.gpu_monitor import AsyncTranscriber, guard, is_gpu_available, get_gpu_name

    if not is_gpu_available():
        logger.warning("GPU 不可用，跳过转录")
        return {}

    import torch
    if not torch.cuda.is_available():
        logger.error("CUDA 不可用，无法使用 GPU 转录")
        return {}

    logger.info(f"GPU 转录: {get_gpu_name()} | 任务数: {len(bvid_audio_map)}")
    guard.start()

    transcriber = AsyncTranscriber()
    for bvid, (audio_path, cid) in bvid_audio_map.items():
        transcriber.submit(bvid, audio_path)

    results = transcriber.run_all()
    guard.stop()

    # 清理临时音频文件
    import os
    for path, _ in bvid_audio_map.values():
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass

    return results
