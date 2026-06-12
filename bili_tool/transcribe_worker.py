"""子进程转录工人。独立进程=干净CUDA上下文，退出自动回收显存。"""
import sys, json, os


def main():
    audio_path = sys.argv[1]
    bvid = sys.argv[2]
    try:
        from funasr import AutoModel
        model = AutoModel(
            model="paraformer-zh", device="cuda:0",
            disable_update=True, trust_remote_code=False,
        )
        result = model.generate(input=audio_path, batch_size=1)
        text = result[0].get("text", "") if result else ""
        print(json.dumps({"bvid": bvid, "text": text}))
    except Exception as e:
        print(json.dumps({"bvid": bvid, "text": "", "error": str(e)}))
        sys.exit(1)
    finally:
        try:
            os.unlink(audio_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
