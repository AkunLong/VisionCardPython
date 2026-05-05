import argparse
import binascii
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from app.config import settings

import requests



DEFAULT_CATEGORY = "animal"
BASE_DIR = Path(f"data/{DEFAULT_CATEGORY}")
ITEMS_DIR = BASE_DIR / "items"
AUDIO_DIR = BASE_DIR / "audio" / "item-audio"
if not ITEMS_DIR.exists():
    os.makedirs(ITEMS_DIR)
if not AUDIO_DIR.exists():
    os.makedirs(AUDIO_DIR)

MINIMAX_API_URL = "https://api.minimaxi.com/v1/t2a_v2"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def remove_emoji(text: str) -> str:
    """
    去掉 emoji，避免 TTS 念出奇怪内容。
    """
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
        "\u2600-\u26FF"
        "\u2700-\u27BF"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def normalize_spaces(text: str) -> str:
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def item_slug(item_path: Path, item_data: Dict[str, Any]) -> str:
    item_id = item_data.get("id", "")
    if item_id:
        return item_id
    return item_path.stem


def build_intro_text(content: Dict[str, Any], lang: str) -> str:
    name = content.get("name", "").strip()
    words = content.get("words", "").strip()
    intro = content.get("intro", "").strip()

    if lang == "zh-CN":
        # 中文页：苹果，Apple。xxx
        parts = [name]
        if words:
            parts.append(words)
        prefix = "，".join(parts)
        return normalize_spaces(f"{prefix}。{intro}")

    if lang == "en":
        # 英文页：Apple. xxx
        # en.words 你现在是空，所以不强行读中文辅助词。
        return normalize_spaces(f"{name}. {intro}")

    return normalize_spaces(f"{name}. {intro}")


def build_story_text(content: Dict[str, Any], lang: str) -> str:
    story = content.get("story", {}) or {}
    knowledge = content.get("knowledge", {}) or {}

    story_title = remove_emoji(story.get("title", "")).strip()
    story_body = story.get("body", "").strip()

    knowledge_title = remove_emoji(knowledge.get("title", "")).strip()
    knowledge_body = knowledge.get("body", "").strip()

    if lang == "zh-CN":
        text = (
            f"小故事：{story_title}。"
            f"{story_body} "
            f"故事听完了，再告诉你一个有趣的小知识。"
            f"{knowledge_title}"
            f"{knowledge_body}"
        )
        return normalize_spaces(text)

    if lang == "en":
        text = (
            f"Story time: {story_title}. "
            f"{story_body} "
            f"The story is over. Now let me tell you a fun fact. "
            f"{knowledge_title} "
            f"{knowledge_body}"
        )
        return normalize_spaces(text)

    return normalize_spaces(f"{story_title}. {story_body} {knowledge_title} {knowledge_body}")


def get_content(item_data: Dict[str, Any], lang: str) -> Optional[Dict[str, Any]]:
    content = item_data.get("content", {})
    lang_content = content.get(lang)
    if not isinstance(lang_content, dict):
        return None
    return lang_content


def call_minimax_tts(
    text: str,
    output_path: Path,
    voice_id: str,
    model: str,
    language_boost: str,
    speed: float,
    volume: float,
    pitch: int,
    sample_rate: int,
    bitrate: int,
    max_retries: int = 3,
) -> None:
    """
    调用 MiniMax TTS，同步生成 mp3。
    使用 output_format=hex，直接把返回的 hex 音频写成 mp3 文件。
    """
    headers = {
        "Authorization": f"Bearer {settings.MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "text": text,
        "stream": False,
        "language_boost": language_boost,
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
                timeout=120,
            )
            response.raise_for_status()

            result = response.json()

            base_resp = result.get("base_resp", {})
            status_code = base_resp.get("status_code")

            if status_code not in (0, None):
                raise RuntimeError(f"MiniMax API error: {base_resp}")

            audio_hex = (result.get("data") or {}).get("audio")
            if not audio_hex:
                raise RuntimeError(f"MiniMax 返回里没有 data.audio: status={result.get('base_resp', {})}")

            audio_bytes = binascii.unhexlify(audio_hex)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio_bytes)
            return

        except Exception as e:
            last_error = e
            print(f"    第 {attempt} 次生成失败: {e}")
            time.sleep(2)

    raise RuntimeError(f"TTS 生成失败: {output_path}，最后错误: {last_error}")


def relative_audio_path_for_json(lang: str, file_name: str) -> str:
    return f"../item-audio/{lang}/{file_name}"


def update_audio_url(item_data: Dict[str, Any], lang: str, intro_file: str, story_file: str) -> None:
    if "content" not in item_data:
        item_data["content"] = {}

    if lang not in item_data["content"]:
        item_data["content"][lang] = {}

    if "audio_url" not in item_data["content"][lang]:
        item_data["content"][lang]["audio_url"] = {}

    item_data["content"][lang]["audio_url"]["intro"] = relative_audio_path_for_json(lang, intro_file)
    item_data["content"][lang]["audio_url"]["story"] = relative_audio_path_for_json(lang, story_file)


def iter_item_files(items_dir: Path) -> Iterable[Path]:
    return sorted(items_dir.glob("*.json"))


def main(item_name: str = None, task_type: str = "all") -> None:
    """
    :param item_name: 如果指定，则只处理该 item 并强制覆盖。
    :param task_type: 可选 "all", "intro", "story"。指定生成哪部分音频。
    """
    parser = argparse.ArgumentParser(description="批量为 items 生成 MiniMax TTS 音频。")

    # 基础配置参数
    parser.add_argument("--category", default="animal", help="品类名称，如 animal, fruit, flower 等")
    parser.add_argument("--items-dir", default=None, help="items JSON 目录（默认 data/{category}/items）")
    parser.add_argument("--audio-dir", default=None, help="音频输出目录（默认 data/{category}/audio/item-audio）")
    parser.add_argument("--model", default="speech-2.8-turbo", help="MiniMax TTS 模型")
    parser.add_argument("--overwrite", action="store_true", help="是否覆盖已存在音频")
    parser.add_argument("--update-json", action="store_true", help="生成后是否回写 item json")

    # 限制与起始（批量模式使用）
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)

    # 音频参数
    parser.add_argument("--zh-voice", default=os.getenv("MINIMAX_ZH_VOICE_ID", "Chinese (Mandarin)_Cute_Spirit"))
    parser.add_argument("--en-voice", default=os.getenv("MINIMAX_EN_VOICE_ID", "English_radiant_girl"))
    parser.add_argument("--speed", type=float, default=0.88)
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=32000)
    parser.add_argument("--bitrate", type=int, default=128000)

    # 允许从函数参数或命令行传入
    parser.add_argument("--item-name", default=item_name)
    parser.add_argument("--task-type", default=task_type, choices=["all", "intro", "story"], help="生成任务类型")

    args = parser.parse_args()

    category = args.category
    items_dir = Path(args.items_dir) if args.items_dir else Path(f"data/{category}/items")
    audio_dir = Path(args.audio_dir) if args.audio_dir else Path(f"data/{category}/audio/item-audio")

    # 1. 筛选文件
    all_files = list(iter_item_files(items_dir))

    if args.item_name:
        # 单项模式逻辑
        item_files = [f for f in all_files if args.item_name in f.name]
        if not item_files:
            print(f"❌ 找不到匹配 '{args.item_name}' 的文件")
            return
        args.overwrite = True  # 指定单项时默认开启覆盖
        print(f"🎯 单项重跑模式: {item_files[0].name} | 任务类型: {args.task_type}")
    else:
        # 批量模式逻辑
        item_files = all_files
        if args.start > 0: item_files = item_files[args.start:]
        if args.limit > 0: item_files = item_files[:args.limit]
        print(f"🚀 批量模式: 准备处理 {len(item_files)} 个项")

    # 2. 循环处理
    failed_items = []

    for index, item_path in enumerate(item_files, start=1):
        item_data = load_json(item_path)
        slug = item_slug(item_path, item_data)

        print(f"\n[{index}/{len(item_files)}] 处理: {item_path.name}")

        try:
            for lang in ["zh-CN", "en"]:
                content = get_content(item_data, lang)
                if not content: continue

                voice_id = args.zh_voice if lang == "zh-CN" else args.en_voice
                language_boost = "Chinese" if lang == "zh-CN" else "English"

                # 确定输出文件名
                intro_file = f"{slug}_intro.mp3"
                story_file = f"{slug}_story.mp3"
                (audio_dir / lang).mkdir(parents=True, exist_ok=True)

                # --- 任务筛选逻辑 ---
                all_tasks = [
                    ("intro", build_intro_text(content, lang), audio_dir / lang / intro_file),
                    ("story", build_story_text(content, lang), audio_dir / lang / story_file),
                ]

                # 根据 task_type 过滤任务
                tasks_to_run = []
                if args.task_type == "all":
                    tasks_to_run = all_tasks
                else:
                    tasks_to_run = [t for t in all_tasks if t[0] == args.task_type]

                # 执行任务
                for task_name, text, output_path in tasks_to_run:
                    if output_path.exists() and not args.overwrite:
                        print(f"  跳过 {lang}/{task_name}: 已存在")
                        continue

                    if not text:
                        print(f"  跳过 {lang}/{task_name}: 文案为空")
                        continue

                    print(f"  生成 {lang}/{task_name} -> {output_path.name}")

                    call_minimax_tts(
                        text=text,
                        output_path=output_path,
                        voice_id=voice_id,
                        model=args.model,
                        language_boost=language_boost,
                        speed=args.speed,
                        volume=args.volume,
                        pitch=args.pitch,
                        sample_rate=args.sample_rate,
                        bitrate=args.bitrate,
                    )
                    time.sleep(0.8)

                # 回写 JSON（仅在当前语言的任务包含在生成的任务中时更新，或者全部更新）
                if args.update_json:
                    update_audio_url(item_data, lang, intro_file, story_file)

            if args.update_json:
                save_json(item_path, item_data)

        except Exception as e:
            print(f"  ❌ 处理失败: {item_path.name} — {e}")
            failed_items.append({"file": item_path.name, "error": str(e)})

    if failed_items:
        print(f"\n⚠️  {len(failed_items)} 个 item 音频生成失败:")
        for fi in failed_items:
            print(f"  - {fi['file']}: {fi['error']}")
    else:
        print("\n✅ 处理完成，无失败。")





if __name__ == "__main__":
    main(task_type="all")