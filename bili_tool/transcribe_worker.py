"""子进程转录工人。独立进程=干净CUDA上下文，退出自动回收显存。"""
import sys, json, os


def main():
    audio_path = sys.argv[1]
    bvid = sys.argv[2]
    result_file = sys.argv[3]  # 结果写到这里
    # 重定向 FunASR 日志到 stderr，stdout 只输出 JSON
    import logging
    logging.getLogger().setLevel(logging.WARNING)
    try:
        from funasr import AutoModel
        model = AutoModel(
            model="paraformer-zh", device="cuda:0",
            disable_update=True, trust_remote_code=False,
        )
        import warnings
        warnings.filterwarnings('ignore')
        result = model.generate(input=audio_path, batch_size=1)
        text = result[0].get("text", "") if result else ""
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump({"bvid": bvid, "text": text}, f, ensure_ascii=False)
    except Exception as e:
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump({"bvid": bvid, "text": "", "error": str(e)}, f)
        sys.exit(1)
    finally:
        try:
            os.unlink(audio_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
