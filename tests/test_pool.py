"""pool.py 单元测试 — TDD RED-GREEN-REFACTOR"""

import pytest
import queue
import threading
from unittest.mock import patch, MagicMock

# ═══════════════════════════════════════════
# PoolRunner 基础测试
# ═══════════════════════════════════════════

class TestPoolRunnerInit:
    """初始化测试"""

    def test_init_sets_attributes(self):
        """初始化应正确设置所有属性"""
        from bili_tool.pool import PoolRunner
        taste = MagicMock()
        runner = PoolRunner("pool1", 207, ["历史", "朝代"], taste, max_retries=2)

        assert runner.pool_id == "pool1"
        assert runner.partition_id == 207
        assert runner.keywords == ["历史", "朝代"]
        assert runner.taste is taste
        assert runner.max_retries == 2
        assert runner._retries_left == 2
        assert runner._seen_bvids == set()
        assert runner._sort_idx == 0
        assert runner._page == 1

    def test_init_default_retries(self):
        """默认重试次数为3"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        assert runner.max_retries == 3
        assert runner._retries_left == 3


class TestRotateStrategy:
    """重试策略切换测试"""

    def test_rotate_increments_sort_idx(self):
        """切换策略应增加排序索引"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        assert runner._sort_idx == 0
        runner._rotate_strategy()
        assert runner._sort_idx == 1

    def test_rotate_wraps_to_next_page(self):
        """排序方式轮完一圈后翻页"""
        from bili_tool.pool import PoolRunner, SEARCH_SORTS
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        # 翻到第(len(SORTS)*2)次
        for _ in range(len(SEARCH_SORTS) * 2):
            runner._rotate_strategy()
        assert runner._page == 2
        assert runner._sort_idx == 0


class TestIsSatisfied:
    """达标检查测试"""

    def test_not_satisfied_when_less_than_2(self):
        """少于2条候选不达标"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        candidates = [{"score_l3": 0.5, "soup_score": 0.1}]
        assert not runner._is_satisfied(candidates)

    def test_not_satisfied_when_avg_low(self):
        """均分低于0.3不达标"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        candidates = [
            {"score_l3": 0.2, "soup_score": 0.1},
            {"score_l3": 0.2, "soup_score": 0.1},
        ]
        assert not runner._is_satisfied(candidates)

    def test_not_satisfied_when_all_soup(self):
        """全鸡汤不达标"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        candidates = [
            {"score_l3": 0.5, "soup_score": 0.9},
            {"score_l3": 0.5, "soup_score": 0.9},
        ]
        assert not runner._is_satisfied(candidates)

    def test_satisfied_when_good(self):
        """正常候选达标"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        candidates = [
            {"score_l3": 0.5, "soup_score": 0.1},
            {"score_l3": 0.5, "soup_score": 0.2},
            {"score_l3": 0.5, "soup_score": 0.1},
        ]
        assert runner._is_satisfied(candidates)


class TestSelectTop:
    """池内策展测试"""

    def test_select_top_returns_limit(self):
        """返回不超过N条"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        candidates = [
            {"bvid": f"BV{i}", "score_l3": 0.5 - i * 0.1}
            for i in range(5)
        ]
        result = runner._select_top(candidates, n=2)
        assert len(result) == 2

    def test_select_top_sorted_by_score(self):
        """按分数降序排列"""
        from bili_tool.pool import PoolRunner
        runner = PoolRunner("p1", 207, ["测试"], MagicMock())
        candidates = [
            {"bvid": "BV1", "score_l3": 0.3},
            {"bvid": "BV2", "score_l3": 0.8},
            {"bvid": "BV3", "score_l3": 0.5},
        ]
        result = runner._select_top(candidates, n=3)
        assert result[0]["score_l3"] == 0.8
        assert result[2]["score_l3"] == 0.3


# ═══════════════════════════════════════════
# GPU 队列测试
# ═══════════════════════════════════════════

class TestGpuQueue:
    """全局GPU队列测试"""

    def test_queue_put_get(self):
        """队列基本操作"""
        from bili_tool.pool import _gpu_queue
        # 清空
        while not _gpu_queue.empty():
            _gpu_queue.get()

        _gpu_queue.put({"pool_id": "pool1", "bvid": "BVtest", "audio_url": "http://x"})
        assert _gpu_queue.qsize() == 1
        task = _gpu_queue.get()
        assert task["pool_id"] == "pool1"
        assert task["bvid"] == "BVtest"

    def test_get_gpu_queue_size(self):
        """队列大小查询"""
        from bili_tool.pool import get_gpu_queue_size, _gpu_queue
        while not _gpu_queue.empty():
            _gpu_queue.get()
        assert get_gpu_queue_size() == 0
        _gpu_queue.put({"pool_id": "p", "bvid": "BV", "audio_url": "x"})
        assert get_gpu_queue_size() == 1
        _gpu_queue.get()

    def test_clear_pool_results(self):
        """清理转录结果"""
        from bili_tool.pool import _pool_results, _results_lock, clear_pool_results
        with _results_lock:
            _pool_results["pool1"] = {"BV1": "text"}
        assert "pool1" in _pool_results
        clear_pool_results()
        assert len(_pool_results) == 0


# ═══════════════════════════════════════════
# 分区配置测试
# ═══════════════════════════════════════════

class TestPartitionConfig:
    """分区配置测试"""

    def test_whitelist_has_6_entries(self):
        """分区白名单应有6个入口"""
        from bili_tool.pool import PARTITION_WHITELIST
        assert len(PARTITION_WHITELIST) == 6

    def test_keywords_match_partitions(self):
        """每个白名单分区都有关键词"""
        from bili_tool.pool import PARTITION_WHITELIST, PARTITION_KEYWORDS
        for pid in PARTITION_WHITELIST:
            assert pid in PARTITION_KEYWORDS, f"分区{pid}缺少关键词"
            assert len(PARTITION_KEYWORDS[pid]) >= 2, f"分区{pid}关键词少于2个"

    def test_sort_modes_are_strings(self):
        """排序方式全是字符串"""
        from bili_tool.pool import SEARCH_SORTS
        assert len(SEARCH_SORTS) >= 2
        for s in SEARCH_SORTS:
            assert isinstance(s, str)


# ═══════════════════════════════════════════
# 种子数据测试（RED — 功能待实现）
# ═══════════════════════════════════════════

class TestSeedData:
    """种子数据提取测试"""

    def test_extract_followed_mids_returns_list(self):
        """从taste画像提取关注的UP主mid列表"""
        from bili_tool.pool import extract_seed_data
        taste = MagicMock()
        taste.followed_mids = {123, 456, 789}

        seeds = extract_seed_data(taste)
        assert "followed_mids" in seeds
        assert len(seeds["followed_mids"]) == 3
        assert 123 in seeds["followed_mids"]

    def test_extract_seed_data_empty_collections(self):
        """无收藏夹时不报错"""
        from bili_tool.pool import extract_seed_data
        taste = MagicMock()
        taste.followed_mids = set()
        seeds = extract_seed_data(taste)
        assert seeds["followed_mids"] == []
        assert seeds["seed_bvids"] == []

    def test_extract_seed_data_returns_both_keys(self):
        """返回字典包含两个必需key"""
        from bili_tool.pool import extract_seed_data
        taste = MagicMock()
        taste.followed_mids = {1}
        seeds = extract_seed_data(taste)
        assert "followed_mids" in seeds
        assert "seed_bvids" in seeds


class TestPartitionBlacklist:
    """分区黑名单过滤测试"""

    def test_is_blacklisted_music(self):
        """音乐分区被黑名单拦截"""
        from bili_tool.pool import is_partition_blacklisted, PARTITION_BLACKLIST
        # 3=音乐
        assert is_partition_blacklisted(3)

    def test_is_not_blacklisted_history(self):
        """人文历史不在黑名单"""
        from bili_tool.pool import is_partition_blacklisted
        assert not is_partition_blacklisted(207)

    def test_blacklist_not_empty(self):
        """黑名单不为空"""
        from bili_tool.pool import PARTITION_BLACKLIST
        assert len(PARTITION_BLACKLIST) > 0


class TestMergeResults:
    """合并池结果测试"""

    def test_merge_sorts_by_score(self):
        """合并后按score_l3降序"""
        from bili_tool.pool import merge_pool_results
        pool_results = {
            "pool1": [{"bvid": "BV1", "score_l3": 0.3}],
            "pool2": [{"bvid": "BV2", "score_l3": 0.8}],
            "pool3": [{"bvid": "BV3", "score_l3": 0.5}],
        }
        merged = merge_pool_results(pool_results)
        assert merged[0]["score_l3"] == 0.8
        assert merged[2]["score_l3"] == 0.3

    def test_merge_handles_empty_pool(self):
        """某池空产不影响合并"""
        from bili_tool.pool import merge_pool_results
        pool_results = {
            "pool1": [{"bvid": "BV1", "score_l3": 0.5}],
            "pool2": [],
        }
        merged = merge_pool_results(pool_results)
        assert len(merged) == 1

    def test_merge_all_empty_returns_empty(self):
        """全空返回空列表"""
        from bili_tool.pool import merge_pool_results
        assert merge_pool_results({"p1": [], "p2": []}) == []

    def test_merge_preserves_all_bvids(self):
        """不丢数据"""
        from bili_tool.pool import merge_pool_results
        pool_results = {
            "p1": [{"bvid": f"BV{i}", "score_l3": 0.5} for i in range(3)],
            "p2": [{"bvid": f"BV{i+10}", "score_l3": 0.5} for i in range(2)],
        }
        merged = merge_pool_results(pool_results)
        assert len(merged) == 5
