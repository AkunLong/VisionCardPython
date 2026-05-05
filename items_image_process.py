import argparse
import shutil
from pathlib import Path

from PIL import Image

from app.config import settings
from app.infra.media.png_get import img2png_2048x2048

CATEGORIES = ["animal", "fruit", "flower", "food", "number", "object", "person", "plant", "transport", "vegetable"]
#CATEGORIES = ["food"]

PROJECT_ROOT = Path(__file__).parent


def resize_and_compress_jpg(src_path: Path, dst_path: Path, size: int = 2048, quality: int = 85) -> None:
    img = Image.open(src_path)
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst_path, format="JPEG", quality=quality, optimize=True)
    img.close()


def backup_file(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        return dst
    shutil.copy2(src, dst)
    return dst


async def process_main(
    main_dir: Path,
    main_4k_dir: Path,
    main_2k_png_dir: Path,
    overwrite: bool = False,
) -> None:
    """
    主图处理流程：
    1. 备份原始 4K JPG → main-4k/
    2. 抠图生成 2048x2048 PNG → main-2k-png/
    3. PNG 转 2048x2048 JPG → 替换 main/
    """
    jpg_files = sorted(main_dir.glob("*.jpg"))
    print(f"📦 主图处理: 共 {len(jpg_files)} 张")

    for i, jpg_path in enumerate(jpg_files, 1):
        slug = jpg_path.stem.replace("_main", "")
        png_path = main_2k_png_dir / f"{slug}_main.png"

        with Image.open(jpg_path) as check:
            is_4k = check.size[0] > 2048 or check.size[1] > 2048


        if not is_4k and not overwrite:
            print(f"  [{i}/{len(jpg_files)}] {jpg_path.name}: 已是 2048 JPG，跳过")
            continue

        backup_file(jpg_path, main_4k_dir)
        print(f"  [{i}/{len(jpg_files)}] 抠图: {jpg_path.name}")
        try:
            await img2png_2048x2048(str(jpg_path), str(png_path))
        except Exception as e:
            print(f"    ❌ 抠图失败 {jpg_path.name}: {e}")
            continue

        resize_and_compress_jpg(png_path, jpg_path, size=2048, quality=85)


async def process_story_knowledge(
    src_dir: Path,
    backup_dir: Path,
    label: str,
    overwrite: bool = False,
) -> None:
    """
    story / knowledge 处理流程：
    1. 备份原始 4K JPG → {type}-4k/
    2. 缩放压缩成 2048x2048 JPG → 替换原目录
    """
    jpg_files = sorted(src_dir.glob("*.jpg"))
    print(f"📦 {label}处理: 共 {len(jpg_files)} 张")

    for i, jpg_path in enumerate(jpg_files, 1):
        with Image.open(jpg_path) as check:
            if check.size == (2048, 2048) and not overwrite:
                print(f"  [{i}/{len(jpg_files)}] {jpg_path.name}: 已是 2048 JPG，跳过")
                continue
            original_size = check.size

        backup_file(jpg_path, backup_dir)

        print(f"  [{i}/{len(jpg_files)}] {jpg_path.name}: {original_size} → 2048x2048")
        resize_and_compress_jpg(jpg_path, jpg_path, size=2048, quality=85)


async def main() -> None:
    parser = argparse.ArgumentParser(description="图片后处理：主图抠图+压缩，其它图压缩，原始图备份。")
    parser.add_argument("--overwrite", action="store_true", help="是否覆盖已处理的文件")
    parser.add_argument("--skip-main", action="store_true", help="跳过主图处理")
    parser.add_argument("--skip-story", action="store_true", help="跳过故事图处理")
    parser.add_argument("--skip-knowledge", action="store_true", help="跳过知识图处理")

    args = parser.parse_args()

    for category in CATEGORIES:
        image_dir = PROJECT_ROOT / "data" / category / "images"
        backup_base = PROJECT_ROOT / "image-4k" / category

        if not image_dir.exists():
            print(f"⚠️  跳过不存在的品类目录: {category}")
            continue

        print(f"\n{'='*40} 品类: {category} {'='*40}")

        main_dir = image_dir / "main"
        story_dir = image_dir / "story"
        knowledge_dir = image_dir / "knowledge"

        main_4k_dir = backup_base / "main-4k"
        main_2k_png_dir = backup_base / "main-2k-png"
        story_4k_dir = backup_base / "story-4k"
        knowledge_4k_dir = backup_base / "knowledge-4k"

        for d in [main_dir, story_dir, knowledge_dir,
                  main_4k_dir, main_2k_png_dir, story_4k_dir, knowledge_4k_dir]:
            d.mkdir(parents=True, exist_ok=True)

        if not args.skip_main:
            await process_main(main_dir, main_4k_dir, main_2k_png_dir, overwrite=args.overwrite)

        if not args.skip_story:
            await process_story_knowledge(story_dir, story_4k_dir, "故事图", overwrite=args.overwrite)

        if not args.skip_knowledge:
            await process_story_knowledge(knowledge_dir, knowledge_4k_dir, "知识图", overwrite=args.overwrite)

    print("\n✅ 图片后处理完成")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
