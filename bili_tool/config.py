"""
B站内容发现工具 — 全局配置模块

所有配置从环境变量读取，辅以合理默认值。
缺失关键配置时明确报错，拒绝带病启动。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """配置缺失或无效。"""


@dataclass
class Config:
    """全局配置单例。"""

    # ── 路径 ──────────────────────────────────
    vault_root: Path = field(default_factory=lambda: Path(
        os.environ.get("OBSIDIAN_VAULT_PATH", "") or
        Path.home() / "Documents" / "Obsidian 笔记"
    ))
    note_dir: Path = field(init=False)
    db_path: Path = field(init=False)

    # ── B站认证 ──────────────────────────────
    sessdata: str = field(default_factory=lambda: os.environ.get("BILI_SESSDATA", ""))
    # [IO] 常见 UA，模拟桌面浏览器
    headers: dict = field(default_factory=lambda: {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com",
    })

    # ── 发现策略 ──────────────────────────────
    max_per_strategy: int = 30         # 每策略最多拉多少候选
    search_budget_total: int = 20      # 搜索 API 总调用次数
    exclude_followed: bool = True      # 排除已关注 UP主

    # ── 请求节流 ──────────────────────────────
    request_interval: float = 1.5      # 请求最小间隔（秒）
    request_timeout: int = 15          # 单次请求超时（秒）

    # ── 打分漏斗 ──────────────────────────────
    l1_min_duration: int = 600         # L1 最低时长 10 分钟
    l1_prefer_long: int = 1800         # 偏好阈值 30 分钟以上加分
    l2_sample_secs: int = 600          # L2 字幕采样时长（秒），取前 5 min + 中间 5 min
    l2_score_cutoff: float = 0.4       # L2 不及格线（丢弃）
    l3_score_cutoff: float = 0.3       # L3 不及格线（丢弃，放宽以覆盖无字幕视频）

    # ── 输出 ──────────────────────────────────
    daily_count: int = 10              # 每天推荐数量

    def __post_init__(self) -> None:
        # [C6] 关键配置缺失直接报错
        if not self.sessdata:
            raise ConfigError(
                "缺少 BILI_SESSDATA 环境变量。请设置后重试：\n"
                "  export BILI_SESSDATA='你的SESSDATA值'"
            )

        # [IO] 拼接路径
        self.note_dir = self.vault_root / "笔记" / "AI推荐的视频"
        self.db_path = Path.home() / ".bili_tool" / "bili_tool.db"

        # [IO] 确保目录存在
        self.note_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def template_path(self) -> Path:
        return self.note_dir / "推荐模板.md"

    @property
    def cookie_dict(self) -> dict[str, str]:
        """用于 requests 的 Cookie 字典。"""
        return {"SESSDATA": self.sessdata}


# 模块级单例
_config: Config | None = None


def get_config() -> Config:
    """获取全局配置（惰性初始化）。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
