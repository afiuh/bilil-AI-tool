"""管道守护线程。每10分钟检查运行状态，异常自动报警。"""
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class PipelineWatchdog:
    """管道守护。每10分钟巡检，检测停滞/异常。"""

    def __init__(self, interval: int = 600):
        self.interval = interval
        self._running = False
        self._last_gpu_queue_size = 0
        self._last_cache_count = 0
        self._stuck_count = 0
        self._thread = None

    # ── 启动/停止 ──

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[守护] 启动 (每%d分钟)", self.interval // 60)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # ── 巡检 ——

    def _loop(self):
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break
            self._check()

    def _check(self):
        from bili_tool.pool import get_gpu_queue_size
        from bili_tool.cache import VIDEO_CACHE_DIR

        qsize = get_gpu_queue_size()
        cache_count = len(list(VIDEO_CACHE_DIR.glob("*.json"))) if VIDEO_CACHE_DIR.exists() else 0

        # 检测停滞：队列大小和缓存数都没变化
        if qsize == self._last_gpu_queue_size and cache_count == self._last_cache_count:
            self._stuck_count += 1
        else:
            self._stuck_count = 0

        status = "⚠️ 疑似停滞" if self._stuck_count >= 2 else "✅ 正常"
        logger.info(
            "[守护] %s | GPU队列:%d | 缓存:%d | 停滞计数:%d",
            status, qsize, cache_count, self._stuck_count,
        )
        self._last_gpu_queue_size = qsize
        self._last_cache_count = cache_count

        # 写状态文件供 Hermes 读取
        import json
        status_file = Path.home() / '.bili_tool' / 'watchdog_status.json'
        status_file.parent.mkdir(parents=True, exist_ok=True)
        import datetime
        status_file.write_text(json.dumps({
            'timestamp': datetime.datetime.now().isoformat(),
            'status': status,
            'gpu_queue_size': qsize,
            'cache_count': cache_count,
            'stuck_count': self._stuck_count,
        }, ensure_ascii=False), encoding='utf-8')


# ── 便捷函数 ──

_watchdog: PipelineWatchdog | None = None


def start_watchdog():
    global _watchdog
    _watchdog = PipelineWatchdog()
    _watchdog.start()


def stop_watchdog():
    global _watchdog
    if _watchdog:
        _watchdog.stop()
        _watchdog = None
