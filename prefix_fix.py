"""
prefix_fix.py — 给所有品类文件统一加 {category}_ 前缀

涉及目录：
  - items/*.json                          → 文件名 + JSON内 id/sku_id + audio_url 引用
  - audio/item-audio/{zh-CN,en}/*.mp3     → 文件名加前缀
  - audio/tags-audio/{zh-CN,en}/*.mp3     → 文件名加前缀
  - images/{main,story,knowledge,prompts} → 文件名加前缀
  - index.json                            → items[].id 同步更新
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"

#CATEGORIES = ["animal", "fruit", "flower", "food", "number", "object", "person", "plant", "transport", "vegetable"]
CATEGORIES = ["animal", "fruit", "flower", "food", "number", "object", "person", "plant", "transport", "vegetable"]

SKIP_FILES = {"example.json", "example_intro.mp3", "example_story.mp3", ".DS_Store"}


def needs_prefix(filename: str, category: str) -> bool:
    if filename in SKIP_FILES:
        return False
    if filename.startswith(f"{category}_"):
        return False
    if filename.startswith("."):
        return False
    return True


def rename_file(old_path: Path, new_path: Path, dry_run: bool) -> bool:
    if old_path == new_path or new_path.exists():
        return False
    tag = "[DRY]" if dry_run else "[RENAME]"
    print(f"    {tag} {old_path.relative_to(PROJECT_ROOT)} → {new_path.name}")
    if not dry_run:
        old_path.rename(new_path)
    return True


def fix_items(category: str, dry_run: bool) -> int:
    items_dir = DATA_DIR / category / "items"
    if not items_dir.is_dir():
        return 0
    count = 0
    for f in sorted(items_dir.glob("*.json")):
        if not needs_prefix(f.name, category):
            continue
        # 读 JSON 更新 id 和 sku_id
        data = json.loads(f.read_text(encoding="utf-8"))
        old_id = data.get("id", "")
        if old_id and not old_id.startswith(f"{category}_"):
            new_id = f"{category}_{old_id}"
            tag = "[DRY]" if dry_run else "[UPDATE]"
            print(f"    {tag} {f.name}: id '{old_id}' → '{new_id}'")
            data["id"] = new_id
            # sku_id 也跟着改
            old_sku = data.get("sku_id", "")
            if old_sku and not old_sku.startswith(f"card_{category}_"):
                new_sku = old_sku.replace("card_", f"card_{category}_", 1) if old_sku.startswith("card_") else f"card_{category}_{old_sku}"
                print(f"    {tag} {f.name}: sku_id '{old_sku}' → '{new_sku}'")
                data["sku_id"] = new_sku
            if not dry_run:
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 更新 audio_url 引用
        text = f.read_text(encoding="utf-8") if dry_run else json.dumps(data, ensure_ascii=False, indent=2)
        new_text = re.sub(
            r'(?<!\w)([a-z][a-z_0-9]+_(?:intro|story)\.mp3)',
            lambda m: m.group(1) if m.group(1).startswith(f"{category}_") else f"{category}_{m.group(1)}",
            text
        )
        if new_text != text:
            tag = "[DRY]" if dry_run else "[UPDATE]"
            print(f"    {tag} {f.name}: 更新 audio_url 引用")
            if not dry_run:
                f.write_text(new_text, encoding="utf-8")

        # 重命名文件
        new_name = f"{category}_{f.name}"
        count += rename_file(f, items_dir / new_name, dry_run)
    return count


def fix_audio(category: str, dry_run: bool) -> int:
    count = 0
    for sub in ["item-audio", "tags-audio"]:
        audio_dir = DATA_DIR / category / "audio" / sub
        if not audio_dir.is_dir():
            continue
        for lang_dir in audio_dir.iterdir():
            if not lang_dir.is_dir():
                continue
            for f in sorted(lang_dir.iterdir()):
                if not f.is_file() or not needs_prefix(f.name, category):
                    continue
                new_name = f"{category}_{f.name}"
                count += rename_file(f, lang_dir / new_name, dry_run)
    return count


def fix_images(category: str, dry_run: bool) -> int:
    count = 0
    image_dir = DATA_DIR / category / "images"
    if not image_dir.is_dir():
        return 0
    for sub in ["main", "story", "knowledge", "prompts"]:
        sub_dir = image_dir / sub
        if not sub_dir.is_dir():
            continue
        for f in sorted(sub_dir.iterdir()):
            if not f.is_file() or not needs_prefix(f.name, category):
                continue
            new_name = f"{category}_{f.name}"
            count += rename_file(f, sub_dir / new_name, dry_run)
    return count


def fix_index_json(category: str, dry_run: bool) -> int:
    index_path = DATA_DIR / category / "index.json"
    if not index_path.exists():
        return 0
    data = json.loads(index_path.read_text(encoding="utf-8"))
    changed = False
    for item in data.get("items", []):
        old_id = item.get("id", "")
        if old_id and not old_id.startswith(f"{category}_"):
            new_id = f"{category}_{old_id}"
            tag = "[DRY]" if dry_run else "[UPDATE]"
            print(f"    {tag} index.json: id '{old_id}' → '{new_id}'")
            item["id"] = new_id
            changed = True
    if changed and not dry_run:
        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if changed else 0


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="给所有品类文件统一加 {category}_ 前缀")
    parser.add_argument("--run", action="store_true", help="实际执行（默认只预览）")
    args = parser.parse_args()

    dry_run = not args.run
    if dry_run:
        print("⚠️  预览模式，加 --run 实际执行\n")

    total = 0
    for category in CATEGORIES:
        cat_dir = DATA_DIR / category
        if not cat_dir.is_dir():
            continue
        print(f"\n{'='*50}")
        print(f"  品类: {category}")
        print(f"{'='*50}")

        print(f"  [items]")
        total += fix_items(category, dry_run)
        print(f"  [audio]")
        total += fix_audio(category, dry_run)
        print(f"  [images]")
        total += fix_images(category, dry_run)
        print(f"  [index.json]")
        total += fix_index_json(category, dry_run)

    print(f"\n{'预览' if dry_run else '执行'}完成，共 {total} 项变更")


if __name__ == "__main__":
    main()
