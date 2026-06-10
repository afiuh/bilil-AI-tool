"""
GPU 显存监视器 + 异步转录管理器
- 强制 GPU，禁止核显
- 根据剩余显存决定并行任务数
- 显存不足时自动停止新增任务
"""
import logging, threading, time, queue
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    import pynvml; pynvml.nvmlInit()
    _HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _GPU_NAME = pynvml.nvmlDeviceGetName(_HANDLE)
    _GPU_AVAILABLE = True
except Exception:
    _GPU_AVAILABLE = False; _GPU_NAME = "N/A"

@dataclass
class VRAMState:
    total_mb: int = 0; free_mb: int = 0; used_mb: int = 0; gpu_name: str = ""
    @property
    def free_gb(self): return self.free_mb / 1024
    @property
    def usage_ratio(self): return self.used_mb / max(self.total_mb, 1)

def get_vram_state():
    if not _GPU_AVAILABLE: return VRAMState(gpu_name=_GPU_NAME)
    info = pynvml.nvmlDeviceGetMemoryInfo(_HANDLE)
    return VRAMState(
        total_mb=info.total//1024**2, free_mb=info.free//1024**2,
        used_mb=info.used//1024**2, gpu_name=_GPU_NAME)

def calc_concurrent_tasks(per_task_mb=1500):
    state = get_vram_state()
    if not _GPU_AVAILABLE: return 0
    usable = max(0, state.free_mb - 500)
    return min(max(1, usable // per_task_mb), 4)

class VRAMGuard:
    def __init__(self, max_usage=0.85, interval=5.0):
        self.max_usage = max_usage; self.interval = interval
        self._stop = threading.Event(); self._on_oom = []
    def on_oom(self, cb): self._on_oom.append(cb)
    def start(self):
        self._stop.clear()
        threading.Thread(target=self._monitor, daemon=True).start()
    def stop(self): self._stop.set()
    def _monitor(self):
        while not self._stop.is_set():
            s = get_vram_state()
            if s.usage_ratio > self.max_usage:
                logger.warning(f"VRAM high: {s.usage_ratio:.0%}")
                for cb in self._on_oom: cb(s)
            time.sleep(self.interval)
    def is_safe(self, need_mb=500):
        return get_vram_state().free_mb >= need_mb

class AsyncTranscriber:
    """异步转录管理器：GPU 强制 + 显存感知 + 任务队列"""
    def __init__(self, max_workers=None):
        self.max_workers = max_workers or calc_concurrent_tasks()
        self._queue = queue.Queue()
        self._results = {}
        self._running = False
        self._model = None
        logger.info(f"AsyncTranscriber: max_workers={self.max_workers} GPU={_GPU_NAME}")

    def _load_model(self):
        if self._model is not None: return
        import torch
        assert torch.cuda.is_available(), "CUDA required for transcription"
        from funasr import AutoModel
        self._model = AutoModel(model="paraformer-zh", device="cuda:0", disable_update=True)

    def submit(self, task_id: str, audio_path: str) -> None:
        self._queue.put((task_id, audio_path))

    def run_all(self) -> dict[str, str]:
        """运行所有排队任务，返回 {task_id: text}。"""
        self._load_model()
        results = {}
        while not self._queue.empty():
            tid, path = self._queue.get()
            if not guard.is_safe(500):
                logger.warning(f"VRAM low, stopping. {self._queue.qsize()} tasks remaining")
                break
            try:
                r = self._model.generate(input=path)
                results[tid] = r[0].get("text", "") if r else ""
            except Exception as e:
                logger.error(f"Transcribe failed {tid}: {e}")
                results[tid] = ""
        return results

guard = VRAMGuard()
def is_gpu_available(): return _GPU_AVAILABLE
def get_gpu_name(): return _GPU_NAME
