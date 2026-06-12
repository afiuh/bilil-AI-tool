"""管道编排。薄层，调其他模块串联完整流程。人用和AI用都可以。"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from bili_tool._cp_pause import checkpoint_pause
from bili_tool._review import run_review

logger = logging.getLogger(__name__)


def run_daily(
    taste,     # TasteProfile
    db,        # Database
    api_key: str,
    note_dir: Path,
    limit: int = 10,
) -> str | None:
    """完整每日管道。返回笔记路径，无法生成返回None。"""
    from bili_tool.discovery import discover_all
    from bili_tool.scoring import score_l1, score_l2_auto, score_l3
    from bili_tool.curator import curate
    from bili_tool.analyzer import post_analyze_note
    from bili_tool.notes import write_recommendations
    from datetime import date, datetime

    from datetime import date, datetime
    from bili_tool.cache import save, load, get_latest_stage, cleanup
    run_id = datetime.now().strftime("%Y-%m-%d-%H")
    latest = get_latest_stage(run_id)

    # 连通性检查
    if not _check_connectivity():
        logger.error("B站 API 连通性检查失败，SESSDATA 可能已过期")
        return None

    from bili_tool.bootstrap import ensure_fresh
    ensure_fresh()

    if latest:
        logger.info(f"=== 管道恢复（从缓存 {latest}） ===")
    logger.info("=== 管道启动 ===")

    # ① 发现
    if latest and latest >= "01_discovery":
        candidates = load("01_discovery", run_id) or discover_all(taste)
    else:
        candidates = discover_all(taste)
        save("01_discovery", candidates, run_id)

    if not candidates:
        logger.warning("发现阶段无结果")
        return None

    # [检查点1] 话题分布
    from bili_tool.checkpoint import check_discovery
    cp1 = check_discovery(candidates)
    checkpoint_pause(1, cp1)

    # ② 打分
    if latest and latest >= "02_l1":
        candidates = load("02_l1", run_id) or score_l1(candidates, taste)
    else:
        candidates = score_l1(candidates, taste)
        save("02_l1", candidates, run_id)

    if latest and latest >= "03_l2":
        candidates = load("03_l2", run_id) or score_l2_auto(candidates, taste)
    else:
        candidates = score_l2_auto(candidates, taste)
        save("03_l2", candidates, run_id)
    if latest and latest >= "04_l3":
        candidates = load("04_l3", run_id) or score_l3(candidates, taste)
    else:
        candidates = score_l3(candidates, taste)
        save("04_l3", candidates, run_id)

    if not candidates:
        logger.warning("打分后无幸存者")
        return None

    # [检查点2] 打分分布
    from bili_tool.checkpoint import check_scoring
    cp2 = check_scoring(candidates)
    checkpoint_pause(2, cp2)

    # ③ 策展
    candidates = curate(candidates, db, limit=limit)
    save("05_curated", candidates, run_id)

    # 写入笔记（分析字段暂为空，后续精校填充）
    today = datetime.now().strftime("%Y-%m-%d-%H")
    note_path = write_recommendations(candidates, taste, today, note_dir)

    # 记录推荐历史
    for c in candidates:
        db.mark_recommended(c["bvid"], note_path)

    # LLM精校
    if api_key:
        updated = post_analyze_note(note_path, api_key)
        logger.info(f"精校完成: {updated} 条")
    else:
        logger.warning("未设置 DEEPSEEK_API_KEY，跳过精校")

    # [检查点3] 笔记质量
    from bili_tool.checkpoint import check_output
    cp3 = check_output(note_path)
    checkpoint_pause(3, cp3)

    # 清理缓存
    cleanup(run_id)

    logger.info(f"✅ 管道完成: {note_path}")
    return note_path


def run_discovery_only(taste) -> list[dict[str, Any]]:
    """只跑发现阶段。"""
    from bili_tool.discovery import discover_all
    return discover_all(taste)


def run_scoring_only(
    candidates: list[dict[str, Any]],
    taste,
    levels: list[str] | None = None,
) -> list[dict[str, Any]]:
    """只跑打分阶段。levels=None时跑全部三级。"""
    from bili_tool.scoring import score_l1, score_l2_auto, score_l3
    levels = levels or ["l1", "l2", "l3"]
    for lvl in levels:
        if lvl == "l1":
            candidates = score_l1(candidates, taste)
        elif lvl == "l2":
            candidates = score_l2_auto(candidates, taste)
        elif lvl == "l3":
            candidates = score_l3(candidates, taste)
    return candidates


def check_ready(note_dir: Path) -> tuple[bool, str]:
    """检查是否可以生成新推荐。返回(是否就绪, 原因)。"""
    from bili_tool.notes import get_latest_note, count_reviewed
    latest = get_latest_note(note_dir)
    if not latest:
        return True, "无历史笔记"
    total, checked = count_reviewed(str(latest))
    if total == 0:
        return True, "笔记中无已阅标记"
    if checked < total:
        return False, f"{checked}/{total} 已阅，等待用户阅读"
    return True, f"全部已阅 ({checked}/{total})"


def get_status(db, note_dir: Path) -> dict[str, Any]:
    """返回系统状态摘要。"""
    from bili_tool.state import (
        get_candidate_count, get_recommend_history, get_unreviewed_notes
    )
    return {
        "candidates_total": get_candidate_count(db),
        "recommend_history": len(get_recommend_history(db, limit=100)),
        "unreviewed_notes": len(get_unreviewed_notes(note_dir)),
        "latest_note": str(get_latest_note(note_dir)) if get_latest_note(note_dir) else None,
    }


def get_latest_note(note_dir: Path) -> Path | None:
    from bili_tool.notes import get_latest_note as _get
    return _get(note_dir)

    from bili_tool.notes import get_latest_note as _get
    return _get(note_dir)


def _check_connectivity() -> bool:
    """检查 B站 API 连通性，验证 SESSDATA 是否有效。"""
    import requests
    from bili_tool.config import get_config
    cfg = get_config()
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=cfg.headers,
            cookies=cfg.cookie_dict,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                uname = data.get("data", {}).get("uname", "?")
                logger.info(f"B站连通性OK，当前用户: {uname}")
                return True
            elif data.get("code") == -101:
                logger.error("SESSDATA 已过期（code=-101），请更新 .env 中的 BILI_SESSDATA")
                return False
        logger.warning(f"连通性检查异常: HTTP {resp.status_code}")
        return False
    except Exception as e:
        logger.error(f"连通性检查失败: {e}")
        return False

# ═══════════════════════════════════════════
# 5池并行管道（v0.4.0）
# ═══════════════════════════════════════════

def run_daily_5pool(
    taste, db, api_key, note_dir, limit=10
):
    """5池并行管道。5个分区各跑一个池，合并输出。"""
    from datetime import datetime
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from bili_tool.pool import (
        PoolRunner, PARTITION_WHITELIST, PARTITION_KEYWORDS,
        process_gpu_queue, clear_pool_results,
    )
    from bili_tool.notes import write_recommendations
    from bili_tool.curator import rank

    from bili_tool.bootstrap import ensure_fresh
    ensure_fresh()
    logger.info("=== 5池管道启动 ===")

    # ① 随机选5个分区
    import random
    selected = random.sample(PARTITION_WHITELIST, min(5, len(PARTITION_WHITELIST)))
    logger.info("选中分区: %s", selected)

    # ①.5 提取种子数据
    from bili_tool.pool import extract_seed_data
    seeds = extract_seed_data(taste)

    # ② 建5个池，注入种子
    pools = []
    for i, pid in enumerate(selected):
        kw = PARTITION_KEYWORDS.get(pid, ["深度", "解读"])
        runner = PoolRunner(
            pool_id=f"pool{i+1}",
            partition_id=pid,
            keywords=kw,
            taste=taste,
            max_retries=2,
        )
        runner.seed_mids = seeds["followed_mids"]
        runner.seed_bvids = seeds["seed_bvids"]
        pools.append(runner)

    # ③ 启动GPU消费者线程（和池并行跑）
    import threading
    gpu_done = threading.Event()
    def gpu_worker():
        while not gpu_done.is_set():
            from bili_tool.pool import get_gpu_queue_size
            if get_gpu_queue_size() > 0:
                process_gpu_queue()
            gpu_done.wait(1.0)  # 每秒检查一次
    gpu_thread = threading.Thread(target=gpu_worker, daemon=True)
    gpu_thread.start()

    # ④ 并行跑搜索+打分（线程池）
    pool_results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(p.run): p for p in pools}
        for future in as_completed(futures):
            p = futures[future]
            try:
                result = future.result()
                pool_results[p.pool_id] = result
                logger.info("[%s] 产出 %d 条", p.pool_id, len(result))
            except Exception as e:
                logger.error("[%s] 失败: %s", p.pool_id, e)
                pool_results[p.pool_id] = []

    # ⑤ 停止GPU消费者 + 清空剩余队列
    gpu_done.set()
    gpu_thread.join(timeout=5)
    try:
        remaining = process_gpu_queue()
        logger.info("GPU转录完成: %d 条", remaining)
    except Exception as e:
        logger.error("GPU转录阶段崩溃: %s (已有缓存数据保留)", e)
    clear_pool_results()

    # ⑥ 全量转录（L2只采样，L3需要全文）
    full_transcribed = 0
    for pid, results in pool_results.items():
        for c in results:
            if not c.get('subtitle_text') and c.get('_gpu_failed'):
                c['subtitle_text'] = process_gpu_queue(full_length=True)  # 重试全量
                if c.get('subtitle_text'):
                    full_transcribed += 1
    if full_transcribed:
        logger.info('全量转录: %d 条', full_transcribed)

    # ⑦ 合并+排序
    from bili_tool.pool import merge_pool_results
    all_candidates = merge_pool_results(pool_results)

    # ⑥ 检查点：字幕产出+GPU+缓存
    from bili_tool.checkpoint import check_subtitle_production
    cp_sub = check_subtitle_production(all_candidates)
    logger.info("[检查点·字幕] %s", cp_sub['summary'])
    if cp_sub.get('warning'):
        logger.warning("[检查点·字幕] ⚠️ %s", cp_sub['warning'])

    # ⑦ 缓存清理 — 落选的从 video_cache 删除
    from bili_tool.cache import cleanup_non_selected
    selected_bvids = [x["bvid"] for x in all_candidates]
    cleanup_non_selected(selected_bvids)

    if not all_candidates:
        logger.warning("5池全部空产")
        return None

    ranked = all_candidates  # merge_pool_results 已排序
    final = ranked[:limit]

    # ⑧ 写笔记+精校
    from datetime import date
    today = datetime.now().strftime("%Y-%m-%d-%H")
    note_path = write_recommendations(final, taste, today, note_dir)

    for c in final:
        db.mark_recommended(c["bvid"], note_path)

    if api_key:
        from bili_tool.analyzer import post_analyze_note
        updated = post_analyze_note(note_path, api_key)
        logger.info("精校: %d 条", updated)

        # [检查点] 精校后 — 翻看笔记
        from bili_tool.checkpoint import check_final_note
        cp_note = check_final_note(note_path)
        logger.info("[检查点·笔记] %s", cp_note['summary'])
        if cp_note.get('warning'):
            logger.warning("[检查点·笔记] ⚠️ 错误日志已写入笔记末尾")

    # 检查点
    from bili_tool.checkpoint import check_output
    from bili_tool._cp_pause import checkpoint_pause
    cp = check_output(note_path)
    checkpoint_pause(3, cp)

    topic_dist = {}
    for c in final:
        p = c.get("partition", "其他")
        topic_dist[p] = topic_dist.get(p, 0) + 1
    logger.info("产出: %d条, 分区: %s", len(final), topic_dist)
    logger.info("管道完成: %s", note_path)
    return note_path
