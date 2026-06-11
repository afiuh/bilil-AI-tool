"""bili_tool — B站高质量内容自动化发现与推荐系统。

去中心化工具箱架构：每个模块可独立调用，AI自由组合。
一键管道见 pipeline.py。
"""

__version__ = "0.3.0"

# 核心类
from bili_tool.taste import TasteProfile
from bili_tool.storage import Database
from bili_tool.config import get_config

# 一键管道
from bili_tool.pipeline import (
    run_daily,
    run_discovery_only,
    run_scoring_only,
    check_ready,
    get_status,
)

# 各模块独立函数
from bili_tool.discovery import (
    discover,
    discover_all,
    discover_by_search,
    discover_by_partition,
    discover_by_following,
)
from bili_tool.scoring import (
    score_l1,
    score_l2,
    score_l3,
    score_single,
    score_chicken_soup,
)
from bili_tool.curator import (
    curate,
    deduplicate,
    rank,
    enforce_diversity,
)
from bili_tool.analyzer import (
    analyze_subtitle,
    analyze_subtitle_split,
    analyze_batch,
    post_analyze_note,
)
from bili_tool.feedback import (
    scan_feedback_notes,
    _classify_feedback,
    _is_reviewed,
    _is_communicated,
)
from bili_tool.notes import (
    write_recommendations,
    mark_reviewed,
    mark_communicated,
    get_latest_note,
    count_reviewed,
)
from bili_tool.state import (
    get_candidate_count,
    get_recommend_history,
    get_unreviewed_notes,
    get_stats,
)
from bili_tool.transcribe import (
    get_subtitle_text,
    transcribe_single,
    transcribe_batch_gpu,
)
