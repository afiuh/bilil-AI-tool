"""bootstrap.py 测试 — 验证拉起的是最新代码"""
import sys
import time
from pathlib import Path
from unittest.mock import patch


class TestEnsureFresh:
    """ensure_fresh() 核心行为测试"""

    def test_returns_dict_with_keys(self):
        """返回值包含必需key"""
        from bili_tool.bootstrap import ensure_fresh
        result = ensure_fresh()
        assert "pyc_cleaned" in result
        assert "modules_unloaded" in result
        assert isinstance(result["pyc_cleaned"], int)
        assert isinstance(result["modules_unloaded"], list)

    def test_unloads_bili_modules(self):
        """确实卸载了 bili_tool.* 模块"""
        import bili_tool.pool
        import bili_tool.scoring
        assert "bili_tool.pool" in sys.modules

        from bili_tool.bootstrap import ensure_fresh
        ensure_fresh()

        assert "bili_tool.pool" not in sys.modules
        assert "bili_tool.scoring" not in sys.modules

    def test_reimport_loads_fresh(self):
        """卸载后重新导入，函数存在且可用"""
        from bili_tool.bootstrap import ensure_fresh
        ensure_fresh()

        import bili_tool.pool
        import bili_tool.scoring
        import bili_tool.curator

        from bili_tool.pool import PoolRunner, merge_pool_results
        from bili_tool.scoring import score_chicken_soup
        from bili_tool.curator import rank

        assert PoolRunner is not None
        assert merge_pool_results is not None
        assert score_chicken_soup is not None
        assert rank is not None

    def test_idempotent(self):
        """连续两次调用不报错"""
        from bili_tool.bootstrap import ensure_fresh
        ensure_fresh()
        ensure_fresh()  # 不应报错

    def test_pyc_actually_deleted(self):
        """pycache 文件确实被删除了"""
        import tempfile, os
        from bili_tool.bootstrap import ensure_fresh

        # 制造一个假 pyc 文件在 bili_tool 目录下
        pyc_dir = Path(__file__).parent.parent / "bili_tool" / "__pycache__"
        pyc_dir.mkdir(exist_ok=True)
        test_pyc = pyc_dir / "test_fake.cpython-312.pyc"
        test_pyc.write_text("fake")
        assert test_pyc.exists()

        ensure_fresh()

        assert not test_pyc.exists(), f"pyc file still exists: {test_pyc}"


class TestBootstrapPipeline:
    """bootstrap + pipeline 联动测试"""

    def test_pipeline_imports_after_bootstrap(self):
        """bootstrap后 pipeline 能正常加载"""
        from bili_tool.bootstrap import ensure_fresh
        ensure_fresh()

        from bili_tool.pipeline import run_daily, run_daily_5pool
        assert run_daily is not None
        assert run_daily_5pool is not None

    def test_all_modules_reimportable(self):
        """全部模块都能在 bootstrap 后重新导入"""
        from bili_tool.bootstrap import ensure_fresh
        ensure_fresh()

        modules = [
            "bili_tool.config",
            "bili_tool.taste",
            "bili_tool.storage",
            "bili_tool.pool",
            "bili_tool.scoring",
            "bili_tool.curator",
            "bili_tool.analyzer",
            "bili_tool.feedback",
            "bili_tool.notes",
            "bili_tool.state",
            "bili_tool.transcribe",
            "bili_tool.checkpoint",
            "bili_tool.pipeline",
            "bili_tool.cache",
        ]
        for mod_name in modules:
            __import__(mod_name)
        # 全部导入成功即通过
