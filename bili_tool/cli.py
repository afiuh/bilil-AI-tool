"""CLI 辅助命令。"""
import logging

def cmd_clean():
    """清理所有缓存数据。"""
    import shutil
    from bili_tool.cache import CACHE_ROOT
    for d in [CACHE_ROOT / 'run', CACHE_ROOT / 'video_cache', CACHE_ROOT / 'cache']:
        if d.exists():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
    print('缓存清理完成')

def main():
    import sys
    cmds = {'clean': cmd_clean}
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print('用法: python -m bili_tool.cli [clean]')

if __name__ == '__main__':
    main()
