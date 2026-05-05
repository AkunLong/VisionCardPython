import argparse
import binascii
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

from app.config import settings

DEFAULT_CATEGORY = "animal"
BASE_DIR = Path(f"data/{DEFAULT_CATEGORY}")
TAGS_JSON_PATH = BASE_DIR / "tags.json"
TAGS_AUDIO_DIR = BASE_DIR / "audio" / "tags-audio"


MINIMAX_API_URL = "https://api.minimaxi.com/v1/t2a_v2"


def load_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
                raise RuntimeError(f"MiniMax 返回里没有 data.item-audio: {result}")

            audio_bytes = binascii.unhexlify(audio_hex)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio_bytes)
            return

        except Exception as e:
            last_error = e
            print(f"    第 {attempt} 次生成失败: {e}")
            time.sleep(2)

    raise RuntimeError(f"TTS 生成失败: {output_path}，最后错误: {last_error}")


def relative_audio_path(lang: str, file_name: str) -> str:
    return f"audio/tags-audio/{lang}/{file_name}"





def main(update_json: bool = True) -> None:
    parser = argparse.ArgumentParser(description="批量为 audio 生成 MiniMax TTS 音频，并整理图标。")

    parser.add_argument("--category", default="animal", help="品类名称，如 animal, fruit, flower 等")
    parser.add_argument("--tags-json", default=None, help="tags.json 路径（默认 data/{category}/tags.json）")
    parser.add_argument("--tags-dir", default=None, help="audio 输出目录（默认 data/{category}/audio/tags-audio）")
    parser.add_argument("--model", default="speech-2.8-turbo", help="MiniMax TTS 模型")
    parser.add_argument("--overwrite", action="store_true", help="是否覆盖已存在音频")
    parser.add_argument("--update-json", action="store_true", default=update_json, help="生成后是否回写 audio.json")
    parser.add_argument("--skip-tag-icons", action="store_true", help="跳过图标复制")

    # 限制与起始
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

    args = parser.parse_args()

    category = args.category
    tags_json_path = Path(args.tags_json) if args.tags_json else Path(f"data/{category}/tags.json")
    tags_dir = Path(args.tags_dir) if args.tags_dir else Path(f"data/{category}/audio/tags-audio")
    audio_dir = tags_dir

    all_tags = load_json(tags_json_path)

    # 筛选范围
    start = args.start
    end = start + args.limit if args.limit > 0 else len(all_tags)
    tags_to_process = all_tags[start:end]

    if args.start > 0 or args.limit > 0:
        print(f"处理范围: [{start}:{end}]，共 {len(tags_to_process)} 个 tag")


    # 生成音频
    failed_tags = []

    for index, tag in enumerate(tags_to_process, start=1):
        tag_id = tag.get("id", "")
        content = tag.get("content", {})

        if not tag_id:
            print(f"  跳过: 缺少 id")
            continue

        print(f"\n[{index}/{len(tags_to_process)}] 处理: {tag_id}")

        try:
            for lang in ["zh-CN", "en"]:
                lang_content = content.get(lang)
                if not isinstance(lang_content, dict):
                    continue

                name = lang_content.get("name", "").strip()
                if not name:
                    print(f"  跳过 {lang}: 名称为空")
                    continue

                voice_id = args.zh_voice if lang == "zh-CN" else args.en_voice
                language_boost = "Chinese" if lang == "zh-CN" else "English"

                audio_file = f"{category}_{tag_id}.mp3"
                output_path = audio_dir / lang / audio_file

                if output_path.exists() and not args.overwrite:
                    print(f"  跳过 {lang}: 已存在")
                    # 即使跳过生成，也需要写入 audio_url
                    if args.update_json:
                        lang_content["audio_url"] = relative_audio_path(lang, audio_file)
                    continue

                print(f"  生成 {lang} -> {audio_file}")

                call_minimax_tts(
                    text=name,
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

                if args.update_json:
                    lang_content["audio_url"] = relative_audio_path(lang, audio_file)

        except Exception as e:
            print(f"  ❌ 处理失败: {tag_id} — {e}")
            failed_tags.append({"id": tag_id, "error": str(e)})

    # 回写 audio.json
    if args.update_json:
        save_json(tags_json_path, all_tags)
        print(f"\n已更新 {tags_json_path}")

    if failed_tags:
        print(f"\n⚠️  {len(failed_tags)} 个 tag 音频生成失败:")
        for ft in failed_tags:
            print(f"  - {ft['id']}: {ft['error']}")
    else:
        print("\n✅ 处理完成，无失败。")


if __name__ == "__main__":
    main()
