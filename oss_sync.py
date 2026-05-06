"""
oss_sync.py — 增量同步 data/{category}/ 到阿里云 OSS

只上传有变化的文件（基于 MD5 对比），已同步且未修改的自动跳过。
同步记录保存在 .oss_sync_manifest.json 中。
"""

import asyncio
import hashlib
import json
from pathlib import Path

from app.infra.infra_provider import use_oss_save

CATEGORIES = ["animal", "fruit", "flower", "food", "number", "object", "person", "plant", "transport", "vegetable"]
#CATEGORIES = ["fruit","animal","food"]

PROJECT_ROOT = Path(__file__).parent
OSS_PREFIX = "weapp/VisionCard/app/src/assets"
MANIFEST_FILE = PROJECT_ROOT / ".oss_sync_manifest.json"


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect_files(category: str) -> list[tuple[Path, str]]:
    """收集需要同步到 OSS 的文件，返回 (本地绝对路径, 项目相对路径字符串)"""
    data_dir = PROJECT_ROOT / "data"
    results = []

    # 定义需要扫描的目录及其扫描方式 (False=仅根目录, True=递归)
    targets = [
        (data_dir, False),  # data/ 根目录文件 (如 registry.json)
        (data_dir / category, True),  # data/{category}/ 下所有文件
        (data_dir / "tag-icons", True)  # 新增：svg 图标文件夹
    ]

    for path, recursive in targets:
        if not path.exists():
            if path.name == category:  # 仅对必需的 category 目录缺失报错
                print(f"  ⚠️  目录不存在: {path}")
            continue

        # 根据是否递归选择匹配模式
        pattern = "**/*" if recursive else "*"

        # 统一处理文件收集
        for f in sorted(path.glob(pattern) if not recursive else path.rglob("*")):
            if f.is_file():
                # 过滤掉隐藏文件 (如 .DS_Store)
                if f.name.startswith('.'):
                    continue

                rel = f.relative_to(PROJECT_ROOT)
                results.append((f, str(rel)))

    return results


async def sync_category(category: str, manifest: dict) -> None:
    print(f"\n{'='*50}")
    print(f"  同步品类: {category}")
    print(f"{'='*50}")

    files = collect_files(category)
    if not files:
        return

    oss = use_oss_save()
    uploaded = 0
    skipped = 0
    failed = 0

    for local_path, rel_path in files:
        file_md5 = md5_file(local_path)
        manifest_key = rel_path
        previous_md5 = manifest.get(manifest_key)

        if previous_md5 == file_md5:
            skipped += 1
            continue

        oss_path = f"{OSS_PREFIX}/{rel_path}"
        status = "新增" if previous_md5 is None else "更新"
        print(f"  [{status}] {rel_path}")

        ok = await oss.upload_file(str(local_path), oss_path)
        if ok:
            manifest[manifest_key] = file_md5
            uploaded += 1
        else:
            print(f"    ❌ 上传失败: {rel_path}")
            failed += 1

    print(f"\n  {category} 完成: 上传 {uploaded}, 跳过 {skipped}, 失败 {failed}")


async def main() -> None:
    manifest = load_manifest()
    print(f"已加载同步记录，共 {len(manifest)} 条")

    for category in CATEGORIES:
        await sync_category(category, manifest)

    save_manifest(manifest)
    print(f"\n✅ 同步完成，记录已保存到 {MANIFEST_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
