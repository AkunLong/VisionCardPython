"""
fruit_rename.py — 给 fruit 品类的文件名加 fruit_ 前缀，与其他品类统一

涉及：
  - items/*.json           → fruit_*.json
  - audio/item-audio/      → 文件名加 fruit_ 前缀
  - audio/tags-audio/      → 文件名加 fruit_ 前缀
  - images/main,story,knowledge,prompts/ → 文件名加 fruit_ 前缀
  - items JSON 内 audio_url 引用路径同步更新
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
FRUIT_DIR = PROJECT_ROOT / "data" / "fruit"
ITEMS_DIR = FRUIT_DIR / "items"
IMAGE_DIR = FRUIT_DIR / "images"

# 已有 fruit_ 前缀的跳过（如 example.json、fruit_hami_melon.json）
SKIP_NAMES = {"example.json"}


def rename_file(old_path: Path, new_path: Path, dry_run: bool = True) -> bool:
    if old_path == new_path or new_path.exists():
        return False
    tag = "[DRY]" if dry_run else "[RENAME]"
    print(f"  {tag} {old_path.name} → {new_path.name}")
    if not dry_run:
        old_path.rename(new_path)
    return True


def rename_items(dry_run: bool = True) -> int:
    """items/*.json → fruit_*.json"""
    count = 0
    for f in sorted(ITEMS_DIR.glob("*.json")):
        if f.name in SKIP_NAMES or f.name.startswith("fruit_"):
            continue
        new_path = ITEMS_DIR / f"fruit_{f.name}"
        count += rename_file(f, new_path, dry_run)
    return count


def rename_audio(dry_run: bool = True) -> int:
    """audio/item-audio/ 和 audio/tags-audio/ 下的 mp3 文件加前缀"""
    count = 0
    for sub in ["item-audio", "tags-audio"]:
        audio_dir = FRUIT_DIR / "audio" / sub
        if not audio_dir.is_dir():
            continue
        for lang_dir in audio_dir.iterdir():
            if not lang_dir.is_dir():
                continue
            for f in sorted(lang_dir.glob("*")):
                if not f.is_file() or f.name.startswith("fruit_"):
                    continue
                new_path = lang_dir / f"fruit_{f.name}"
                count += rename_file(f, new_path, dry_run)
    return count


def rename_images(dry_run: bool = True) -> int:
    """images/ 下 main, story, knowledge, prompts 子目录的文件加前缀"""
    count = 0
    for sub in ["main", "story", "knowledge", "prompts"]:
        sub_dir = IMAGE_DIR / sub
        if not sub_dir.is_dir():
            continue
        for f in sorted(sub_dir.iterdir()):
            if not f.is_file() or f.name.startswith("fruit_"):
                continue
            new_path = sub_dir / f"fruit_{f.name}"
            count += rename_file(f, new_path, dry_run)
    return count


def update_json_audio_urls(dry_run: bool = True) -> int:
    """更新 items JSON 内的 audio_url 引用路径：apple_intro.mp3 → fruit_apple_intro.mp3"""
    count = 0
    for f in sorted(ITEMS_DIR.glob("*.json")):
        if f.name in SKIP_NAMES:
            continue
        text = f.read_text(encoding="utf-8")
        new_text = text
        # 匹配 ../item-audio-audio/ 或直接文件名中的 mp3 引用
        # 将 "xxx.mp3" 中不含 fruit_ 前缀的加上
        new_text = re.sub(
            r'(?<!fruit_)(?<=/)([a-z][a-z_0-9]+_(?:intro|story|knowledge)\.mp3)',
            r'fruit_\1',
            new_text
        )

        if new_text != text:
            tag = "[DRY]" if dry_run else "[UPDATE]"
            print(f"  {tag} {f.name}: 更新 audio_url 引用")
            if not dry_run:
                f.write_text(new_text, encoding="utf-8")
            count += 1
    return count


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="给 fruit 品类文件名加 fruit_ 前缀")
    parser.add_argument("--run", action="store_true", help="实际执行（默认只预览）")
    args = parser.parse_args()

    dry_run = not args.run
    if dry_run:
        print("⚠️  预览模式，加 --run 实际执行\n")

    total = 0
    print("📦 items JSON 文件重命名:")
    total += rename_items(dry_run)

    print("\n📦 audio 文件重命名:")
    total += rename_audio(dry_run)

    print("\n📦 images 文件重命名:")
    total += rename_images(dry_run)

    print("\n📦 JSON 内 audio_url 路径更新:")
    total += update_json_audio_urls(dry_run)

    print(f"\n{'预览' if dry_run else '执行'}完成，共 {total} 项变更")


if __name__ == "__main__":
    main()
