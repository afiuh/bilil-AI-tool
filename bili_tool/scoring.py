"""
B站内容发现工具 — 三层打分漏斗

L1: 元数据筛（不拉字幕）
    时长 / UP主 / 标题质量 / 收藏播放比
    → 硬过滤 + 基础分

L2: 字幕采样（拉 10min 字幕）
    因果关系密度 / 结构完整性 / 反常识比例 / 信息密度
    → 不及格丢弃

L3: 完整字幕分析（拉全部字幕）
    论证完整性 / 跨域连接深度 / 与口味画像匹配度
    → 最终排序依据
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bili_tool.bili_api import (
    get_subtitle_text,
    is_collection,
    get_random_episode_info,
    transcribe_audio_segment,
)
from bili_tool.config import get_config
from bili_tool.taste import TasteProfile

logger = logging.getLogger(__name__)

# ── 内容类型黑名单 ──────────────────────────
_EXCLUDE_TITLE_PATTERNS = [
    r"纪录片", r"有声书", r"听书", r"电视剧", r"连续剧",
    r"适合\d+[~\-]?\d*岁", r"儿童", r"启蒙", r"宝宝", r"少儿",
    r"睡前", r"催眠", r"白噪音", r"ASMR",
    r"高考", r"应试", r"考试", r"考点", r"真题", r"专升本", r"考研",
]


def score_l1(candidates: list[dict[str, Any]], taste: TasteProfile) -> list[dict[str, Any]]:
    """L1: 元数据打分。过滤 + 基础分。"""
    cfg = get_config()
    survivors = []
    for c in candidates:
        dur = c.get("duration_sec", 0)
        # [C6] 硬过滤：时长太短
        if dur < 60:
            continue

        # [C6] 硬过滤：黑名单
        mid = c.get("up_mid", 0)
        if taste.is_blacklisted(mid):
            continue

        # [C6] 硬过滤：内容类型（纪录片/有声书/电视剧/儿童）
        title = c.get("title", "")
        if any(re.search(p, title) for p in _EXCLUDE_TITLE_PATTERNS):
            continue

        score = _calc_l1_score(c, taste, cfg)
        # L1 只过滤极差（< 0.1），大部分留给 L2 判断
        if score < 0.1:
            continue

        c["score_l1"] = round(score, 3)
        survivors.append(c)

    survivors.sort(key=lambda x: x.get("score_l1", 0), reverse=True)
    logger.info(f"L1: {len(candidates)} → {len(survivors)}")
    return survivors


def _calc_l1_score(c: dict[str, Any], taste: TasteProfile, cfg: Any) -> float:
    """计算 L1 基础分（0-1）。"""
    score = 0.0

    # 时长信号
    dur = c.get("duration_sec", 0)
    if dur >= cfg.l1_prefer_long:
        score += 0.25
    elif dur >= cfg.l1_min_duration:
        score += 0.10

    # UP主信号
    mid = c.get("up_mid", 0)
    up_w = taste.up_weights.get(mid, 0.0)
    score += up_w * 0.30

    # 标题信号
    title = c.get("title", "")
    depth_keywords = ["深度", "解读", "底层逻辑", "真相", "密码", "拆解", "分析", "系统"]
    shallow_keywords = ["笑死", "绝了", "翻车", "卧槽", "震惊", "没想到", "竟然"]
    dw = sum(1 for w in depth_keywords if w in title)
    sw = sum(1 for w in shallow_keywords if w in title)
    score += min(dw * 0.05, 0.15)       # 深度词加分
    score -= min(sw * 0.08, 0.15)       # 肤浅词扣分

    # 收藏播放比
    play = c.get("play_count", 0)
    if play > 1000:
        score += 0.05  # 有一定受众基础
    return max(0.0, min(1.0, score))


def score_l2(candidates: list[dict[str, Any]], taste: TasteProfile) -> list[dict[str, Any]]:
    """L2: 字幕采样打分。拉前5min+中间5min 字幕做骨架分析。"""
    cfg = get_config()
    # L1 → L2 截断，最多处理 30 条（避免字幕拉取太慢）
    candidates = candidates[:30]
    survivors = []
    for c in candidates:
        # 合集处理：随机抽一集
        bvid = c["bvid"]
        if is_collection(bvid):
            ep = get_random_episode_info(bvid)
            if ep:
                # 用单集时长（API 返回0时默认30分钟）
                single_dur = ep["duration_sec"] if ep["duration_sec"] > 0 else 1800
                c["duration_sec"] = single_dur
                c["title"] = f'{c["title"]} [随机抽样: {ep["part"]}]'

        # 字幕提取
        subtitle = get_subtitle_text(bvid)
        if not subtitle:
            # 无字幕 → L1分作为基础，标题分析加分（FunASR 太慢，跳过）
            # 无字幕 → L1分作为基础，标题分析加分
            base = c.get("score_l1", 0.3)
            title = c.get("title", "")
            # 标题深度信号额外加分
            depth_bonus = 0
            deep_words = ["深度", "解读", "底层逻辑", "拆解", "密码", "分析", "系统", "万字"]
            depth_bonus = sum(0.03 for w in deep_words if w in title)
            c["score_l2"] = round(min(base * 0.85 + depth_bonus, 1.0), 3)
            survivors.append(c)
            continue

        # 采样：前 1000 字 + 中间 1000 字
        half = len(subtitle) // 2
        sample = subtitle[:1000] + subtitle[half:half + 1000] if half > 1000 else subtitle

        score = _calc_l2_score(sample, taste)
        if score < cfg.l2_score_cutoff:
            continue  # [C6] 不及格丢弃

        # 存鸡汤指数到候选，供推荐理由生成使用
        c["soup_score"] = round(score_chicken_soup(sample, taste), 3)
        c["score_l2"] = round(score, 3)
        c["subtitle_text"] = subtitle
        survivors.append(c)

    survivors.sort(key=lambda x: x.get("score_l2", 0), reverse=True)
    logger.info(f"L2: {len(candidates)} → {len(survivors)}")
    return survivors


# ── 鸡汤指数检测 ──────────────────────────

def score_chicken_soup(text: str, taste=None) -> float:
    cfg = get_config()
    """检测学术外衣下的鸡汤/情绪按摩内容。阈值触发制，不越线不计分。"""
    text_len = max(len(text), 1)
    paragraphs = [p for p in text.split(chr(10)) if len(p.strip()) > 10]
    para_count = max(len(paragraphs), 1)
    negative = 0.0
    positive = 0.0

    # ① 你字率 — 阈值 0.008
    you_count = len(re.findall(r'你', text))
    you_rate = you_count / text_len
    if you_rate > 0.008:
        excess = min((you_rate - 0.008) / 0.008, 1.0)
        negative += excess * 0.25

    # ② 零出处引用（含话题调节）
    has_book = bool(re.search(r'《.+?》', text))
    has_year = bool(re.search(r'\d{4}年', text))
    has_cite = bool(re.search(
        r'(?<![你我他她它这那的])[一-鿿]{2,4}(?:认为|考证|记载|指出|曾言)',
        text
    ))
    if not (has_book or has_year or has_cite):
        factor = 1.0
        if taste and hasattr(taste, 'topics') and taste.topics:
            top = max(taste.topics, key=taste.topics.get)
            factor = {'历史': 1.0, '社会': 0.9, '影视': 0.8, '哲学': 0.6}.get(top, 1.0)
        negative += factor * 0.35

    # ③ 比喻密度 — 阈值 0.5 个/段
    metaphor_count = len(re.findall(
        r'就像|如同|是一把|是一座|仿佛|好比|像.{1,3}一样|像是|好似|宛若',
        text
    ))
    metaphor_density = metaphor_count / para_count
    if metaphor_density > 0.5:
        excess = (metaphor_density - 0.5) / 0.5
        normalized = min(excess / 3, 1.0)
        negative += normalized * 0.20

    # ④ 高情感词密度 — 阈值 1.0/千字
    emotional_count = len(re.findall(
        r'痛苦|悲伤|温柔|拥抱|感动|温暖|灵魂|信念|勇气|疗愈|滋养',
        text
    ))
    emotional_density = emotional_count / text_len * 1000
    if emotional_density > 1.0:
        excess = min((emotional_density - 1.0) / 1.0, 1.0)
        negative += excess * 0.10

    # ⑤ 结尾模板（最后500字）
    tail = text[-500:] if len(text) > 500 else text
    if re.search(r'愿你|你会发现|真正的.{1,10}是|这就是.{1,10}的|所以.{1,5}请', tail):
        negative += 0.10

    # ── 正向防御 ──
    source_count = (
        len(re.findall(r'《.+?》', text)) +
        len(re.findall(r'\d{4}年', text)) +
        len(re.findall(r'(?<![你我他她它这那的])[一-鿿]{2,4}(?:认为|考证|记载|指出|曾言)', text))
    )
    source_density = min(source_count / text_len * 1000 / 2, 1.0)
    positive += source_density * 0.5

    verifiable = len(re.findall(r'\d+[万亿千百%人元次个]', text))
    verifiable_density = min(verifiable / text_len * 1000 / 2, 1.0)
    positive += verifiable_density * 0.3

    counter_count = len(re.findall(
        r'有人认为.{1,20}但是|争议在于|也有人质疑|反对者|批评者',
        text
    ))
    positive += min(counter_count * 0.5, 1.0) * 0.2

    return max(0.0, min(negative - positive * 0.5, 1.0))

def _calc_l2_score(text: str, taste=None) -> float:
    """基于字幕骨架分析的 L2 分（0-1）。"""
    score = 0.0

    # 因果关系密度
    causal_patterns = [
        r"因为.*所以", r"由于.*因此", r"之所以.*是因为",
        r"本质是", r"关键是", r"根本上", r"底层",
        r"导致", r"从而", r"进而", r"归根结底",
    ]
    causal_count = sum(len(re.findall(p, text)) for p in causal_patterns)
    text_len = max(len(text), 1)
    causal_density = causal_count / text_len * 1000
    score += min(causal_density * 5, 0.25)

    # 结构信号（有分段标记）
    structure_patterns = [
        r"第[一二三四五六七八九十\d]+[、，,\.点节部分]", r"首先", r"其次", r"最后",
        r"总结", r"以上是", r"接下来", r"另一个", r"除了",
    ]
    struct_count = sum(len(re.findall(p, text)) for p in structure_patterns)
    score += min(struct_count * 0.04, 0.20)

    # 反常识/新视角信号
    novelty_patterns = [
        r"大多数人以为", r"实际上", r"真相是", r"表面.*深层",
        r"真正的", r"其实不是", r"并不是", r"很少有人",
    ]
    novelty_count = sum(len(re.findall(p, text)) for p in novelty_patterns)
    score += min(novelty_count * 0.03, 0.15)

    # 信息密度（排除 filler words）
    filler_words = ["就是说", "那么", "对吧", "说白了", "怎么说呢", "实际上"]
    filler_count = sum(text.count(w) for w in filler_words)
    filler_ratio = filler_count / text_len * 100
    density_score = 0.25
    if filler_ratio > 2:   # 话多 → 降分
        density_score = 0.10
    elif filler_ratio > 1:
        density_score = 0.18
    score += density_score

    # 断言密度检查（根据用户画像的 claim_density_min）
    assertion_patterns = [
        r"(证据|数据|统计|调查|研究|文献|史料|档案)",
        r"(例如|比如|举个|案例|例子)",
        r"(具体|实际|真实|确实|确凿)",
        r"(数字|百分比|倍|万人|亿元|年[间代])",
    ]
    assertion_count = sum(len(re.findall(p, text)) for p in assertion_patterns)
    assertion_density = assertion_count / text_len * 1000
    claim_min = taste.get_claim_density_min() if hasattr(taste, 'get_claim_density_min') else 0.5
    if assertion_density < claim_min:
        penalty = min((claim_min - assertion_density) / claim_min * 0.20, 0.20)
        score -= penalty

    # 鸡汤指数检测（阈值触发制）
    cfg = get_config()
    soup = score_chicken_soup(text, taste)
    if soup > cfg.soup_threshold:
        soup_penalty = cfg.soup_penalty_base + (soup - cfg.soup_threshold) * cfg.soup_penalty_max
        score -= soup_penalty
        logger.debug(f"鸡汤指数={soup:.2f}，扣分={soup_penalty:.2f}")

    return max(0.0, min(1.0, score))


def score_l3(candidates: list[dict[str, Any]], taste: TasteProfile) -> list[dict[str, Any]]:
    """L3: 完整字幕分析。论证完整性 + 跨域连接 + 口味匹配。"""
    cfg = get_config()
    survivors = []
    for c in candidates:
        subtitle = c.get("subtitle_text", "")
        if not subtitle:
            c["score_l3"] = c.get("score_l2", 0.3) * 0.8
            survivors.append(c)
            continue

        score = _calc_l3_score(subtitle, c, taste)
        if score < cfg.l3_score_cutoff:
            continue

        c["score_l3"] = round(score, 3)
        survivors.append(c)

    survivors.sort(key=lambda x: x.get("score_l3", 0), reverse=True)
    logger.info(f"L3: {len(candidates)} → {len(survivors)}")
    return survivors


def _calc_l3_score(subtitle: str, meta: dict[str, Any], taste: TasteProfile) -> float:
    """L3 综合分（0-1）。"""
    score = 0.0

    # 论证完整性（有开头/主体/结尾结构）
    has_intro = bool(re.search(r"(大家好|欢迎|今天|本期|这期|这集)", subtitle[:200]))
    has_body = len(subtitle) > 500
    has_conclusion = bool(re.search(r"(总结|以上就是|总的来说|回顾|最后|谢谢)", subtitle[-500:]))
    if has_intro:
        score += 0.05
    if has_body:
        score += 0.05
    if has_conclusion:
        score += 0.10

    # 模糊开篇惩罚（根据用户画像的 vague_intro_penalty）
    if hasattr(taste, 'get_vague_intro_penalty') and taste.get_vague_intro_penalty():
        # 检测模糊开篇：开头200字内没有具体论点或断言
        intro_text = subtitle[:200]
        has_specific = bool(re.search(
            r"(证据|数据|例如|比如|具体|实际|案例|数字|%|\d+年|\d+%|\d+万|\d+亿)",
            intro_text
        ))
        if not has_specific:
            # 模糊开篇 → 根据画像偏好降权
            score -= 0.08  # 降权幅度

    # 批判风格评分（根据用户画像的 criticism_tolerance）
    if hasattr(taste, 'get_criticism_tolerance'):
        tol = taste.get_criticism_tolerance()
        if tol == 'factual_only':
            # 检测情绪化批判词
            emotional_critique = sum(1 for w in [
                "垃圾", "恶心", "傻逼", "脑残", "废物", "搞笑的吧",
                "笑死", "无语", "离谱他妈", "什么鬼", "太扯了"
            ] if w in subtitle[:1000])
            if emotional_critique >= 2:
                score -= 0.12  # 情绪化批判 → 降权
            # 奖励基于事实的批判
            factual_critique = sum(1 for w in [
                "事实上", "实际上", "数据", "证据", "史料",
                "根据", "来源", "出处", "原文", "考证"
            ] if w in subtitle[:1000])
            if factual_critique >= 3:
                score += 0.08  # 事实驱动批判 → 加分

    # 跨域连接深度
    cross_patterns = [
        r"(就像|好比|跟.*一样|类似于)", r"(放到今天|放在现在|跟现代)",
        r"(原理|模型|框架|规律|范式)", r"(推及|延展|套用)",
    ]
    cross_count = sum(len(re.findall(p, subtitle)) for p in cross_patterns)
    score += min(cross_count * 0.02, 0.20)

    # 论证深度（关联词密度升级）  
    deep_patterns = [
        r"(核心|关键在于|本质上|底层逻辑|根源|机制)",
        r"(反过来|反过来说|但是如果|然而|不过)",
    ]
    deep_count = sum(len(re.findall(p, subtitle)) for p in deep_patterns)
    text_len = max(len(subtitle), 1)
    score += min(deep_count / text_len * 500, 0.15)

    # 时长加分（长视频 → 加分）
    dur = meta.get("duration_sec", 0)
    if dur > 3600:
        score += 0.15
    elif dur > 1800:
        score += 0.10
    elif dur > 600:
        score += 0.05

    # UP主匹配加分（非已关注UP主的额外好感）
    mid = meta.get("up_mid", 0)
    score += taste.up_weights.get(mid, 0.0) * 0.15
    return max(0.0, min(1.0, score))

# ── GPU 批量转录 + 打分 ─────────────────────

def score_l2_gpu(candidates, taste):
    """L2 GPU 版：批量下载音频 → GPU 转录 → 打分"""
    from bili_tool.bili_api import get_audio_url, transcribe_batch_gpu
    import tempfile, os, requests
    from bili_tool.config import get_config
    cfg = get_config()

    candidates = candidates[:30]
    # 收集需要转录的（无 CC 字幕的）
    to_transcribe = {}
    for c in candidates:
        bvid = c["bvid"]
        sub = get_subtitle_text(bvid)
        if sub:
            c["subtitle_text"] = sub
            continue
        # 下载音频到临时文件
        audio_url = get_audio_url(bvid)
        if not audio_url:
            continue
        try:
            resp = requests.get(audio_url, headers=cfg.headers,
                cookies=cfg.cookie_dict, timeout=60, stream=True)
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
            downloaded = 0
            for chunk in resp.iter_content(8192):
                if chunk:
                    tmp.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= 300 * 16000:  # 5分钟音频
                        break
            tmp.close()
            to_transcribe[bvid] = (tmp.name, None)
        except Exception:
            continue

    # GPU 批量转录
    if to_transcribe:
        logger.info(f"GPU 批量转录: {len(to_transcribe)} 条")
        results = transcribe_batch_gpu(to_transcribe)
        for bvid, text in results.items():
            for c in candidates:
                if c["bvid"] == bvid:
                    if text:
                        c["subtitle_text"] = text
                        c["_gpu_transcribed"] = True

    # 逐个打分
    survivors = []
    for c in candidates:
        subtitle = c.get("subtitle_text", "")
        if subtitle:
            score = _calc_l2_score(subtitle[:2000] if len(subtitle) > 2000 else subtitle, taste)
            if score >= cfg.l2_score_cutoff:
                c["soup_score"] = round(score_chicken_soup(
                    subtitle[:2000] if len(subtitle) > 2000 else subtitle, taste
                ), 3)
                c["score_l2"] = round(score, 3)
                survivors.append(c)
            continue
        # 无字幕 → 降分
        base = c.get("score_l1", 0.3)
        title = c.get("title", "")
        depth_bonus = sum(0.03 for w in ["深度","解读","底层逻辑","拆解","分析"] if w in title)
        c["score_l2"] = round(min(base * 0.85 + depth_bonus, 1.0), 3)
        survivors.append(c)

    survivors.sort(key=lambda x: x.get("score_l2", 0), reverse=True)
    logger.info(f"L2(GPU): {len(candidates)} → {len(survivors)}")
    return survivors

# ── 自动选择 ────────────────────────────────

def _is_gpu_available():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False

# 导出统一的 score_l2（自动选 GPU/CPU）
score_l2_auto = score_l2_gpu if _is_gpu_available() else score_l2


def score_single(bvid: str, taste=None) -> dict[str, Any] | None:
    """对单个视频跑通L1+L2+L3，调试专用。"""
    from bili_tool.bili_api import get_video_info, get_subtitle_text
    info = get_video_info(bvid)
    if not info:
        return None
    candidate = {
        "bvid": bvid,
        "title": info.get("title", ""),
        "up_mid": info.get("owner", {}).get("mid", 0),
        "up_name": info.get("owner", {}).get("name", ""),
        "duration_sec": info.get("duration", 0),
        "play_count": info.get("stat", {}).get("view", 0),
        "partition": info.get("tname", ""),
    }
    candidates = score_l1([candidate], taste)
    if not candidates:
        return candidate
    candidates = score_l2(candidates, taste)
    if not candidates:
        return candidate
    candidates = score_l3(candidates, taste)
    return candidates[0] if candidates else candidate
