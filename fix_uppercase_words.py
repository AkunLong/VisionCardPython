"""
fix_uppercase_words.py — 检查所有品类 items 中 zh-CN.words 大写的文件，
将 words 改为小写，并删除对应的中文 intro 音频以便重新生成。
"""

import json
from pathlib import Path

CATEGORIES = ["animal", "fruit", "flower", "food", "number", "object", "person", "plant", "transport", "vegetable"]


def main() -> None:
    fixed = []
    skipped = []

    for cat in CATEGORIES:
        items_dir = Path(f"data/{cat}/items")
        audio_dir = Path(f"data/{cat}/audio/item-audio/zh-CN")
        if not items_dir.exists():
            continue

        for f in sorted(items_dir.glob("*.json")):
            if f.name == "example.json":
                continue

            data = json.load(open(f, encoding="utf-8"))
            zh_words = (data.get("content", {}).get("zh-CN", {}).get("words") or "")

            if not (zh_words and zh_words.isupper()):
                continue

            slug = f.stem
            old_words = zh_words
            new_words = zh_words.lower()

            # 修改 JSON
            data["content"]["zh-CN"]["words"] = new_words
            with open(f, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
                fp.write("\n")

            # 删除对应的中文 intro 音频
            intro_audio = audio_dir / f"{slug}_intro.mp3"
            deleted = False
            if intro_audio.exists():
                intro_audio.unlink()
                deleted = True

            fixed.append({
                "category": cat,
                "file": f.name,
                "old_words": old_words,
                "new_words": new_words,
                "audio_deleted": deleted,
            })

    if not fixed:
        print("没有找到 zh-CN.words 为大写的 item。")
        return

    print(f"共修复 {len(fixed)} 个 item：\n")
    for item in fixed:
        audio_status = "已删除音频" if item["audio_deleted"] else "音频不存在"
        print(f"  {item['category']}/{item['file']}  \"{item['old_words']}\" -> \"{item['new_words']}\"  {audio_status}")

    deleted_count = sum(1 for i in fixed if i["audio_deleted"])
    print(f"\n修改了 {len(fixed)} 个 JSON，删除了 {deleted_count} 个中文 intro 音频。")
    print("重新运行 items_audio_make 即可重新生成音频。")


if __name__ == "__main__":
    main()
