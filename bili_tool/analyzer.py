"""
B站内容发现工具 — LLM 精校分析模块

用 DeepSeek API 对视频字幕做：
  1. 精校文本（标点、分段、修正转写错误）
  2. 逐段批注（💡亮点 / ⚠️不足）
  3. 总结分析
  4. 每段留 💬 反馈空位
"""

import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

# [IO] DeepSeek API 配置
API_URL = "https://api.deepseek.com/chat/completions"

SYSTEM_PROMPT = """你是一个内容分析助手。给你一段B站视频的字幕（无标点无分段），请完成：

1. **精校文本**：加标点、按语义分段、修正明显转写错误（如"沈沛→审配"）。
   分段规则（按意思切，不按字数切）：
   - 一个完整意思 = 一个自然段。说完一个论点，换段说下一个论点
   - 意思转折（但是/然而/另一方面/反过来说）→ 必须分段
   - 话题切换（换了一个新话题）→ 必须分段
   - 举例/论证/引用 → 与主体论述分开，单独成段
   - 对话/引语 → 单独成段
   - 每段配一个概括性的段落标题（简洁扼要）
   - 红线：绝对不允许省略任何原文内容。字数多就多分段，不能删减
2. **逐段批注**：每段后标注，必须指向具体内容，禁止泛泛而谈。
   - 💡 亮点：指出具体的论证技巧/知识增量/反常识观点，并说明为什么值得关注。
     错误示例："💡 生动形象，讲解清晰" ← 禁止！
     正确示例："💡 用'藩王-官僚'二元框架解释洪武政治清洗，而非泛泛归因于个人性格，这在洪武研究中是较少见的制度视角"
   - ⚠️ 不足：指出具体的论证漏洞/可疑论断/信息缺失，并说明其影响。
     错误示例："⚠️ 有些地方不够严谨" ← 禁止！
     正确示例："⚠️ 声称'明代宦官从未掌权'与《明史·宦官传》记载相悖，未提供反证，结论可靠性存疑"
3. **总结分析**：
   - 核心框架（一句话）
   - 亮点（3-5条）
   - 不足（3-5条）

输出格式（严格按此模板）：

【第一段：段落标题】
精校后的文本（一个完整的意思）...

> 💡 批注内容（你的分析）
> 💬 你的看法：（留空！这是给用户填的，你只写 💬 你的看法： 后面什么都不写）

【第二段：段落标题】
精校后的文本...

> ⚠️ 批注内容
> 💬 你的看法：

### 🔍 总结分析
**核心框架**：...
**亮点**：...
**不足**：...

要求：
- 覆盖全部原文，绝对不允许省略任何内容——这是红线
- 按语义分段：一个意思一段，不要挤在一起
- 段落标题概括该段核心观点
- 意思转折、话题切换、举例论证处必须分段
- 如果原文有逻辑不通处，微调使其通顺，但不改变原意
"""


def analyze_subtitle(
    subtitle: str,
    api_key: str,
    video_title: str = "",
    max_tokens: int = 8192,
) -> str:
    """[IO] 调用 DeepSeek API 对字幕做精校分析。"""
    if not subtitle or len(subtitle) < 50:
        return "（该视频无字幕或字幕过短，无法分析）"

    # 截断超长字幕（API 上下文限制）
    if len(subtitle) > 12000:
        subtitle = subtitle[:12000]

    user_prompt = f"视频标题：{video_title}\n\n原始字幕（无标点）：\n{subtitle}"

    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        finish_reason = data["choices"][0].get("finish_reason", "")
        if finish_reason == "length":
            logger.warning(f"[TRUNCATED] max_tokens={max_tokens} 截断, 字幕{len(subtitle)}字")
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        logger.error(f"LLM 分析失败: {e}")
        return f"（分析失败: {e}）"


def analyze_subtitle_split(
    subtitle: str,
    api_key: str,
    video_title: str = "",
) -> str:
    """长字幕分段精校：正文+批注一调，总结分析一调，避免截断。"""
    if not subtitle or len(subtitle) < 50:
        return "（该视频无字幕或字幕过短，无法分析）"
    if len(subtitle) > 12000:
        subtitle = subtitle[:12000]

    NL = chr(10)
    body_prompt = NL.join([
        f"视频标题：{video_title}",
        "",
        "原始字幕（无标点）：",
        subtitle,
        "",
        "请只输出【精校文本】+【逐段批注】部分，不要输出总结分析。",
    ])
    summary_prompt = NL.join([
        f"视频标题：{video_title}",
        "",
        f"该视频字幕共 {len(subtitle)} 字，请基于此输出【总结分析】部分：",
        "1. 核心框架（一句话）",
        "2. 亮点（3-5条）",
        "3. 不足（3-5条）",
        "4. 总体评分和推荐建议",
    ])

    result_parts = []
    for label, prompt in [("body", body_prompt), ("summary", summary_prompt)]:
        try:
            resp = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 8192,
                    "temperature": 0.3,
                },
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
            finish_reason = data["choices"][0].get("finish_reason", "")
            if finish_reason == "length":
                logger.warning(
                    f"[TRUNCATED] 视频《{video_title}》{label}阶段被截断 (finish_reason=length)"
                )
            result_parts.append(data["choices"][0]["message"]["content"])
        except Exception as e:
            logger.error(f"LLM 分析失败 ({label}): {e}")
            result_parts.append(f"（{label} 分析失败: {e}）")

    return NL.join(result_parts)


def post_analyze_note(note_path: str, api_key: str) -> int:
    """[IO] 读取笔记，对有字幕的视频逐条精校，更新笔记。

    返回处理的视频数。
    """
    content = open(note_path, encoding="utf-8").read()

    # 按视频分段
    sections = re.split(r"(\n## \d+\. )", content)
    # sections: [header, "## 1.", video1, "## 2.", video2, ...]

    updated = 0
    new_parts = [sections[0]]  # header

    for i in range(1, len(sections), 2):
        if i + 1 >= len(sections):
            break
        marker = sections[i]      # "## 1. "
        body = sections[i + 1]    # everything after

        # 提取标题
        title_match = re.search(r"(.+?)\n", body)
        title = title_match.group(1).strip() if title_match else ""

        # 跳过已有完整逐段精校的（不是批量概述）
        has_detailed = re.search(r"【第[一二三四五六七八九十\d]+段", body)
        if has_detailed:
            new_parts.append(marker)
            new_parts.append(body)
            continue

        # 找原始字幕
        sub_match = re.search(r"```text\n(.+?)\n```", body, re.DOTALL)
        if not sub_match:
            new_parts.append(marker)
            new_parts.append(body)
            continue

        subtitle = sub_match.group(1)
        logger.info(f"正在分析: {title[:40]} ({len(subtitle)} 字)")

        # [IO] 调 LLM
        if len(subtitle) > 6000:
            logger.info(f"视频「{title}」字幕{len(subtitle)}字，使用分段精校")
            analysis = analyze_subtitle_split(subtitle, api_key, title)
        else:
            analysis = analyze_subtitle(subtitle, api_key, title)

        # 替换占位符 + 移除原始字幕块
        old_placeholder = "### 🤖 Hermes 逐段分析\n<!-- 待 Hermes 分析后填充 -->\n> ⏳ 待分析..."
        old_subtitle_block = re.search(
            r"### 📜 完整字幕.*?\n```text\n.*?\n```\n\n", body, re.DOTALL
        )

        if old_placeholder in body:
            body = body.replace(old_placeholder, f"### 📜 精校文本与批注\n\n{analysis}\n")
            updated += 1

        if old_subtitle_block:
            body = body.replace(old_subtitle_block.group(0), "")

        new_parts.append(marker)
        new_parts.append(body)
        # 增量保存
        open(note_path, "w", encoding="utf-8").write("".join(new_parts[1:] if not new_parts[0].strip() else new_parts))

    open(note_path, "w", encoding="utf-8").write("".join(new_parts))
    logger.info(f"精校完成: {updated} 条视频")
    return updated


def analyze_batch(
    candidates: list[dict[str, Any]],
    api_key: str,
) -> list[dict[str, Any]]:
    """批量精校。自动判断字幕长短选择单次或分段API调用。"""
    for c in candidates:
        subtitle = c.get("subtitle_text", "")
        title = c.get("title", "")
        if not subtitle or len(subtitle) < 50:
            c["analysis"] = "（无字幕或字幕过短）"
            continue
        try:
            if len(subtitle) > 6000:
                c["analysis"] = analyze_subtitle_split(subtitle, api_key, title)
            else:
                c["analysis"] = analyze_subtitle(subtitle, api_key, title)
        except Exception as e:
            logger.error(f"批量精校失败 [{title}]: {e}")
            c["analysis"] = f"（分析失败: {e}）"
    return candidates
