"""5池并行发现引擎。"""
import logging, queue, threading, time
logger = logging.getLogger(__name__)
_gpu_queue = queue.Queue()
_pool_results = {}
_results_lock = threading.Lock()
PARTITION_WHITELIST = [207, 36, 35, 181, 188, 122]
PARTITION_KEYWORDS = {
    207: ["历史","朝代","制度","战争","帝国","博弈"],
    36: ["知识","科普","深度","原理"],
    35: ["社会","哲学","政治","权力","博弈"],
    181: ["影评","剧评","解读","人物解析"],
    188: ["科技","技术","原理","科普"],
    122: ["经济","财经","商业","分析"],
}
SEARCH_SORTS = ["hot", "newest"]

class PoolRunner:
    def __init__(self, pool_id, partition_id, keywords, taste, max_retries=3):
        self.pool_id = pool_id
        self.partition_id = partition_id
        self.keywords = keywords
        self.taste = taste
        self.max_retries = max_retries
        self._retries_left = max_retries
        self._seen_bvids = set()
        self._sort_idx = 0
        self._page = 1
        self.seed_mids: list = []
        self.seed_bvids: list = []

    def run(self):
        from bili_tool.config import get_config
        self._cfg = get_config()
        # 种子注入（首轮）
        extra = self._inject_seeds()

        while self._retries_left >= 0:
            c = self._search()
            if extra:
                c = extra + c
                extra = []  # 只在首轮注入
            if not c:
                self._retries_left -= 1
                self._rotate_strategy()
                continue
            c = self._score_l1_l2(c)
            self._collect_transcriptions(c)
            c = self._score_l3(c)
            if self._is_satisfied(c):
                self._retries_left = 0
                break
            self._retries_left -= 1
            self._rotate_strategy()
        return self._select_top(c)

    def _inject_seeds(self, max_new=10):
        """用种子数据发现新内容：UP主蔓延 + 关联推荐。"""
        extra = []
        # UP主蔓延：爬关注UP主的关注链，发现新UP主，拉他们视频
        if self.seed_mids:
            try:
                from bili_tool.discovery import _spread_up_chain
                from bili_tool.bili_api import get_upper_videos
                new_mids = _spread_up_chain(self.taste, self.seed_mids[:20], depth=1)
                for mid in new_mids[:max_new]:
                    if mid not in self.taste.followed_mids:
                        videos = get_upper_videos(mid, page=1, page_size=3)
                        for v in videos:
                            bvid = v.get("bvid", "")
                            if bvid and bvid not in self._seen_bvids:
                                self._seen_bvids.add(bvid)
                                v["_pool_id"] = self.pool_id
                                v["_source"] = "spread"
                                extra.append(v)
            except Exception as e:
                logger.debug("[%s] UP蔓延失败: %s", self.pool_id, e)

        # 关联推荐：基于收藏夹BV号找相关视频
        if self.seed_bvids:
            try:
                from bili_tool.bili_api import get_related_videos
                import random as _rnd
                sample = _rnd.sample(self.seed_bvids, min(3, len(self.seed_bvids)))
                for bvid in sample:
                    related = get_related_videos(bvid, limit=5)
                    for v in related:
                        vbvid = v.get("bvid", "")
                        if vbvid and vbvid not in self._seen_bvids:
                            self._seen_bvids.add(vbvid)
                            v["_pool_id"] = self.pool_id
                            v["_source"] = "related"
                            extra.append(v)
            except Exception as e:
                logger.debug("[%s] 关联推荐失败: %s", self.pool_id, e)

        logger.info("[%s] 种子注入: +%d条 (蔓延%d+关联%d)",
                     self.pool_id, len(extra),
                     sum(1 for v in extra if v.get("_source")=="spread"),
                     sum(1 for v in extra if v.get("_source")=="related"))
        return extra

    def _search(self):
        from bili_tool.bili_api import search_videos
        sort = SEARCH_SORTS[self._sort_idx % len(SEARCH_SORTS)]
        kw = self.keywords[self._sort_idx % len(self.keywords)]
        import random as _random
        time.sleep(_random.uniform(0.5, 2.0))  # [IO] 防止5池并发触发B站风控
        try:
            results = search_videos(kw, page=self._page, page_size=15)
        except Exception as e:
            logger.warning("[%s] search: %s", self.pool_id, e)
            return []
        new = []
        for r in results:
            bvid = r.get("bvid", "")
            if bvid and bvid not in self._seen_bvids:
                self._seen_bvids.add(bvid)
                r["_pool_id"] = self.pool_id
                new.append(r)
        logger.info("[%s] search %s p%d -> %d new", self.pool_id, kw, self._page, len(new))
        return new

    def _rotate_strategy(self):
        self._sort_idx += 1
        if self._sort_idx >= len(SEARCH_SORTS) * 2:
            self._page += 1
            self._sort_idx = 0

    def _score_l1_l2(self, candidates):
        from bili_tool.scoring import score_l1, score_l2
        candidates = score_l1(candidates, self.taste)
        if not candidates:
            return []
        for c in candidates:
            self._defer_transcription(c)
        return score_l2(candidates, self.taste)

    def _defer_transcription(self, candidate):
        from bili_tool.transcribe import get_subtitle_text, get_audio_url
        bvid = candidate.get("bvid", "")
        if candidate.get("subtitle_text"):
            return
        sub = get_subtitle_text(bvid)
        if sub and len(sub) >= 100:
            candidate["subtitle_text"] = sub
            return
        url = get_audio_url(bvid)
        if not url:
            candidate["subtitle_text"] = ""
            return
        _gpu_queue.put({"pool_id": self.pool_id, "bvid": bvid, "audio_url": url})

    def _collect_transcriptions(self, candidates):
        dl = time.time() + 30
        pending = {c["bvid"]: c for c in candidates
                   if not c.get("subtitle_text") and c.get("subtitle_text") != ""}
        if not pending:
            return
        while pending and time.time() < dl:
            with _results_lock:
                if self.pool_id not in _pool_results:
                    time.sleep(0.5)
                    continue
                for bvid, text in list(_pool_results[self.pool_id].items()):
                    if bvid in pending:
                        pending[bvid]["subtitle_text"] = text
                        del pending[bvid]
                if not pending:
                    del _pool_results[self.pool_id]
            time.sleep(0.5)
        for c in pending.values():
            c["subtitle_text"] = ""

    def _score_l3(self, candidates):
        from bili_tool.scoring import score_l3
        if not candidates:
            return []
        return score_l3(candidates, self.taste)

    def _is_satisfied(self, candidates):
        if len(candidates) < 2:
            return False
        avg = sum(c.get("score_l3", 0) for c in candidates) / len(candidates)
        if avg < 0.3:
            return False
        soup = sum(1 for c in candidates if c.get("soup_score", 0) > 0.6)
        if soup / len(candidates) > 0.5:
            return False
        return True

    def _select_top(self, candidates, n=2):
        from bili_tool.curator import rank
        return rank(candidates, sort_by="score_l3")[:n]


def process_gpu_queue(device="cuda:0"):
    processed = 0
    while not _gpu_queue.empty():
        if not vram_safe_to_transcribe():
            time.sleep(1.0)
            continue
        try:
            task = _gpu_queue.get(timeout=1)
        except queue.Empty:
            break
        pid = task["pool_id"]
        bvid = task["bvid"]
        try:
            text = _transcribe_one(task, device)
            ok = text and len(text) >= 50
            with _results_lock:
                _pool_results.setdefault(pid, {})[bvid] = text if ok else ""
            logger.info("GPU %s: [%s] %s", "OK" if ok else "SHORT", pid, bvid)
        except Exception as e:
            logger.error("GPU fail [%s] %s: %s", pid, bvid, e)
            with _results_lock:
                _pool_results.setdefault(pid, {})[bvid] = ""
        processed += 1
    return processed


def _transcribe_one(task, device):
    import requests, tempfile, os
    from bili_tool.config import get_config
    from bili_tool.bili_api import transcribe_batch_gpu
    cfg = get_config()
    bvid = task["bvid"]
    resp = requests.get(task["audio_url"], headers=cfg.headers, cookies=cfg.cookie_dict, timeout=120, stream=True)
    resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    try:
        dl = 0
        for chunk in resp.iter_content(8192):
            if chunk:
                tmp.write(chunk)
                dl += len(chunk)
                if dl >= 600 * 16000:
                    break
        tmp.close()
        results = transcribe_batch_gpu({bvid: (tmp.name, None)}, device=device)
        return results.get(bvid, "")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def get_gpu_queue_size():
    return _gpu_queue.qsize()


def clear_pool_results():
    with _results_lock:
        _pool_results.clear()

# ═══════════════════════════════════════════
# 分区黑名单 + 种子数据
# ═══════════════════════════════════════════

PARTITION_BLACKLIST = [3, 4, 5, 31, 33, 21, 138, 239]


def is_partition_blacklisted(partition_id: int) -> bool:
    """检查分区是否在黑名单中。"""
    return partition_id in PARTITION_BLACKLIST


def extract_seed_data(taste) -> dict:
    """从用户画像提取种子数据。返回 {followed_mids: [int], seed_bvids: [str]}。"""
    mids = list(taste.followed_mids) if hasattr(taste, 'followed_mids') and taste.followed_mids else []
    bvids = []
    try:
        from bili_tool.storage import Database
        db = Database()
        bvids = db.get_recent_bvids(days=90)
    except Exception:
        pass
    return {"followed_mids": mids, "seed_bvids": bvids}


def merge_pool_results(pool_results: dict) -> list:
    """纯函数：合并多池结果，按score_l3降序排列。"""
    all_candidates = []
    for results in pool_results.values():
        all_candidates.extend(results)
    return sorted(all_candidates, key=lambda c: c.get("score_l3", 0), reverse=True)


def vram_safe_to_transcribe(threshold: float = 0.85, vram_fn=None) -> bool:
    """检查VRAM是否安全可转录。vram_fn用于测试注入。"""
    if vram_fn is None:
        try:
            from bili_tool.gpu_monitor import get_vram_info
            vram_fn = get_vram_info
        except Exception:
            return True  # 无法查询时默认允许
    try:
        info = vram_fn()
        used_ratio = info["used"] / info["total"]
        return used_ratio < threshold
    except Exception:
        return True  # 查询失败不阻塞
