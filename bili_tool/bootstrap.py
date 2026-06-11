"""启动自检。清编译缓存+卸载旧模块，确保运行最新代码。"""
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_fresh() -> dict:
    """清 __pycache__ + 卸载 bili_tool.* 模块。返回清理摘要。"""
    result = {"pyc_cleaned": 0, "modules_unloaded": []}

    # ① 清 __pycache__
    root = Path(__file__).parent
    for cache_dir in root.rglob("__pycache__"):
        for pyc in cache_dir.glob("*.pyc"):
            try:
                pyc.unlink()
                result["pyc_cleaned"] += 1
                logger.debug("清理: %s", pyc.name)
            except Exception:
                pass

    # ② 卸载旧模块
    to_unload = [k for k in list(sys.modules) if k.startswith("bili_tool.")]
    for key in to_unload:
        del sys.modules[key]
        result["modules_unloaded"].append(key)

    logger.info(
        "__pycache__: 清理 %d 个 .pyc | sys.modules: 卸载 %d 个 (%s)",
        result["pyc_cleaned"],
        len(result["modules_unloaded"]),
        ", ".join(k.split(".")[-1] for k in result["modules_unloaded"][:6]),
    )
    return result
