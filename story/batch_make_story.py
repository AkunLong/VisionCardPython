import argparse
import binascii
import csv
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml
from openai import OpenAI

from app.config import settings


BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "睡前故事120篇.csv"
PROMPT_FILE = BASE_DIR / "Story_prompt.yaml"
TEXT_DIR = BASE_DIR / "story_text"
AUDIO_DIR = BASE_DIR / "story_audio"

DEEPSEEK_API_BASE = "https://api.deepseek.com"
MINIMAX_API_URL = "https://api.minimaxi.com/v1/t2a_v2"


# ── CSV 解析 ──────────────────────────────────────────────

def load_story_list(csv_path: Path) -> List[Dict[str, str]]:
    """
    读取 CSV，forward-fill 类别列。
    返回 [{"category": "动物冒险类", "title": "小兔子丢了那颗红纽扣"}, ...]
    """
    stories: List[Dict[str, str]] = []
    current_category = ""

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # 跳过表头

        for row in reader:
            if not row or (not row[0].strip() and (len(row) < 2 or not row[1].strip())):
                continue

            if row[0].strip():
                current_category = row[0].strip()

            raw_title = row[1].strip() if len(row) > 1 else ""
            title = raw_title.strip("《》").strip()

            if title:
                stories.append({
                    "category": current_category,
                    "title": title,
                })

    return stories


# ── Prompt 加载 ────────────────────────────────────────────

def load_prompts(yaml_path: Path) -> Dict[str, str]:
    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return {
        "system_prompt": data.get("system_prompt", ""),
        "user_prompt_template": data.get("user_prompt", ""),
    }


def build_messages(prompts: Dict[str, str], story_title: str) -> List[Dict[str, str]]:
    user_content = prompts["user_prompt_template"].replace("{故事标题}", story_title)

    return [
        {"role": "system", "content": prompts["system_prompt"]},
        {"role": "user", "content": user_content},
    ]


# ── DeepSeek 故事生成 ──────────────────────────────────────

def call_deepseek(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("模型返回为空。")

    content = content.strip()
    content = re.sub(r"^```\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    return content.strip()


def generate_story_text(
    client: OpenAI,
    model: str,
    prompts: Dict[str, str],
    story_title: str,
    max_retries: int = 3,
) -> str:
    messages = build_messages(prompts, story_title)
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            text = call_deepseek(client, model, messages)

            char_count = len(text.replace(" ", "").replace("\n", ""))
            if char_count < 1500:
                raise ValueError(f"故事太短，仅 {char_count} 字，要求 2000-2200 字。")

            return text

        except Exception as e:
            last_error = e
            print(f"    第 {attempt} 次生成失败: {e}")

            repair_prompt = (
                f"上一次输出不符合要求，错误是：{e}\n\n"
                f"请重新创作故事《{story_title}》，只输出故事正文，"
                f"不要输出标题、Markdown 或任何说明。"
            )
            messages.append({"role": "assistant", "content": "上一版故事未通过校验。"})
            messages.append({"role": "user", "content": repair_prompt})

            time.sleep(1.5)

    raise RuntimeError(f"《{story_title}》生成失败，已重试 {max_retries} 次。最后错误: {last_error}")


# ── MiniMax TTS ────────────────────────────────────────────

def remove_emoji(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "☀-⛿"
        "✀-➿"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def normalize_text_for_tts(text: str) -> str:
    text = remove_emoji(text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def call_minimax_tts(
    text: str,
    output_path: Path,
    voice_id: str,
    model: str = "speech-2.8-turbo",
    speed: float = 0.88,
    volume: float = 1.0,
    pitch: int = 0,
    sample_rate: int = 32000,
    bitrate: int = 128000,
    max_retries: int = 3,
) -> None:
    headers = {
        "Authorization": f"Bearer {settings.MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "text": text,
        "stream": False,
        "language_boost": "Chinese",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": volume,
            "pitch": pitch,
        },
        "audio_setting": {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": "mp3",
            "channel": 1,
        },
    }

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                MINIMAX_API_URL,
                headers=headers,
                json=payload,
                timeout=180,
            )
            response.raise_for_status()

            result = response.json()
            base_resp = result.get("base_resp", {})
            status_code = base_resp.get("status_code")

            if status_code not in (0, None):
                raise RuntimeError(f"MiniMax API error: {base_resp}")

            audio_hex = (result.get("data") or {}).get("audio")
            if not audio_hex:
                raise RuntimeError(f"MiniMax 返回里没有 data.audio: {result.get('base_resp', {})}")

            audio_bytes = binascii.unhexlify(audio_hex)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio_bytes)
            return

        except Exception as e:
            last_error = e
            print(f"    第 {attempt} 次 TTS 失败: {e}")
            time.sleep(2)

    raise RuntimeError(f"TTS 生成失败: {output_path}，最后错误: {last_error}")


# ── 主流程 ─────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="批量生成睡前故事文本和音频。")
    parser.add_argument("--model", default="deepseek-v4-pro", help="DeepSeek 模型名")
    parser.add_argument("--tts-model", default="speech-2.8-turbo", help="MiniMax TTS 模型名")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有文件")
    parser.add_argument("--start", type=int, default=0, help="从第几个故事开始，0 表示从头")
    parser.add_argument("--limit", type=int, default=0, help="最多处理几个，0 表示不限制")
    parser.add_argument(
        "--task-type",
        default="all",
        choices=["all", "text", "audio"],
        help="任务类型：all=文本+音频，text=仅文本，audio=仅音频",
    )
    parser.add_argument("--zh-voice", default=os.getenv("MINIMAX_ZH_VOICE_ID", "Chinese (Mandarin)_Cute_Spirit"))
    parser.add_argument("--speed", type=float, default=0.92)
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=32000)
    parser.add_argument("--bitrate", type=int, default=128000)
    args = parser.parse_args()

    # ── 加载故事列表和 prompt ──
    stories = load_story_list(CSV_FILE)
    prompts = load_prompts(PROMPT_FILE)

    if args.start > 0:
        stories = stories[args.start:]
    if args.limit > 0:
        stories = stories[:args.limit]

    print(f"准备处理 {len(stories)} 个故事")
    print(f"文本模型: {args.model} | TTS 模型: {args.tts_model} | 任务类型: {args.task_type}")

    # ── 初始化 DeepSeek 客户端 ──
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        raise EnvironmentError("请先设置 DEEPSEEK_API_KEY。")

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_API_BASE)

    # ── 循环处理 ──
    failed_items = []

    for index, story in enumerate(stories, start=1):
        category = story["category"]
        title = story["title"]

        category_text_dir = TEXT_DIR / category
        category_audio_dir = AUDIO_DIR / category
        category_text_dir.mkdir(parents=True, exist_ok=True)
        category_audio_dir.mkdir(parents=True, exist_ok=True)

        text_file = category_text_dir / f"{title}.txt"
        audio_file = category_audio_dir / f"{title}.mp3"

        print(f"\n[{index}/{len(stories)}] {category} — 《{title}》")

        # ── 生成文本 ──
        if args.task_type in ("all", "text"):
            if text_file.exists() and not args.overwrite:
                print(f"  文本已存在，跳过: {text_file.name}")
            else:
                try:
                    print(f"  生成文本...")
                    story_text = generate_story_text(client, args.model, prompts, title)
                    text_file.write_text(story_text, encoding="utf-8")
                    print(f"  已保存: {text_file}")
                except Exception as e:
                    print(f"  ❌ 文本生成失败: {e}")
                    failed_items.append({"title": title, "category": category, "task": "text", "error": str(e)})
                    if args.task_type == "all":
                        continue

        # ── 生成音频 ──
        if args.task_type in ("all", "audio"):
            if audio_file.exists() and not args.overwrite:
                print(f"  音频已存在，跳过: {audio_file.name}")
            else:
                if text_file.exists():
                    tts_text = text_file.read_text(encoding="utf-8")
                else:
                    print(f"  ⚠️ 文本文件不存在，跳过音频: {text_file}")
                    failed_items.append({"title": title, "category": category, "task": "audio", "error": "文本文件不存在"})
                    continue

                try:
                    tts_text = normalize_text_for_tts(tts_text)
                    print(f"  生成音频...")
                    call_minimax_tts(
                        text=tts_text,
                        output_path=audio_file,
                        voice_id=args.zh_voice,
                        model=args.tts_model,
                        speed=args.speed,
                        volume=args.volume,
                        pitch=args.pitch,
                        sample_rate=args.sample_rate,
                        bitrate=args.bitrate,
                    )
                    print(f"  已保存: {audio_file}")
                except Exception as e:
                    print(f"  ❌ 音频生成失败: {e}")
                    failed_items.append({"title": title, "category": category, "task": "audio", "error": str(e)})

        time.sleep(0.8)

    # ── 汇总 ──
    if failed_items:
        print(f"\n⚠️  {len(failed_items)} 个任务失败:")
        for fi in failed_items:
            print(f"  - [{fi['task']}] 《{fi['title']}》({fi['category']}): {fi['error']}")
    else:
        print("\n✅ 全部处理完成，无失败。")


if __name__ == "__main__":
    main()
