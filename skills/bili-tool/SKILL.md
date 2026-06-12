---
name: bili-tool
version: 2.1.0
description: 去中心化B站内容工具箱。按功能拆分，通过缓存文件夹交换数据，智能体逐步操作。
---

## 架构

去中心化工具箱。功能模块间零耦合，只与缓存文件夹交互。

### 功能模块（8个）

| 模块 | 职责 | 关键函数 |
|------|------|---------| 
| discovery.py | 搜索发现 | discover_one_zone(), discover_and_cache() |
| scoring.py | 三层打分 | score_videos(), extract_subtitle_text(), score_chicken_soup() |
| audio_downloader.py | 音频下载 | download_audio() |
| transcribe_worker.py | GPU转录(whisper.cpp) | transcribe_batch() |
| cleanup.py | 缓存清理 | clean_all(), clean_audio(), clean_runs() |
| transcribe_worker.py | GPU转录 | transcribe_batch() |
| curator.py | 策展去重 | check_ready(), curate_from_cache() |
| analyzer.py | DeepSeek精校 | analyze_from_cache() |
| notes.py | Obsidian笔记 | write_note_from_cache() |
| cache.py | 缓存层 | create_run(), read_video(), write_video(), count_ready() |

### 基础设施（9个）

config.py | taste.py | storage.py | feedback.py | gpu_monitor.py | bootstrap.py | bili_api.py | state.py | cli.py

### 数据流

所有模块通过缓存文件夹交换数据：
  ~/.bili_tool/run/<run_id>/_search/   → 搜索批量文件
  ~/.bili_tool/run/<run_id>/candidates/ → 视频递进文件
  ~/.bili_tool/audio/                  → 音频文件

### 智能体操作流程

1. 搜索: discover_one_zone() × 5个分区 → 写入 search批量文件 → split_all_batches() → 拆分视频文件
2. 打分: score_videos() → 读视频文件 → L1/L2/L3 → 写回
3. 提取字幕: extract_subtitle_text() → 有CC的直接用
4. 下载音频: download_audio() → 无CC的视频下载音频
5. GPU转录: transcribe_batch() → ProcessPoolExecutor → 子进程写缓存
6. 检查就绪: curator.check_ready() → 确认全部打分+转录完成
7. 策展: curate_from_cache() → 去重排序 → 删落选文件
8. 精校: analyze_from_cache() → DeepSeek → 写回缓存
9. 笔记: write_note_from_cache() → 读入选文件 → 生成MD

### 清理

智能体说"清理缓存"时调用 。音频>2天、管道>7天自动删。

### 触发词

搜索、打分、转录、策展、精校、笔记、检查状态、清理缓存
