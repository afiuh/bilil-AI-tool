#!/usr/bin/env python3
"""bili_tool 每日自动化管道入口。

运行完整流程：发现候选 → 三层打分 → LLM精校 → 写入Obsidian笔记。
"""
from bili_tool.cli import cmd_daily

if __name__ == "__main__":
    cmd_daily()
