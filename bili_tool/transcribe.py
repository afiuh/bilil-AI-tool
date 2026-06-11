"""GPU转录 + B站API工具函数。纯工具模块，不参与业务决策。"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_subtitle_text(bvid: str) -> str | None:
    """获取 CC 字幕文本。无字幕返回 None。"""
    from bili_tool.bili_api import get_subtitle_text as _get
    return _get(bvid)


def is_collection(bvid: str) -> bool:
    """判断是否为合集视频。"""
    from bili_tool.bili_api import is_collection as _is
    return _is(bvid)


def get_random_episode_info(bvid: str) -> dict[str, Any] | None:
    """合集随机抽一集。"""
    from bili_tool.bili_api import get_random_episode_info as _ep
    return _ep(bvid)


def get_audio_url(bvid: str) -> str | None:
    """获取视频音频流 URL。"""
    from bili_tool.bili_api import get_audio_url as _url
    return _url(bvid)


def transcribe_batch_gpu(
    audio_map: dict[str, tuple[str, str | None]],
    model_name: str = "paraformer-zh",
    device: str = "cuda:0",
) -> dict[str, str]:
    """GPU 批量转录。audio_map: {bvid: (文件路径, 语言)}。"""
    from bili_tool.bili_api import transcribe_batch_gpu as _batch
    return _batch(audio_map, model_name, device)


def transcribe_single(audio_path: str, device: str = "cuda:0") -> str:
    """GPU 转录单个音频文件。"""
    from bili_tool.bili_api import transcribe_batch_gpu as _batch
    import tempfile, os
    bvid = os.path.basename(audio_path)[:12]
    results = transcribe_batch_gpu({bvid: (audio_path, None)}, device=device)
    return results.get(bvid, "")
