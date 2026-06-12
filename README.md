# bilil-AI-tool

**B站高质量内容自动化发现与推荐系统** — AI 驱动的端到端管道，从视频发现到精校笔记全自动。

## 它能做什么

每天运行，自动帮你：

1. **发现候选视频** — 从关注链、B站推荐、关键词搜索、分区热门中，四策略并行挖掘
2. **三层漏斗筛选** — L1 元数据硬过滤 → L2 字幕采样分析 → L3 LLM 深度评估，层层淘汰
3. **GPU 转录无字幕视频** — FunASR paraformer-zh 模型，转录无 CC 字幕的中文视频
4. **LLM 逐段精校** — DeepSeek API 修正转录错误、补全标点、逐段批注
5. **写入 Obsidian 笔记** — 结构化笔记，含基本信息表、精校文本、批注、建议
6. **反馈闭环进化** — 解析你的批注，自动调整推荐画像

## 管道架构

```
发现引擎 (四策略并行)
  → L1 元数据过滤 (时长/类型/已关注UP主)
  → L2 字幕采样 (CC字幕 + GPU转录) + 内容类型硬过滤
  → L3 LLM 深度分析 (DeepSeek 逐段精校 + 💡⚠️ 批注)
  → 策展去重排序
  → 写入 Obsidian 笔记
  → 用户反馈闭环 → 画像权重进化
```

## 项目结构

```
bilil-AI-tool/
├── README.md              # 项目说明
├── .gitignore             # 排除 .env / __pycache__ / .db
├── .env.example           # 环境变量模板
├── run_daily.py           # 一键每日管道入口
├── PROBLEMS.md            # 已知问题与修复记录
│
├── bili_tool/             # 核心 Python 包
│   ├── __init__.py
│   ├── config.py          # 全局配置：路径、阈值、API Key
│   ├── storage.py         # SQLite 持久化 (candidates/taste/history)
│   ├── bili_api.py        # B站 API 封装 + FunASR GPU 转录
│   ├── taste.py           # 用户口味画像 (话题权重/UP主评分/黑名单)
│   ├── discovery.py       # 四策略并行发现引擎
│   ├── scoring.py         # L1/L2/L3 三层打分逻辑
│   ├── curator.py         # 策展：去重、排序、截断
│   ├── feedback.py        # 三级反馈解析 (auto/ask/conversation)
│   ├── analyzer.py        # DeepSeek API 逐段精校 + 增量保存
│   ├── gpu_monitor.py     # VRAM 实时监视 + 异步转录管理器
│   └── cli.py             # CLI 命令行入口 (所有子命令)
│
└── skills/                # Hermes Agent Skill 文件
    ├── bili-tool/         # 工具使用指南与故障排查
    │   └── SKILL.md
    └── bili-tool-profile/ # 用户内容偏好深度画像
        └── SKILL.md
```

## 快速开始

### 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.10+ | 推荐 3.12 |
| NVIDIA GPU + CUDA | 转录需要 (RTX 4050 6GB 实测可用) |
| B站 SESSDATA | 登录 Cookie |
| DeepSeek API Key | LLM 精校用 |
| Obsidian (可选) | 查看和批注笔记 |

### 安装

```bash
git clone https://github.com/afiuh/bilil-AI-tool.git
cd bilil-AI-tool
pip install requests numpy torch funasr openai
```

### 配置

```bash
cp .env.example bili_tool/.env
# 编辑 bili_tool/.env，填入：
#   BILI_SESSDATA=你的B站Cookie
#   DEEPSEEK_API_KEY=***   DEEPSEEK_BASE_URL=https://api.deepseek.com
#   OBSIDIAN_VAULT_PATH=C:/Users/用户名/Documents/Obsidian 笔记
#   OBSIDIAN_NOTE_DIR=笔记/AI推荐的视频
```

### 测试各模块

```bash
python -m bili_tool.cli check-env      # 环境检查
python -m bili_tool.cli test-bili      # B站 API 连通测试
python -m bili_tool.cli test-asr       # GPU 转录功能测试
python -m bili_tool.cli test-llm       # DeepSeek 精校测试
```

### 运行

```bash
# 一键每日管道
python run_daily.py

# 或分步执行
python -m bili_tool.cli discover       # 仅发现候选
python -m bili_tool.cli score          # 仅打分
python -m bili_tool.cli analyze        # 仅 LLM 精校
```

## CLI 命令参考

| 命令 | 说明 |
|------|------|
| `discover` | 四策略发现候选视频 |
| `score` | 执行 L1/L2/L3 三层打分 |
| `analyze` | DeepSeek LLM 逐段精校 |
| `daily` | 完整每日管道 (发现→打分→精校→写笔记) |
| `status` | 查看当前状态与待阅笔记数 |
| `history` | 查看推荐历史列表 |
| `stats` | 统计信息 |
| `check-env` | 检查环境与依赖 |
| `test-bili` | 测试 B站 API 连通性 |
| `test-asr` | 测试 GPU 转录功能 |
| `test-llm` | 测试 DeepSeek 精校功能 |
| `blacklist add <uid>` | 拉黑指定 UP 主 |
| `blacklist list` | 查看黑名单 |

## 三层打分详解

### L1 — 元数据硬过滤

- 时长 < 5 分钟或 > 180 分钟 → 直接丢弃
- 播放量、弹幕数、硬币数、收藏数、分享数 → 加权基础分
- UP主粉丝数、投稿频率 → 成长性加分
- 标题/标签关键词与用户画像匹配度 → 相关性分

### L2 — 字幕采样分析

- 有 CC 字幕 → 直接提取关键词，匹配用户偏好词库
- 无字幕 → FunASR GPU 转录前 5 分钟，用于关键词匹配
- 内容类型正则检测 → 纪录片/有声书/电视剧/儿童/催眠 → 直接丢弃
- 论证密度评分 (每千字可验证断言数)
- 信息量评估 (概念密度、专有名词频率)

### L3 — 完整深度分析 (LLM)

- 获取完整字幕 (CC 字幕优先，否则 GPU 完整转录)
- 调用 DeepSeek API 逐段处理：
  - 标点补全 + 合理分段
  - 转录错误修正 (根据上下文推断)
  - 逻辑不通处微调 (保留原意)
  - 逐段批注：💡 亮点 / ⚠️ 不足
  - 结尾总结分析 + 推荐建议
- **红线**：不允许省略内容，38 分钟视频必须完整覆盖

## 反馈与交流闭环 (核心特色)

本系统与其他推荐工具最大的不同 —— **不是单向推送，而是双向交流**。

### 流程

```
用户阅读笔记 → 在 Obsidian 中写批注
  ├── 💬 逐段看法 (穿插在精校文本间)
  ├── 📝 视频评论 (笔记末尾总体评价)
  └── 💬 总体反馈 (系统改进建议)
       ↓
助手读取 → 分级判断 → 交流讨论
       ↓
确认后勾选 ✅已交流 → 数据标注 → 权重调整
       ↓
新画像维度写入 bili-tool-profile skill
       ↓
下次推荐更精准
```

### 三级反馈执行

| 级别 | 触发信号示例 | 行为 |
|------|-------------|------|
| **auto** | "完全不喜欢"/"别再推了"/"拉黑" | 自动加入黑名单或更新画像 |
| **auto** | "多推"/"喜欢"/"关注了" | boost 对应话题/UP主风格 |
| **ask** | "不够严谨"/"还行吧"/"有点意思但..." | 写入 `.pending_questions.json`，下次对话逐一确认 |
| **conversation** | 提出新评判标准/纠正系统判断 | 深度交流，提炼新的画像维度 |

### 权重调整规则

- 每条已交流的反馈 → 对应话题权重 ±0.03
- auto 级拉黑 → 对应风格标签直接置零 (不等待已交流)
- conversation 级新维度 → 经确认后写入画像，初始权重 0.5
- 同一维度连续 3 次正向反馈 → 权重锁定 (不再自动下调)

### 推荐节奏

- 每天凌晨 3 点自动检查最新笔记
- **全部已阅** → 生成新推荐
- **有待阅** → 跳过，等待用户看完再推

## 配置参考

### 环境变量 (`.env`)

| 变量 | 必填 | 说明 |
|------|------|------|
| `BILI_SESSDATA` | ✅ | B站登录 Cookie (浏览器 DevTools → Application → Cookies) |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | ❌ | API 地址 (默认 `https://api.deepseek.com`) |
| `OBSIDIAN_VAULT_PATH` | ❌ | Obsidian 仓库路径 |
| `OBSIDIAN_NOTE_DIR` | ❌ | 笔记子目录 (默认 `笔记/AI推荐的视频`) |

### `config.py` 可调参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MIN_DURATION` | 300s | 视频最小时长 |
| `MAX_DURATION` | 10800s | 视频最大时长 |
| `L1_TOP_N` | 50 | L1 阶段保留数 |
| `L2_TOP_N` | 20 | L2 阶段保留数 |
| `L3_TOP_N` | 10 | L3 最终推荐数 |
| `ASR_SAMPLE_SECONDS` | 300 | L2 转录采样时长 |
| `VRAM_THRESHOLD` | 0.85 | GPU 显存使用上限 |
| `LLM_MODEL` | `deepseek-chat` | 精校模型 |
| `LLM_MAX_TOKENS` | 4096 | 单次分析最大 token |

## GPU 转录

使用阿里达摩院 [FunASR](https://github.com/modelscope/FunASR) 的 `paraformer-zh` 模型，为中文语音识别专门优化。

- **触发条件**：视频无 CC 字幕时自动启动 GPU 转录
- **采样策略**：L2 阶段转录前 5 分钟用于筛选，L3 阶段转录完整内容
- **显存管理**：实时监视 VRAM，超过 85% 阈值自动暂停新转录任务
- **异步批量**：支持多视频并行转录，最大化 GPU 利用率

## 内容过滤规则

系统自动排除以下类型，无需手动配置：

| 过滤项 | 过滤阶段 | 原因 |
|--------|---------|------|
| 已关注 UP 主 | L1 | 已是已知信源，不去重推 |
| 纪录片 | L2 | 信息密度过低 |
| 有声书 | L2 | 非原创分析内容 |
| 电视剧原片 | L2 | 非分析类内容 |
| 儿童内容 | L2 | 与用户画像不匹配 |
| 催眠/助眠 | L2 | 无信息量 |
| 高考/应试 | L2 | 用户明确排除 |
| < 5 分钟 | L1 | 不足以展开深度分析 |
| > 3 小时 | L1 | 超出精校处理上限 |

## Hermes Agent 集成

项目包含两个 Hermes Agent Skill，让 AI 助手能理解和操作本系统：

```bash
# 安装 skill 到本地 Hermes
cp -r skills/bili-tool ~/.hermes/skills/
cp -r skills/bili-tool-profile ~/.hermes/skills/
```

- **`bili-tool` skill** — 工具使用指南、完整管道流程文档、故障排查手册
- **`bili-tool-profile` skill** — 用户内容偏好深度画像、量化维度、演化规则

## 故障排查

### B站 API 返回 403

SESSDATA 过期。重新登录 B站，从浏览器 DevTools → Application → Cookies 获取新值，更新 `.env`。

### GPU 转录失败 / CUDA OOM

```bash
# 检查 GPU 状态
nvidia-smi

# 确认 PyTorch CUDA 可用
python -c "import torch; print(torch.cuda.is_available())"

# 释放显存
# 重启 Python 进程，或终止占用 GPU 的其他进程
```

### DeepSeek API 超时或返回不完整

长视频字幕超过 token 限制。调整 `config.py` 中的 `LLM_MAX_TOKENS` 参数，或在 `analyzer.py` 中减小分段大小。

### 笔记未生成

```bash
# 检查是否有未阅笔记阻塞
python -m bili_tool.cli status

# 手动运行各阶段排查
python -m bili_tool.cli discover --verbose
python -m bili_tool.cli score --verbose
python -m bili_tool.cli analyze --verbose
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| B站 API | requests (REST API) |
| GPU 转录 | FunASR paraformer-zh + PyTorch CUDA |
| LLM 精校 | DeepSeek API (OpenAI 兼容) |
| 数据持久化 | SQLite |
| 笔记输出 | Obsidian (Markdown) |
| AI 助手集成 | Hermes Agent Skill |



## 更新日志


### v0.6.0 — 去中心化架构 (2026-06-12)

**删除**
- pool.py (PoolRunner / 全局GPU队列)
- pipeline.py (run_daily / run_daily_5pool 大蛇脚本)
- pipeline_watchdog.py / checkpoint.py / _cp_pause.py
- _review.py / _review_cli.py / run_daily.py

**新模块**
- audio_downloader.py: 音频下载，写 audio_path 到缓存
- transcribe_worker.py: 重写为 ProcessPoolExecutor 子进程转录
- cache.py: 双层缓存(搜索批量文件 + 视频递进文件)

**架构**
去中心化工具模式。8个功能模块零耦合，通过缓存文件夹交换数据。
智能体逐步操作每一步，崩一个不影响其他。

### v0.5.0 — 5池架构完善 + 视频级缓存 (2026-06-11)

**新增**
- 视频级缓存：video_cache/BVxxx.json 按BV号存储打分+字幕，跨管道复用
- 策展后自动清理落选视频缓存
- 2个关键检查点：字幕产出(L2后) + 精校后翻看笔记(自动写入错误日志)
- 笔记模板移除原始字幕区，仅保留精校文本

**修复**
- L1补上已关注UP主过滤（141人视频不推荐）
- 无字幕走GPU转录而非直接毙掉
- VRAM检查增强（同时检测nvidia-smi + PyTorch分配量）
- GPU转录参数修复
- 跨池数据竞争修复

**种子数据**
- 141关注UP主 → UP蔓延 → 发现新UP主
- 64个收藏夹BV号 → 关联推荐 → 发现相似内容
- seed_bvids.json 手动导出，B站API不可用
### v0.4.0 — 5池并行发现引擎 (2026-06-11)

**新增**
-  — 5池并行引擎：PoolRunner 单池自治（搜索→打分→转录→策展），全局 GPU 队列自适应调度
-  — 3 个管道检查点（发现后/打分后/笔记后 + 5池模式），AI 可介入审查
-  — 断点续传缓存，崩了自动恢复，正常结束自动清理
-  — Obsidian 笔记模板集中锁定
-  — 状态查询（纯读）
-  — GPU 转录 + 字幕工具
-  — 定期回顾引擎（5 层分析框架）
-  — 检查点暂停逻辑
-  — CLI  命令

**改动**
-  — 新增  5 线程并行编排， 定期回顾
-  — 双池探索（70% 兴趣 + 30% 探索），种子数据（141 关注 + 收藏夹）注入
-  — 话题上限（ceiling）+ 多样性 floor 双约束
-  — UP 主权重降为 0.20，无字幕视频直接毙掉，鸡汤指数阈值触发制
-  — 分段 API 避免截断，finish_reason 检测，辩证完整性加分维度
-  — 已交流复选框由用户自行勾选
-  — 新增  子命令， 改用 pipeline

**配置**
-  — 11 个可调阈值集中管理（soup/diversity/split/explore/ceiling 等）
-  — 6 个核心分区
-  — 音乐/VOCALOID/翻唱等永久排除

**测试**
-  — 30 个单元测试全部通过

### v0.3.0 — 去中心化工具箱 (2026-06-10)

- 14 模块解耦，AI 可自由组合调用
-  统一导出 40+ 公共 API
- 精校分段改为语义驱动
- 推荐理由关联用户画像维度

### v0.2.0 — 反馈闭环 (2026-06-10)

- 三级反馈解析（auto/ask/conversation）
- 已阅/已交流双复选框
- 定期回顾机制（每 3 天）

### v0.1.0 — 初始版本 (2026-06-10)

- 四策略发现引擎
- L1/L2/L3 三层打分漏斗
- FunASR GPU 转录
- DeepSeek LLM 精校
- Obsidian 笔记输出
## License

MIT © 2026 陈懿灵 (意慎)
