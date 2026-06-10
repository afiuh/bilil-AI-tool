# bilil-AI-tool

B站高质量内容自动化发现与推荐系统 — AI 驱动的端到端管道。

## 管道概览

```
发现（四策略并行）
  → L1 元数据过滤（时长/类型/已关注UP主）
  → L2 字幕采样分析（CC字幕 + FunASR GPU转录）
  → L3 DeepSeek 逐段精校 + 批注
  → 策展去重排序
  → 写入 Obsidian 笔记
  → 用户反馈闭环（auto/ask/conversation 三级）
```

## 项目结构

```
bili_tool/
├── config.py          # 配置：路径/阈值/API
├── storage.py         # SQLite 数据持久化
├── bili_api.py        # B站 API 封装
├── taste.py           # 用户口味画像
├── discovery.py       # 四策略候选发现
├── scoring.py         # L1/L2/L3 三层打分
├── curator.py         # 策展去重
├── feedback.py        # 三级反馈解析
├── analyzer.py        # DeepSeek LLM 精校
├── gpu_monitor.py     # VRAM 监视 + 异步转录
├── cli.py             # CLI 命令行入口
└── run_daily.py       # 一键日常管道

skills/                 # Hermes Agent Skill 文件
├── bili-tool/          # 工具使用指南
└── bili-tool-profile/  # 用户内容偏好画像
```

## 快速开始

```bash
# 1. 安装依赖
pip install requests numpy torch funasr openai

# 2. 配置 .env
cp .env.example .env
# 编辑 .env，填入 BILI_SESSDATA 和 DEEPSEEK_API_KEY

# 3. 运行
python run_daily.py
```

## 核心特性

- **四策略发现**：关注蔓延 / 关联推荐 / 关键词搜索 / 分区探索
- **GPU 转录**：FunASR paraformer-zh，无 CC 字幕视频自动转录
- **LLM 精校**：DeepSeek API 逐段修正转录错误、补全标点、批注亮点与不足
- **Obsidian 集成**：笔记自动写入 Obsidian 仓库，含已阅/已交流追踪
- **反馈闭环**：auto 自动执行 / ask 待确认 / conversation 深度交流 → 画像持续进化
- **防偷懒红线**：不允许省略内容，38 分钟视频必须完整覆盖

## 环境要求

- Python 3.10+
- NVIDIA GPU + CUDA（转录需要，RTX 4050 6GB 实测可用）
- B站登录 Cookie（SESSDATA）
- DeepSeek API Key
- Obsidian（可选，用于笔记查看）

## License

MIT
