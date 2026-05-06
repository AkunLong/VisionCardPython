"""
pipeline_make.py — 串联四步生产流程，遍历所有品类

步骤：
  1. items_make        — 调用 DeepSeek 生成 items JSON
  2. items_audio_make  — 调用 MiniMax TTS 生成 items 音频
  3. tags_audio_make   — 调用 MiniMax TTS 生成 tags 音频
  4. items_image_make  — 调用 LLM+图片接口 生成 items 图片

每个步骤内部已有文件级缓存（已存在则跳过），无需额外去重。
所有输出同时写入 logs/pipeline_YYYYMMDD_HHMMSS.log。
"""

import argparse
import datetime
import io
import subprocess
import sys
from pathlib import Path

#CATEGORIES = ["animal", "fruit", "flower", "food", "number", "object", "person", "plant", "transport", "vegetable"]
CATEGORIES = ["transport"]

STEP_NAMES = {
    "1": "items_make",
    "2": "items_audio_make",
    "3": "tags_audio_make",
    "4": "items_image_make",
}

LOG_DIR = Path(__file__).parent / "logs"


class Tee:
    """同时写入 console 和 log file"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"pipeline_{timestamp}.log"
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)
    print(f"日志文件: {log_path}")
    return log_path


def run_step(cmd: list[str], step_name: str, category: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  [{step_name}] 品类: {category}")
    print(f"  命令: {' '.join(cmd)}")
    print(f"{'='*60}")

    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if result.returncode != 0:
        print(f"  ❌ [{step_name}] {category} 失败 (exit code {result.returncode})")
        return False

    print(f"  ✅ [{step_name}] {category} 完成")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="串联四步生产流程，遍历所有品类")
    parser.add_argument("--categories", nargs="*", default=None, help="指定品类，默认全部")
    parser.add_argument("--steps", nargs="*", default=None, choices=["1", "2", "3", "4"],
                        help="指定执行步骤，默认全部 (1=items_make, 2=items_audio_make, 3=tags_audio_make, 4=items_image_make)")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的文件")
    parser.add_argument("--model", default="deepseek-v4-pro", help="DeepSeek 模型名")
    parser.add_argument("--skip-errors", action="store_true", help="某品类失败时跳过继续下一个")
    args = parser.parse_args()

    log_path = setup_logging()

    categories = args.categories or CATEGORIES
    steps = set(args.steps) if args.steps else {"1", "2", "3", "4"}

    python = sys.executable
    overwrite_flag = ["--overwrite"] if args.overwrite else []

    results: dict[str, dict[str, bool]] = {}

    for cat in categories:
        cat_dir = Path(f"data/{cat}")
        if not cat_dir.is_dir():
            print(f"⚠️  跳过不存在的品类目录: {cat}")
            continue

        results[cat] = {}

        # 步骤 1: items_make
        if "1" in steps:
            cmd = [python, "items_make.py", "--category", cat, "--model", args.model] + overwrite_flag
            ok = run_step(cmd, "步骤1-items_make", cat)
            results[cat]["1"] = ok
            if not ok and not args.skip_errors:
                break

        # 步骤 2: items_audio_make
        if "2" in steps:
            cmd = [python, "items_audio_make.py", "--category", cat] + overwrite_flag + ["--update-json"]
            ok = run_step(cmd, "步骤2-items_audio_make", cat)
            results[cat]["2"] = ok
            if not ok and not args.skip_errors:
                break

        # 步骤 3: tags_audio_make
        if "3" in steps:
            cmd = [python, "tags_audio_make.py", "--category", cat] + overwrite_flag + ["--update-json"]
            ok = run_step(cmd, "步骤3-tags_audio_make", cat)
            results[cat]["3"] = ok
            if not ok and not args.skip_errors:
                break

        # 步骤 4: items_image_make
        if "4" in steps:
            cmd = [python, "items_image_make.py", "--category", cat] + overwrite_flag
            ok = run_step(cmd, "步骤4-items_image_make", cat)
            results[cat]["4"] = ok
            if not ok and not args.skip_errors:
                break

    # 汇总
    print(f"\n{'='*60}")
    print("  汇总")
    print(f"{'='*60}")

    for cat, step_results in results.items():
        status_parts = []
        for step, ok in step_results.items():
            step_name = STEP_NAMES[step]
            status_parts.append(f"{step_name}:{'✅' if ok else '❌'}")
        print(f"  {cat}: {' | '.join(status_parts)}")

    print(f"\n日志已保存: {log_path}")


if __name__ == "__main__":
    main()
